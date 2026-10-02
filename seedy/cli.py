"""seedy <command>: the CLI the workflow and developers call. Standard library only."""
import argparse
import glob
import json
import os
import re
import shlex
import sys

from seedy import __version__, compare, files, plan, quartus, records, render


def _load_records(paths):
    out = []
    for p in paths:
        paths_ = sorted(glob.glob(os.path.join(p, "**", "*.json"), recursive=True)) if os.path.isdir(p) else [p]
        for f in paths_:
            data = files.load_json(f)
            if isinstance(data, dict) and "records" in data:
                data = data["records"]
            items = data if isinstance(data, list) else [data]
            # only seed records; a stray meta.json in an input dir is not one
            out.extend(r for r in items if isinstance(r, dict) and "seed" in r and "variant" in r)
    return out


def _dump(obj, path):
    if path in (None, "-"):
        json.dump(obj, sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w") as fh:
            json.dump(obj, fh, indent=1, sort_keys=True)


def cmd_plan(a):
    seeds = plan.parse_seeds(a.seeds or f"1-{a.seed_count}")
    variants = [v for v in a.variants.split(",") if v]
    out = {"seeds": plan.format_seeds(seeds), "count": len(seeds),
           "matrix": json.dumps(plan.matrix(seeds, a.shards, variants), separators=(",", ":"))}
    if a.baseline_sha:
        out["cache_key"] = plan.cache_key(project=a.project, revision=a.revision, baseline_sha=a.baseline_sha,
                                          image=a.image, seeds=seeds, threads=a.threads, build_epoch=a.build_epoch)
    for k, v in out.items():
        print(f"{k}={v}")


def cmd_concurrency(a):
    try:
        mem_kb = next(int(l.split()[1]) for l in files.read("/proc/meminfo").splitlines() if l.startswith("MemAvailable:"))
    except (OSError, StopIteration):
        mem_kb = 16 * 1024 * 1024
    by_mem = int((mem_kb / 1048576 - a.reserve_gb) // a.peak_gb)
    by_cpu = (os.cpu_count() or 1) // max(1, a.threads)
    print(max(1, min(by_mem, by_cpu)))


def cmd_find_project(a):
    project = a.project or quartus.find_project(a.root)
    revision = a.revision or project
    for name in (project, revision):
        # these names reach workflow expressions and shell commands: allow only plain file-name characters
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            sys.exit(f"refusing Quartus project/revision name {name!r}")
    seed = quartus.read_seed(files.read(quartus.qsf_path(a.root, revision)))
    # shell-quoted: callers eval this, and file names come from (possibly untrusted) PR content
    for k, v in (("project", project), ("revision", revision), ("shipped_seed", seed)):
        print(f"{k}={shlex.quote(str(v))}")


def cmd_prepare(a):
    print(json.dumps(quartus.prepare(a.dir, a.revision, a.seed, a.threads, a.build_epoch)))


def cmd_collect(a):
    meta = json.loads(a.meta) if a.meta else {}
    rec = records.from_compile_dir(a.dir, a.revision, seed=a.seed, variant=a.variant, meta=meta)
    if rec["status"] != "ok" and a.log and os.path.isfile(a.log):
        rec["log_tail"] = files.read(a.log, errors="replace")[-4000:]
    _dump(rec, a.out)
    print(f"seed {a.seed} {a.variant}: {rec['status']}", file=sys.stderr)


def cmd_import_dse(a):
    _dump(records.from_dse_dir(a.dir, plan.parse_seeds(a.seeds), a.variant), a.out)


def cmd_aggregate(a):
    recs = _load_records(a.inputs)
    seeds = plan.parse_seeds(a.seeds)
    variants = [v for v in a.variants.split(",") if v]
    by = {}
    for r in recs:
        key = (r["variant"], r["seed"])
        if key in by:
            sys.exit(f"duplicate record for {key}")
        by[key] = r
    missing = [(v, s) for v in variants for s in seeds if (v, s) not in by]
    extra = sorted(k for k in by if k[0] not in variants or k[1] not in seeds)
    if missing and a.allow_partial:
        # hunt mode stops early by design: unrun seeds are recorded, not compiled
        print(f"{len(missing)} planned seeds were not run (hunt stopped early)", file=sys.stderr)
    elif missing:
        # never compare 27 seeds against 30 silently
        sys.exit("missing seed results: " + ", ".join(f"{v}:{s}" for v, s in missing))
    if extra:
        sys.exit("results not in the plan: " + ", ".join(f"{v}:{s}" for v, s in extra))
    meta = files.load_json(a.meta) if a.meta else {}
    # defaults so a local run needs no meta.json
    meta.setdefault("project", a.project or "core")
    meta.setdefault("revision", meta["project"])
    for v in variants:
        sha = next((by[(v, s)].get("sha", "") for s in seeds if (v, s) in by), "")
        meta.setdefault(v, {})
        meta[v].setdefault("label", {"candidate": "this branch"}.get(v, v))
        meta[v].setdefault("sha", sha)
        meta[v].setdefault("short", sha[:7] if sha else "?")
    ordered = [by[(v, s)] for v in variants for s in seeds if (v, s) in by]
    if not ordered:
        sys.exit("no results at all")
    meta["not_run"] = {v: [s for (vv, s) in missing if vv == v] for v in variants}
    versions = sorted({r.get("quartus_version") for r in ordered if r.get("quartus_version")})
    if versions:
        meta["quartus_version"] = "; ".join(versions)
        meta["quartus_version_short"] = versions[0].split(" Build")[0].replace("Version ", "")
    _dump({"meta": meta, "records": ordered}, a.out)
    print(f"{len(ordered)} records, {sum(r.get('status') != 'ok' for r in ordered)} failed", file=sys.stderr)


def _compare(a):
    merged = files.load_json(a.merged)
    th = compare.parse_thresholds(files.read(a.thresholds)) if a.thresholds and os.path.isfile(a.thresholds) else {}
    res = compare.compare(merged, th, a.seed_policy)
    res["_records"] = merged["records"]
    return merged, res


def cmd_compare(a):
    _, res = _compare(a)
    res.pop("_records")
    _dump(res, a.out)


def cmd_render(a):
    merged, res = _compare(a)
    d = a.out_dir
    os.makedirs(d, exist_ok=True)
    recs = merged["records"]
    def w(name, text):
        files.write(os.path.join(d, name), text)
    w("seeds.csv", render.seeds_csv(recs))
    w("per-clock.csv", render.per_clock_csv(recs))
    w("paths.csv", render.paths_csv(recs))
    w("comment.md", render.comment(res, a.run_url))
    w("summary.md", render.summary(res, a.run_url))
    _dump(merged, os.path.join(d, "merged.json"))
    out = {k: v for k, v in res.items() if k != "_records"}
    _dump(out, os.path.join(d, "compare.json"))
    _dump(dict(res["seed"], revision=merged["meta"].get("revision"),
               candidate_sha=merged["meta"].get("candidate", {}).get("sha")), os.path.join(d, "best-seed.json"))
    print(f"verdict={res['verdict']}")
    print(f"best_seed={res['seed'].get('best') or ''}")
    print(f"best_met={'true' if res['seed'].get('best_met') else 'false'}")
    print(f"apply_seed={'true' if res['seed'].get('apply') else 'false'}")
    print(f"thresholds_failed={'true' if res['thresholds']['failures'] else 'false'}")


def cmd_decide(a):
    from seedy import seedpick
    d = seedpick.apply_policy(files.load_json(a.best_seed), a.policy)
    if a.out:
        _dump(d, a.out)
    print(f"apply={'true' if d.get('apply') else 'false'}")
    print(f"best_seed={d.get('best') or ''}")
    print(f"reason={d.get('reason', '')}")


def cmd_render_single(a):
    """One variant only: hunt mode, or a baseline-only run (push to master / baseline == candidate)."""
    from seedy import seedpick
    merged = files.load_json(a.merged)
    d = a.out_dir
    os.makedirs(d, exist_ok=True)
    recs, meta = merged["records"], merged["meta"]
    variant = recs[0]["variant"]
    decision = seedpick.decide([r for r in recs if r["variant"] == variant],
                               meta.get("shipped_seed", {}).get(variant, 1), a.seed_policy)
    status_lines = []
    for p in glob.glob(os.path.join(a.status_dir, "**", "shard-status-*.txt"), recursive=True) if a.status_dir else []:
        status_lines += files.read(p).splitlines()
    def w(name, text):
        files.write(os.path.join(d, name), text)
    w("seeds.csv", render.seeds_csv(recs))
    w("per-clock.csv", render.per_clock_csv(recs))
    w("paths.csv", render.paths_csv(recs))
    body = render.single(merged, decision, a.run_url, status_lines)
    w("comment.md", body)
    w("summary.md", body.replace(render.marker(meta["project"]) + "\n", ""))
    _dump(merged, os.path.join(d, "merged.json"))
    _dump(dict(decision, revision=meta.get("revision"), candidate_sha=meta.get(variant, {}).get("sha")),
          os.path.join(d, "best-seed.json"))
    met = sum(bool(r.get("headline", {}).get("timing_met")) for r in recs if r.get("status") == "ok")
    print(f"verdict={met} of {len(recs)} seeds meet timing")
    print(f"best_seed={decision.get('best') or ''}")
    print(f"best_met={'true' if decision.get('best_met') else 'false'}")
    print(f"apply_seed={'true' if decision.get('apply') else 'false'}")
    print("thresholds_failed=false")


def cmd_apply_seed(a):
    text = files.read(a.qsf)
    old = quartus.read_seed(text)
    new = quartus.set_seed(text, a.seed)
    if new != text:
        files.write(a.qsf, new)
    print(f"old_seed={old}\nnew_seed={a.seed}\nchanged={'true' if new != text else 'false'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="seedy", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="normalise seeds, build the shard matrix and the baseline cache key")
    p.add_argument("--seeds", default="", help="explicit list, e.g. 1-8,13 (overrides --seed-count)")
    p.add_argument("--seed-count", type=int, default=30, help="use seeds 1..N")
    p.add_argument("--shards", type=int, default=10)
    p.add_argument("--variants", default="baseline,candidate")
    p.add_argument("--project", default="")
    p.add_argument("--revision", default="")
    p.add_argument("--baseline-sha", default="")
    p.add_argument("--image", default="")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--build-epoch", type=int, default=0)
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("concurrency", help="compiles that fit on this machine")
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--peak-gb", type=float, default=7.0)
    p.add_argument("--reserve-gb", type=float, default=2.0)
    p.set_defaults(fn=cmd_concurrency)

    p = sub.add_parser("find-project", help="project, revision and the .qsf's SEED of a source tree")
    p.add_argument("root")
    p.add_argument("--project", default="")
    p.add_argument("--revision", default="")
    p.set_defaults(fn=cmd_find_project)

    p = sub.add_parser("prepare", help="set SEED/threads and pin the build date in a work copy")
    p.add_argument("dir")
    p.add_argument("--revision", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--threads", type=int, default=4)
    p.add_argument("--build-epoch", type=int, required=True)
    p.set_defaults(fn=cmd_prepare)

    p = sub.add_parser("collect", help="parse one compiled work copy into a JSON record")
    p.add_argument("dir")
    p.add_argument("--revision", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--variant", required=True)
    p.add_argument("--meta", default="")
    p.add_argument("--log", default="")
    p.add_argument("--out", default="-")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("import-dse", help="records from one quartus_dse run's exported CSVs")
    p.add_argument("dir")
    p.add_argument("--seeds", required=True, help="that DSE invocation's --seeds list, in order")
    p.add_argument("--variant", required=True)
    p.add_argument("--out", default="-")
    p.set_defaults(fn=cmd_import_dse)

    p = sub.add_parser("aggregate", help="merge shard records; fail if any planned seed is missing")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--seeds", required=True)
    p.add_argument("--variants", default="baseline,candidate")
    p.add_argument("--meta", default="")
    p.add_argument("--allow-partial", action="store_true", help="hunt mode: unrun seeds are fine")
    p.add_argument("--project", default="", help="name shown in the report when no --meta is given")
    p.add_argument("--out", default="-")
    p.set_defaults(fn=cmd_aggregate)

    for name, fn, help_ in (("compare", cmd_compare, "statistics and verdict as JSON"),
                            ("render", cmd_render, "comment.md, summary.md, CSVs, best-seed.json")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("merged")
        p.add_argument("--thresholds", default="")
        p.add_argument("--seed-policy", default="never", choices=["never", "off", "if-failing", "always"])
        p.add_argument("--run-url", default="")
        if name == "compare":
            p.add_argument("--out", default="-")
        else:
            p.add_argument("--out-dir", required=True)
        p.set_defaults(fn=fn)

    p = sub.add_parser("render-single", help="report for one variant (hunt or baseline-only runs)")
    p.add_argument("merged")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--seed-policy", default="never", choices=["never", "off", "if-failing", "always"])
    p.add_argument("--run-url", default="")
    p.add_argument("--status-dir", default="", help="where shard-status-*.txt files are")
    p.set_defaults(fn=cmd_render_single)

    p = sub.add_parser("decide", help="re-apply an override_seed policy to best-seed.json")
    p.add_argument("best_seed")
    p.add_argument("--policy", required=True, choices=["never", "off", "if-failing", "always"])
    p.add_argument("--out", default="")
    p.set_defaults(fn=cmd_decide)

    p = sub.add_parser("apply-seed", help="rewrite the SEED assignment of a .qsf")
    p.add_argument("qsf")
    p.add_argument("--seed", type=int, required=True)
    p.set_defaults(fn=cmd_apply_seed)

    a = ap.parse_args(argv)
    return a.fn(a) or 0
