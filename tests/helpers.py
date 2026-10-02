import os
import shutil
import tempfile

from seedy import parse, records

FX = os.path.join(os.path.dirname(__file__), "fixtures", "snes-2026-10-02")
DSE_RUNS = [("dse-up", "1-16", "baseline"), ("dse-up-b", "17-30", "baseline"),
            ("dse-ir-a", "1-15", "candidate"), ("dse-ir-b", "16-30", "candidate")]
META = {"project": "SNES", "revision": "SNES",
        "baseline": {"label": "master", "short": "c61bfd4", "sha": "c61bfd4"},
        "candidate": {"label": "this PR", "short": "75f10d3", "sha": "75f10d3"},
        "shipped_seed": {"baseline": 1, "candidate": 1}, "quartus_version_short": "17.0.2 Lite"}


def dse_records():
    from seedy.plan import parse_seeds
    out = []
    for d, seeds, variant in DSE_RUNS:
        out += records.from_dse_dir(os.path.join(FX, d), parse_seeds(seeds), variant)
    return sorted(out, key=lambda r: (r["variant"] != "baseline", r["seed"]))


def merged():
    return {"meta": dict(META), "records": dse_records()}


def compile_dir_ir():
    """Lay the full-ir seed-1 reports out like a finished work copy."""
    t = tempfile.mkdtemp()
    os.makedirs(os.path.join(t, "output_files"))
    for f in ("fit.summary", "sta.summary", "flow.rpt"):
        shutil.copy(os.path.join(FX, "full-ir", "SNES." + f), os.path.join(t, "output_files", "SNES." + f))
    shutil.copy(os.path.join(FX, "full-ir", "sta.tsv"), os.path.join(t, "sta.tsv"))
    return t


def legacy(variant):
    r = {"paths": [], "watch": [], "nowatch": []}
    r.update(parse.legacy_paths(open(os.path.join(FX, f"full-{variant}", "full-timing.txt")).read()))
    return r
