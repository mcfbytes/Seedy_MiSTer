#!/usr/bin/env python3
"""Scale the Azure runner scale set (terraform/) to the jobs of this workflow run that wait for it.

Runs in .github/workflows/azure-runners.yml, beside the jobs it serves. It watches this run's jobs: when
jobs that ask for LABEL are queued, it adds that many VMs, up to the scale set's seedy-max-instances tag.
Each VM takes a job and deletes itself afterwards, so the scaler never scales in. Jobs still queued
BOOT_GRACE_MINUTES after a scale-up (a VM was evicted or failed, or another run took it) get more VMs. It
stops when no job waits for LABEL any more, or after WAIT_MINUTES without any such job.

Environment: VMSS_ID, AZURE_CLIENT_ID, AZURE_TENANT_ID, LABEL [seedy-azure], WAIT_MINUTES [30],
BOOT_GRACE_MINUTES [8], POLL_SECONDS [20]; from GitHub Actions: GH_TOKEN (actions: read),
GITHUB_REPOSITORY, GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, RUNNER_NAME, and ACTIONS_ID_TOKEN_REQUEST_URL /
ACTIONS_ID_TOKEN_REQUEST_TOKEN (id-token: write) for the OIDC sign-in to Azure. Standard library only.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

ARM = "https://management.azure.com"
ARM_API = "2024-07-01"
QUEUED = {"queued", "requested", "pending"}  # not "waiting": that is an environment approval
MAX_TAG = "seedy-max-instances"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---- decisions (pure, unit-tested) ----

@dataclass
class Census:
    queued: int = 0         # jobs for the label without a runner yet
    running: int = 0        # jobs for the label on a runner
    total: int = 0          # jobs for the label in any state
    others_active: int = 0  # other unfinished jobs of the run (they may still create jobs for the label)


def census(jobs: list[dict], label: str, self_runner: str) -> Census:
    c, want = Census(), label.lower()
    for j in jobs:
        status = j.get("status")
        if want in {str(l).lower() for l in j.get("labels") or []}:
            c.total += 1
            c.queued += status in QUEUED
            c.running += status == "in_progress"
        elif status != "completed" and j.get("runner_name") != self_runner:
            c.others_active += 1
    return c


def to_add(c: Census, last_scale: float | None, now: float, grace_s: float) -> int:
    """VMs to add now: one per queued job, at once, then again only if jobs still wait after the grace."""
    if c.queued == 0:
        return 0
    if last_scale is None or now - last_scale >= grace_s:
        return c.queued
    return 0


def new_capacity(capacity: int, add: int, maximum: int) -> int:
    return max(capacity, min(maximum, capacity + add))


# ---- HTTP ----

def http(method: str, url: str, headers: dict | None = None, body: bytes | None = None,
         timeout: float = 60) -> tuple[int, dict, dict | list | None]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, hdrs, raw = r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        status, hdrs, raw = e.code, dict(e.headers), e.read()
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = {"raw": raw[:500].decode(errors="replace")}
    return status, hdrs, data


class GitHub:
    def __init__(self, token: str, repo: str, run_id: str, attempt: str,
                 api: str = "https://api.github.com"):
        self.token, self.url = token, f"{api}/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs"

    def jobs(self) -> list[dict]:
        out, page = [], 1
        while True:
            status, _, data = http("GET", f"{self.url}?per_page=100&page={page}", {
                "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"})
            if status != 200:
                raise RuntimeError(f"listing this run's jobs: HTTP {status} {data}")
            out += data["jobs"]
            if len(data["jobs"]) < 100 or len(out) >= data.get("total_count", 0):
                return out
            page += 1


class Azure:
    """ARM calls as the scaler identity, signed in with this job's GitHub OIDC token (no stored secret)."""

    def __init__(self, client_id: str, tenant_id: str):
        self.client_id, self.tenant_id = client_id, tenant_id
        self._token, self._expires = "", 0.0

    def token(self) -> str:
        if time.time() < self._expires - 300:
            return self._token
        url, req_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if not url or not req_token:
            raise RuntimeError("no GitHub OIDC token: the calling job needs `permissions: id-token: write`")
        status, _, data = http("GET", url + "&audience=" + urllib.parse.quote("api://AzureADTokenExchange"),
                               {"Authorization": f"bearer {req_token}"})
        if status != 200:
            raise RuntimeError(f"GitHub OIDC token: HTTP {status} {data}")
        form = urllib.parse.urlencode({
            "client_id": self.client_id, "grant_type": "client_credentials",
            "scope": f"{ARM}/.default", "client_assertion": data["value"],
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"}).encode()
        status, _, data = http("POST", f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                               {"Content-Type": "application/x-www-form-urlencoded"}, form)
        if status != 200:
            raise RuntimeError(f"Azure sign-in failed (HTTP {status}): {data.get('error_description', data)}. "
                               "Check the federated credential (repository, environment) and client/tenant IDs.")
        self._token, self._expires = data["access_token"], time.time() + int(data.get("expires_in", 3600))
        return self._token

    def call(self, method: str, path_or_url: str, body: dict | None = None,
             headers: dict | None = None) -> tuple[int, dict, dict | list | None]:
        url = path_or_url if path_or_url.startswith("https://") else f"{ARM}{path_or_url}"
        if "api-version=" not in url:
            url += ("&" if "?" in url else "?") + f"api-version={ARM_API}"
        h = {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json", **(headers or {})}
        return http(method, url, h, json.dumps(body).encode() if body is not None else None)


def arm_error(data) -> str:
    err = (data or {}).get("error") or data or {}
    return f"{err.get('code', '')}: {err.get('message', err)}" if isinstance(err, dict) else str(err)


class ScaleSet:
    def __init__(self, azure: Azure, vmss_id: str):
        self.az, self.id = azure, vmss_id.rstrip("/")

    def scale_out(self, add: int) -> tuple[int, int, int, str | None]:
        """Raise capacity by `add`, up to the max tag. Returns (old, new, max, async operation URL)."""
        for _ in range(5):
            status, hdrs, vmss = self.az.call("GET", self.id)
            if status != 200:
                raise RuntimeError(f"reading the scale set: HTTP {status} {arm_error(vmss)}")
            sku = dict(vmss["sku"])
            cap = int(sku.get("capacity") or 0)
            maximum = int((vmss.get("tags") or {}).get(MAX_TAG, cap + add))
            new = new_capacity(cap, add, maximum)
            if new == cap:
                return cap, cap, maximum, None
            sku["capacity"] = new
            # If-Match: two runs scaling at once must not overwrite each other's increase
            etag = vmss.get("etag") or hdrs.get("ETag") or hdrs.get("Etag")
            status, hdrs, data = self.az.call("PATCH", self.id, {"sku": sku}, {"If-Match": etag} if etag else None)
            if status == 412:
                continue
            if status not in (200, 201, 202):
                raise RuntimeError(f"scaling to {new}: HTTP {status} {arm_error(data)}")
            return cap, new, maximum, hdrs.get("Azure-AsyncOperation") or hdrs.get("azure-asyncoperation")
        raise RuntimeError("scaling: the scale set kept changing under us")

    def wait(self, op_url: str | None, timeout_s: float, sleep=time.sleep) -> str | None:
        """Wait for a scale operation; returns None on success, else the error."""
        deadline = time.time() + timeout_s
        while op_url and time.time() < deadline:
            status, _, data = self.az.call("GET", op_url)
            state = (data or {}).get("status") if status == 200 else None
            if state == "Succeeded":
                return None
            if state in ("Failed", "Canceled"):
                return arm_error(data)
            sleep(10)
        return None

    def remove_failed(self) -> list[str]:
        """Delete VMs that failed to provision (no capacity, quota): they hold capacity but never run."""
        sub_rg = self.id.split("/providers/")[0]
        status, _, data = self.az.call("GET", f"{sub_rg}/providers/Microsoft.Compute/virtualMachines")
        if status != 200:
            return []
        failed = [vm["name"] for vm in data.get("value", [])
                  if ((vm.get("properties") or {}).get("virtualMachineScaleSet") or {}).get("id", "").lower() == self.id.lower()
                  and (vm.get("properties") or {}).get("provisioningState") == "Failed"]
        if failed:
            self.az.call("POST", f"{self.id}/delete", {"instanceIds": failed})
        return failed


# ---- the loop ----

@dataclass
class Settings:
    label: str = "seedy-azure"
    self_runner: str = ""
    wait_s: float = 30 * 60
    grace_s: float = 8 * 60
    poll_s: float = 20
    max_failures: int = 3


def run(github, scaleset, s: Settings, clock=time.time, sleep=time.sleep) -> int:
    started, last_scale, quiet_polls, failures, errors = clock(), None, 0, 0, 0
    while True:
        try:
            c = census(github.jobs(), s.label, s.self_runner)
            errors = 0
        except Exception as e:  # GitHub API hiccup: try again, but not forever
            errors += 1
            log(f"::warning::{e}")
            if errors >= 5:
                log("::error::cannot list this run's jobs")
                return 1
            sleep(s.poll_s)
            continue
        now = clock()

        if c.total and c.queued == 0:
            log(f"done: every job for '{s.label}' has a runner ({c.running} running)")
            return 0
        if not c.total:
            quiet_polls = quiet_polls + 1 if c.others_active == 0 else 0
            if quiet_polls >= 3:
                log(f"done: nothing left in this run that could ask for '{s.label}'")
                return 0
            if now - started > s.wait_s:
                log(f"::warning::no job asked for '{s.label}' within {s.wait_s / 60:.0f} min; stopping")
                return 0

        add = to_add(c, last_scale, now, s.grace_s)
        if add:
            if last_scale is not None:
                removed = scaleset.remove_failed()
                if removed:
                    log(f"::warning::removed VMs that failed to provision: {', '.join(removed)}")
            old, new, maximum, op = scaleset.scale_out(add)
            last_scale = now
            if new == old:
                log(f"{c.queued} job(s) queued; the scale set is at its maximum ({maximum}), waiting for VMs to free up")
            else:
                log(f"{c.queued} job(s) queued: scale set {old} -> {new} VMs (max {maximum})")
                err = scaleset.wait(op, s.grace_s, sleep)
                if err:
                    failures += 1
                    log(f"::warning::scale-out failed: {err}")
                    if failures >= s.max_failures:
                        log(f"::error::scale-out failed {failures} times in a row ({err}). Check the VM quota "
                            "(Spot quota for spot VMs), the VM size's availability in the region, or set spot = false. "
                            "Then cancel this run and re-run it.")
                        return 1
                else:
                    failures = 0
        sleep(s.poll_s)


def main() -> int:
    env = os.environ
    for k in ("VMSS_ID", "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "GH_TOKEN", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        if not env.get(k):
            log(f"::error::{k} is not set")
            return 2
    s = Settings(label=env.get("LABEL") or "seedy-azure", self_runner=env.get("RUNNER_NAME", ""),
                 wait_s=float(env.get("WAIT_MINUTES") or 30) * 60,
                 grace_s=float(env.get("BOOT_GRACE_MINUTES") or 8) * 60,
                 poll_s=float(env.get("POLL_SECONDS") or 20))
    github = GitHub(env["GH_TOKEN"], env["GITHUB_REPOSITORY"], env["GITHUB_RUN_ID"], env.get("GITHUB_RUN_ATTEMPT") or "1",
                    env.get("GITHUB_API_URL") or "https://api.github.com")
    scaleset = ScaleSet(Azure(env["AZURE_CLIENT_ID"], env["AZURE_TENANT_ID"]), env["VMSS_ID"])
    try:
        return run(github, scaleset, s)
    except RuntimeError as e:
        log(f"::error::{e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
