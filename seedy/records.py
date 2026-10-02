"""One JSON record per (variant, seed): built from a compile directory or from DSE CSVs."""
import os
import re

from seedy import parse

HEADLINE = ("qof", "fmax_geomean", "setup", "hold", "recovery", "removal", "alms", "compile_s", "timing_met")


def _worst(clocks, kind):
    vals = [c["slack"] for c in clocks if c["kind"] == kind and c["slack"] is not None]
    return min(vals) if vals else None


def headline_from(clocks, fmax, util, flow):
    """The #462 columns. f(MAX) geomean = geomean over clocks of each clock's worst-corner
    restricted f(MAX); this reproduces DSE's 'f(MAX) Geomean' to the last digit (docs/METRICS.md)."""
    per_clock = {}
    for f in fmax:
        v = f["restricted"] if f["restricted"] is not None else f["fmax"]
        if v is not None:
            per_clock[f["clock"]] = min(v, per_clock.get(f["clock"], v))
    h = {
        "qof": None,
        "fmax_geomean": parse.geomean(per_clock.values()),
        "setup": _worst(clocks, "setup"),
        "hold": _worst(clocks, "hold"),
        "recovery": _worst(clocks, "recovery"),
        "removal": _worst(clocks, "removal"),
        "alms": util.get("alms"),
        "compile_s": flow.get("total_s"),
    }
    h["timing_met"] = timing_met(h)
    return h


def timing_met(h):
    """DSE's definition: every worst-case slack that exists is >= 0."""
    vals = [h.get(k) for k in ("setup", "hold", "recovery", "removal")]
    if h.get("setup") is None:
        return None
    return all(v >= 0 for v in vals if v is not None)


def from_compile_dir(d, revision, *, seed, variant, meta=None):
    """Parse a finished per-seed work directory (output_files/ + sta.tsv)."""
    out = os.path.join(d, "output_files")
    fit = parse.read_text(os.path.join(out, revision + ".fit.summary"))
    sta_sum = parse.read_text(os.path.join(out, revision + ".sta.summary"))
    flow = parse.read_text(os.path.join(out, revision + ".flow.rpt"))
    tsv = parse.read_text(os.path.join(d, "sta.tsv"))
    rec = {"seed": int(seed), "variant": variant, "source": "compile", **(meta or {})}
    rc = parse.read_text(os.path.join(d, "compile.rc"))
    if rc is not None and rc.strip() not in ("0", ""):
        rec["status"] = "compile_failed"
        rec["exit_code"] = rc.strip()
        return rec
    if fit is None or sta_sum is None:
        rec["status"] = "compile_failed"
        return rec
    util = parse.fit_summary(fit)
    flowd = parse.flow_rpt(flow) if flow else {"runtime_s": {}, "peak_mem_mb": {}, "total_s": None}
    if tsv:
        sta = parse.sta_tsv(tsv)
    else:  # STA script failed: fall back to the per-clock multicorner summary (no corners, no paths)
        sta = {"corners": [], "fmax": [], "paths": [], "watch": [], "nowatch": [],
               "clocks": [dict(c, corner="worst") for c in parse.sta_summary(sta_sum)
                          if c["kind"] in parse.KINDS]}
        rec["warnings"] = ["sta.tsv missing: per-corner data, f(MAX) and paths unavailable"]
    rec.update({
        "status": "ok",
        "quartus_version": util.pop("quartus_version"),
        "headline": headline_from(sta["clocks"], sta["fmax"], util, flowd),
        "utilization": util,
        "runtime_s": flowd["runtime_s"],
        "peak_mem_mb": flowd["peak_mem_mb"],
        **{k: sta[k] for k in ("corners", "clocks", "fmax", "paths", "watch", "nowatch")},
    })
    rec["derived"] = derive_paths(rec)
    return rec


# ---------------------------------------------------------------- path-derived fields
_IDX_RE = re.compile(r"\[\d+\]")
_DUP_RE = re.compile(r"~DUPLICATE(_\d+)?")


def endpoint_family(node):
    """Normalise a node name: drop bus indices and ~DUPLICATE suffixes."""
    return _DUP_RE.sub("", _IDX_RE.sub("", node))


def short_node(node, parts=2):
    """'emu:emu|main:main|...|P65C816:P65C816|P' -> 'P65C816|P' (instance names only)."""
    segs = [s.split(":")[-1] for s in node.split("|")]
    return "|".join(segs[-parts:])


def derive_paths(rec):
    failing = {}
    for p in rec.get("paths", []):
        if p["slack"] is not None and p["slack"] < 0:
            fam = endpoint_family(p["to"])
            failing[fam] = failing.get(fam, 0) + 1
    watch = rec.get("watch", [])

    def worst(kind):
        v = [w["slack"] for w in watch if w["kind"] == kind and w["slack"] is not None]
        return min(v) if v else None
    return {
        "failing_endpoints": failing,
        "watched_min_setup": worst("setup"),
        "watched_min_hold": worst("hold"),
        "watched_on_failing": any(w["slack"] is not None and w["slack"] < 0 for w in watch),
        "watched_unmatched": list(rec.get("nowatch", [])),
    }


# ---------------------------------------------------------------- DSE import
def from_dse_dir(d, seeds, variant, meta=None):
    """Records from one quartus_dse invocation's exported CSVs. `seeds` is that invocation's
    --seeds list in order: DSE names points by position, not by seed."""
    hdr, rows = parse.dse_csv(os.path.join(d, "exploration_summary.csv"))
    by_point = {}
    for r in rows:
        k = parse.dse_point_index(r[0])
        if k > len(seeds):
            raise ValueError(f"{d}: point {r[0]} beyond the {len(seeds)}-seed list")
        by_point[k] = {
            "qof": parse.num(r[1]), "fmax_geomean": parse.num(r[2]), "setup": parse.num(r[3]),
            "hold": parse.num(r[4]), "recovery": parse.num(r[5]), "removal": parse.num(r[6]),
            "alms": parse.num(r[7]), "compile_s": parse.hms(r[8]),
        }
    extra = {}
    for name in ("multicorner_wcslack", "fmax_summary", "utilization", "runtime"):
        p = os.path.join(d, name + ".csv")
        if os.path.isfile(p):
            h, rs = parse.dse_csv(p)
            for r in rs:
                extra.setdefault(parse.dse_point_index(r[0]), {})[name] = dict(zip(h[1:], r[1:]))
    out = []
    for k in sorted(by_point):
        h = by_point[k]
        h["timing_met"] = timing_met(h)
        x = extra.get(k, {})
        clocks = [{"corner": "worst", "kind": "setup", "clock": c, "slack": parse.num(v), "tns": None}
                  for c, v in x.get("multicorner_wcslack", {}).items() if c != "Worst-Case Slack"]
        fmax = [{"corner": "worst", "clock": c, "fmax": parse.num(v), "restricted": parse.num(v)}
                for c, v in x.get("fmax_summary", {}).items() if c != "f(MAX) Geomean"]
        util = {k2.lower().replace(" ", "_"): parse.num(v) for k2, v in x.get("utilization", {}).items()}
        runtime = {k2: parse.hms(v) for k2, v in x.get("runtime", {}).items()}
        rec = {"seed": seeds[k - 1], "variant": variant, "source": "dse", "status": "ok",
               "dse_point": k, **(meta or {}), "headline": h, "utilization": util,
               "runtime_s": runtime, "peak_mem_mb": {}, "corners": [], "clocks": clocks,
               "fmax": fmax, "paths": [], "watch": [], "nowatch": []}
        rec["derived"] = derive_paths(rec)
        out.append(rec)
    missing = sorted(set(range(1, len(seeds) + 1)) - set(by_point))
    for k in missing:
        out.append({"seed": seeds[k - 1], "variant": variant, "source": "dse", "status": "compile_failed",
                    "dse_point": k, **(meta or {})})
    return out
