import importlib.util
import os
import sys
import unittest

# cloud/azure/scaler.py is a standalone script, not part of the seedy package
_spec = importlib.util.spec_from_file_location(
    "azure_scaler", os.path.join(os.path.dirname(__file__), "..", "cloud", "azure", "scaler.py"))
scaler = sys.modules["azure_scaler"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scaler)
scaler.log = lambda msg: None

LABELS = ["self-hosted", "seedy-azure"]


def job(status, labels=LABELS, runner=None):
    return {"status": status, "labels": labels, "runner_name": runner}


class FakeGitHub:
    """Serves one job list per poll; the last one repeats."""

    def __init__(self, *polls):
        self.polls, self.calls = list(polls), 0

    def jobs(self):
        self.calls += 1
        p = self.polls[min(self.calls, len(self.polls)) - 1]
        if isinstance(p, Exception):
            raise p
        return p


class FakeScaleSet:
    def __init__(self, capacity=0, maximum=30, errors=()):
        self.capacity, self.maximum, self.errors = capacity, maximum, list(errors)
        self.adds, self.removed = [], 0

    def scale_out(self, add):
        old = self.capacity
        self.capacity = scaler.new_capacity(old, add, self.maximum)
        self.adds.append(add)
        return old, self.capacity, self.maximum, "op" if self.capacity != old else None

    def wait(self, op, timeout_s, sleep):
        return self.errors.pop(0) if self.errors else None

    def remove_failed(self):
        self.removed += 1
        return []


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run(github, scaleset, **kw):
    clock = Clock()
    s = scaler.Settings(self_runner="me", poll_s=20, grace_s=8 * 60, wait_s=30 * 60, **kw)
    return scaler.run(github, scaleset, s, clock=clock, sleep=clock.sleep), clock


PLAN_RUNNING = [job("in_progress", ["ubuntu-26.04"], "hosted 1"), job("in_progress", ["ubuntu-26.04"], "me")]


class CensusTest(unittest.TestCase):
    def test_counts_jobs_for_the_label_only(self):
        jobs = [job("queued"), job("queued", ["self-hosted", "SEEDY-AZURE"]), job("in_progress"),
                job("completed"), job("waiting"), job("queued", ["ubuntu-26.04"]),
                job("in_progress", ["ubuntu-26.04"], "me"), job("completed", ["ubuntu-26.04"])]
        c = scaler.census(jobs, "seedy-azure", "me")
        self.assertEqual((c.queued, c.running, c.total, c.others_active), (2, 1, 5, 1))

    def test_to_add_first_then_after_grace(self):
        c = scaler.Census(queued=5, total=5)
        self.assertEqual(scaler.to_add(c, None, 0, 480), 5)
        self.assertEqual(scaler.to_add(c, 0, 479, 480), 0)
        self.assertEqual(scaler.to_add(c, 0, 480, 480), 5)
        self.assertEqual(scaler.to_add(scaler.Census(total=5, running=5), None, 0, 480), 0)

    def test_new_capacity_respects_max_and_never_shrinks(self):
        self.assertEqual(scaler.new_capacity(0, 30, 30), 30)
        self.assertEqual(scaler.new_capacity(25, 30, 30), 30)
        self.assertEqual(scaler.new_capacity(35, 5, 30), 35)


class RunTest(unittest.TestCase):
    def test_scales_once_for_the_matrix_and_stops_when_all_have_runners(self):
        queued = [job("completed", ["ubuntu-26.04"])] + [job("queued")] * 20
        started = [job("completed", ["ubuntu-26.04"])] + [job("in_progress")] * 20
        gh, ss = FakeGitHub(PLAN_RUNNING, PLAN_RUNNING, queued, queued, started), FakeScaleSet()
        rc, _ = run(gh, ss)
        self.assertEqual(rc, 0)
        self.assertEqual(ss.adds, [20])
        self.assertEqual(ss.capacity, 20)

    def test_tops_up_jobs_still_queued_after_the_grace(self):
        # 3 of 20 VMs never show up (evicted at boot, say): 3 jobs stay queued
        polls = [[job("queued")] * 20] + [[job("in_progress")] * 17 + [job("queued")] * 3] * 30 + \
                [[job("in_progress")] * 20]
        gh, ss = FakeGitHub(*polls), FakeScaleSet()
        rc, _ = run(gh, ss)
        self.assertEqual(rc, 0)
        self.assertEqual(ss.adds, [20, 3])
        self.assertEqual(ss.removed, 1)  # failed VMs are cleared before a top-up

    def test_stops_quietly_when_no_job_asks_for_the_label(self):
        # e.g. Seedy's plan job failed, or the run uses hosted runners only
        gh = FakeGitHub(PLAN_RUNNING, [job("completed", ["ubuntu-26.04"]), job("in_progress", ["ubuntu-26.04"], "me")])
        ss = FakeScaleSet()
        rc, clock = run(gh, ss)
        self.assertEqual((rc, ss.adds), (0, []))
        self.assertLess(clock.t - 1000, 120)

    def test_gives_up_waiting_after_wait_minutes(self):
        ss = FakeScaleSet()
        rc, clock = run(FakeGitHub(PLAN_RUNNING), ss)
        self.assertEqual((rc, ss.adds), (0, []))
        self.assertGreater(clock.t - 1000, 30 * 60)

    def test_at_max_waits_for_vms_to_free_up(self):
        polls = [[job("queued")] * 40] + [[job("in_progress")] * 10 + [job("queued")] * 30] * 30 + \
                [[job("completed")] * 30 + [job("in_progress")] * 10]
        ss = FakeScaleSet(maximum=10)
        rc, _ = run(FakeGitHub(*polls), ss)
        self.assertEqual(rc, 0)
        self.assertEqual(ss.capacity, 10)

    def test_repeated_scale_failures_fail_the_job(self):
        ss = FakeScaleSet(errors=["OperationNotAllowed: quota"] * 3)
        rc, _ = run(FakeGitHub([job("queued")] * 4), ss)
        self.assertEqual(rc, 1)
        self.assertEqual(len(ss.adds), 3)

    def test_github_errors_are_retried_then_fatal(self):
        ok = [job("in_progress")]
        self.assertEqual(run(FakeGitHub(RuntimeError("502"), ok), FakeScaleSet())[0], 0)
        self.assertEqual(run(FakeGitHub(RuntimeError("502")), FakeScaleSet())[0], 1)


class FakeAzure:
    """Answers ARM calls from a script of (status, headers, body) per call; records the requests."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def call(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))
        return self.answers.pop(0)


VMSS_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Compute/virtualMachineScaleSets/seedy-runners"


def vmss(capacity, etag="e1", maximum="30"):
    return 200, {}, {"sku": {"name": "Standard_D8ads_v5", "capacity": capacity}, "tags": {"seedy-max-instances": maximum},
                     "etag": etag}


class ScaleSetTest(unittest.TestCase):
    def test_scale_out_patches_capacity_with_if_match(self):
        az = FakeAzure(vmss(2), (202, {"Azure-AsyncOperation": "https://op"}, None))
        self.assertEqual(scaler.ScaleSet(az, VMSS_ID).scale_out(5), (2, 7, 30, "https://op"))
        method, path, body, headers = az.requests[1]
        self.assertEqual((method, path), ("PATCH", VMSS_ID))
        self.assertEqual(body, {"sku": {"name": "Standard_D8ads_v5", "capacity": 7}})
        self.assertEqual(headers, {"If-Match": "e1"})

    def test_scale_out_retries_when_another_run_changed_it(self):
        az = FakeAzure(vmss(2), (412, {}, None), vmss(4, "e2"), (200, {}, None))
        self.assertEqual(scaler.ScaleSet(az, VMSS_ID).scale_out(5)[:3], (4, 9, 30))
        self.assertEqual(az.requests[3][3], {"If-Match": "e2"})

    def test_scale_out_stops_at_the_max_tag(self):
        az = FakeAzure(vmss(10, maximum="10"))
        self.assertEqual(scaler.ScaleSet(az, VMSS_ID).scale_out(5), (10, 10, 10, None))
        self.assertEqual(len(az.requests), 1)

    def test_wait_reports_a_failed_operation(self):
        az = FakeAzure((200, {}, {"status": "InProgress"}),
                       (200, {}, {"status": "Failed", "error": {"code": "SkuNotAvailable", "message": "no spot"}}))
        self.assertEqual(scaler.ScaleSet(az, VMSS_ID).wait("https://op", 600, sleep=lambda s: None),
                         "SkuNotAvailable: no spot")

    def test_remove_failed_deletes_only_this_scale_sets_failed_vms(self):
        def vm(name, state, vmss_id=VMSS_ID):
            return {"name": name, "properties": {"provisioningState": state, "virtualMachineScaleSet": {"id": vmss_id}}}
        az = FakeAzure((200, {}, {"value": [vm("a", "Failed"), vm("b", "Succeeded"), vm("c", "Failed", VMSS_ID + "x")]}),
                       (202, {}, None))
        self.assertEqual(scaler.ScaleSet(az, VMSS_ID).remove_failed(), ["a"])
        self.assertEqual(az.requests[1][:3], ("POST", VMSS_ID + "/delete", {"instanceIds": ["a"]}))


if __name__ == "__main__":
    unittest.main()
