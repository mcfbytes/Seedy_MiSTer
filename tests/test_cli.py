"""CLI paths the workflow calls: aggregate (strict and hunt), render-single, decide, apply-seed."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from seedy import cli
from tests import helpers


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        cli.main(list(argv))
    return out.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        recs = helpers.dse_records()
        for r in recs:
            with open(os.path.join(self.d, f"{r['variant']}-{r['seed']}.json"), "w") as fh:
                json.dump(r, fh)
        self.meta = os.path.join(self.d, "meta.json")
        with open(self.meta, "w") as fh:
            json.dump(dict(helpers.META, mode="hunt", min_met=2), fh)

    def test_aggregate_fails_on_missing_seed(self):
        os.remove(os.path.join(self.d, "candidate-7.json"))
        with self.assertRaises(SystemExit) as e:
            run("aggregate", self.d, "--seeds", "1-30", "--out", os.path.join(self.d, "m.json"))
        self.assertIn("candidate:7", str(e.exception.code))

    def test_hunt_partial_and_single_report(self):
        for s in range(21, 31):
            os.remove(os.path.join(self.d, f"candidate-{s}.json"))
        for s in range(1, 31):
            os.remove(os.path.join(self.d, f"baseline-{s}.json"))
        m = os.path.join(self.d, "m.json")
        run("aggregate", self.d, "--seeds", "1-40", "--variants", "candidate", "--allow-partial",
            "--meta", self.meta, "--out", m)
        merged = json.load(open(m))
        self.assertEqual(len(merged["records"]), 20)
        self.assertEqual(merged["meta"]["not_run"]["candidate"], list(range(21, 41)))
        out = run("render-single", m, "--out-dir", os.path.join(self.d, "r"), "--seed-policy", "if-failing")
        self.assertIn("best_seed=18", out)
        self.assertIn("apply_seed=true", out)
        c = open(os.path.join(self.d, "r", "comment.md")).read()
        self.assertTrue(c.startswith("<!-- seedy:SNES -->"))
        self.assertIn("Seeds meeting timing: 2, 4, 18.", c)
        self.assertIn("Target was 2 seed(s) meeting timing: **reached**", c)

    def test_hunt_not_reached_suggests_continuation(self):
        m = os.path.join(self.d, "m.json")
        for s in range(1, 31):
            os.remove(os.path.join(self.d, f"baseline-{s}.json"))
        for s in (2, 4, 18):
            os.remove(os.path.join(self.d, f"candidate-{s}.json"))
        with open(self.meta, "w") as fh:
            json.dump(dict(helpers.META, mode="hunt", min_met=2, seeds="1-50"), fh)
        run("aggregate", self.d, "--seeds", "1-50", "--variants", "candidate", "--allow-partial",
            "--meta", self.meta, "--out", m)
        run("render-single", m, "--out-dir", os.path.join(self.d, "r"))
        c = open(os.path.join(self.d, "r", "comment.md")).read()
        self.assertIn("**not reached**", c)
        self.assertIn("seed_start: 51", c)  # past the planned range: nothing repeats
        self.assertIn("Closest seed (none met timing)", c)

    def test_decide_and_apply_seed(self):
        best = os.path.join(self.d, "best.json")
        json.dump({"best": 18, "best_met": True, "shipped": 1, "shipped_met": False, "best_why": "x"}, open(best, "w"))
        self.assertIn("apply=false", run("decide", best, "--policy", "never"))
        self.assertIn("apply=true", run("decide", best, "--policy", "if-failing"))
        qsf = os.path.join(self.d, "SNES.qsf")
        open(qsf, "w", newline="").write("a\r\nset_global_assignment -name SEED 1\r\n")
        self.assertIn("changed=true", run("apply-seed", qsf, "--seed", "18"))
        self.assertEqual(open(qsf, newline="").read(), "a\r\nset_global_assignment -name SEED 18\r\n")

    def test_plan_seed_count(self):
        out = dict(l.split("=", 1) for l in run("plan", "--seed-count", "8", "--shards", "3").splitlines())
        self.assertEqual(out["seeds"], "1-8")
        self.assertEqual(len(json.loads(out["matrix"])["include"]), 6)


if __name__ == "__main__":
    unittest.main()
