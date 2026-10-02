"""Baseline vs candidate: distributions, tests, per-clock and path signals, verdict, thresholds."""
import re
import statistics

from seedy import seedpick, stats

# key, label, unit, which direction is better
METRICS = [
    ("qof", "Quality of Fit", "", "higher"),
    ("fmax_geomean", "f(MAX) geomean", "MHz", "higher"),
    ("setup", "WC slack: setup", "ns", "higher"),
    ("hold", "WC slack: hold", "ns", "higher"),
    ("recovery", "WC slack: recovery", "ns", "higher"),
    ("removal", "WC slack: removal", "ns", "higher"),
    ("alms", "Logic utilization", "ALMs", "lower"),
    ("compile_s", "Compilation time", "s", "lower"),
]
ALPHA = 0.05
SLACK_KEYS = ("setup", "hold", "recovery", "removal")
# A slack shift only matters for closure if some seed gets near zero; recovery dropping from
# +3.8 to +3.6 ns is a real shift but not a timing risk. Override with the slack_margin_ns threshold.
SLACK_MARGIN_NS = 0.5


def short_clock(name):
    """Full Quartus clock name -> short label for tables (data keeps the full name)."""
    m = re.search(r"counter\[(\d+)\]", name)
    if m:
        return f"{name.split('|')[0]} c{m.group(1)}"
    if "general[" in name or name.startswith("pll_"):
        return name.split("|")[0]
    return name.split("|")[-1]


def ok(records, variant):
    return [r for r in records if r["variant"] == variant and r.get("status") == "ok"]


def per_clock_worst(rec, kind):
    out = {}
    for c in rec.get("clocks", []):
        if c["kind"] == kind and c["slack"] is not None:
            out[c["clock"]] = min(c["slack"], out.get(c["clock"], c["slack"]))
    return out


def clock_table(base, cand, kind):
    names = sorted({n for r in base + cand for n in per_clock_worst(r, kind)}, key=short_clock)
    rows = []
    for n in names:
        b = [per_clock_worst(r, kind).get(n) for r in base]
        c = [per_clock_worst(r, kind).get(n) for r in cand]
        b = [v for v in b if v is not None]
        c = [v for v in c if v is not None]
        bf, cf = sum(v < 0 for v in b), sum(v < 0 for v in c)
        rows.append({"clock": n, "short": short_clock(n), "kind": kind,
                     "base_fail": bf, "cand_fail": cf, "base_n": len(b), "cand_n": len(c),
                     "base_min": min(b) if b else None, "cand_min": min(c) if c else None,
                     "base_median": statistics.median(b) if b else None,
                     "cand_median": statistics.median(c) if c else None,
                     "new_failing": bf == 0 and cf > 0,
                     "p": stats.fisher_exact(cf, len(c) - cf, bf, len(b) - bf) if b and c else None})
    return rows


def endpoint_seeds(recs):
    """failing endpoint family -> number of seeds on which it fails."""
    out = {}
    for r in recs:
        for fam in r.get("derived", {}).get("failing_endpoints", {}):
            out[fam] = out.get(fam, 0) + 1
    return out


def watched_summary(recs):
    ws = [r.get("derived", {}) for r in recs]
    have = [r for r in recs if r.get("watch") or r.get("nowatch")]
    if not have:
        return None

    def worst(k):
        v = [w.get(k) for w in ws if w.get(k) is not None]
        return min(v) if v else None
    return {"min_setup": worst("watched_min_setup"), "min_hold": worst("watched_min_hold"),
            "on_failing_seeds": sorted(r["seed"] for r in recs if r.get("derived", {}).get("watched_on_failing")),
            "unmatched": sorted({g for w in ws for g in w.get("watched_unmatched", [])}),
            "seeds_with_data": len(have)}


def compare(merged, thresholds=None, seed_policy="off"):
    meta, records = merged["meta"], merged["records"]
    margin = (thresholds or {}).get("slack_margin_ns", SLACK_MARGIN_NS)
    base, cand = ok(records, "baseline"), ok(records, "candidate")
    res = {"meta": meta, "metrics": [], "reasons": []}
    for key, label, unit, better in METRICS:
        x = [r["headline"].get(key) for r in base]
        y = [r["headline"].get(key) for r in cand]
        if all(v is None for v in x + y):
            continue
        diff, p = stats.permutation_test(x, y)
        md, lo, hi = stats.bootstrap_median_diff(x, y)
        worse = diff is not None and ((diff < 0) if better == "higher" else (diff > 0))
        m = {"key": key, "label": label, "unit": unit, "better": better,
             "base": stats.describe(x), "cand": stats.describe(y),
             "diff_mean": diff, "p": p, "diff_median": md, "ci": [lo, hi], "worse": worse,
             "flag": bool(worse and p is not None and p < ALPHA and key not in ("compile_s", "qof"))}
        if m["flag"] and key in SLACK_KEYS and m["cand"]["min"] is not None and m["cand"]["min"] >= margin:
            m["flag"] = False
            m["note"] = f"significant shift, but every seed keeps >= {margin:g} ns of {key} slack"
        res["metrics"].append(m)
        if m["flag"]:
            res["reasons"].append(f"{label} worse by {abs(diff):.3f} {unit} on average (p = {p:.3f})".replace("  ", " "))

    bm = sorted(r["seed"] for r in base if r["headline"].get("timing_met"))
    cm = sorted(r["seed"] for r in cand if r["headline"].get("timing_met"))
    pm = stats.fisher_exact(len(cm), len(cand) - len(cm), len(bm), len(base) - len(bm)) if base and cand else None
    res["met"] = {"base": bm, "cand": cm, "base_n": len(base), "cand_n": len(cand), "p": pm}
    if pm is not None and pm < ALPHA and len(cm) / max(1, len(cand)) < len(bm) / max(1, len(base)):
        res["reasons"].append(f"fewer seeds meet timing ({len(cm)}/{len(cand)} vs {len(bm)}/{len(base)}, Fisher p = {pm:.3f})")

    res["clocks_setup"] = clock_table(base, cand, "setup")
    res["clocks_hold"] = clock_table(base, cand, "hold")
    for row in res["clocks_setup"] + res["clocks_hold"]:
        if row["new_failing"]:
            res["reasons"].append(f"new failing clock domain: {row['short']} {row['kind']} "
                                  f"fails on {row['cand_fail']} seeds (0 in baseline)")

    be, ce = endpoint_seeds(base), endpoint_seeds(cand)
    paths_known = any(r.get("paths") for r in base) and any(r.get("paths") for r in cand)
    res["endpoints"] = {"known": paths_known, "base": be, "cand": ce,
                        "cand_only": {k: v for k, v in ce.items() if k not in be}}
    if paths_known:
        for fam, n in sorted(res["endpoints"]["cand_only"].items(), key=lambda kv: -kv[1]):
            res["reasons"].append(f"new failing endpoint family {fam} ({n} seeds)")

    res["watched"] = watched_summary(cand)
    if res["watched"]:
        if res["watched"]["on_failing_seeds"]:
            res["reasons"].append("a watched register is on a failing path (seeds "
                                  + ", ".join(map(str, res["watched"]["on_failing_seeds"])) + ")")
        if res["watched"]["unmatched"]:
            res["reasons"].append("watch glob matched no registers: " + ", ".join(res["watched"]["unmatched"]))

    shipped = meta.get("shipped_seed", {})
    res["shipped"] = {v: next((r for r in records if r["variant"] == v and r["seed"] == shipped.get(v)), None)
                      for v in ("baseline", "candidate")}
    res["seed"] = seedpick.decide(cand, shipped.get("candidate", 1), seed_policy)
    res["missing"] = sorted({(r["variant"], r["seed"]) for r in records if r.get("status") != "ok"})

    res["verdict"] = ("Possible regression" if res["reasons"] else "No measurable regression")
    res["thresholds"] = check_thresholds(res, thresholds or {})
    return res


# ---------------------------------------------------------------- optional gating
def parse_thresholds(text):
    """Flat 'key: value' YAML subset (no PyYAML on the runner)."""
    out = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        v = v.strip().lower()
        out[k.strip()] = True if v in ("true", "yes", "on") else False if v in ("false", "no", "off") else float(v)
    return out


KNOWN_THRESHOLDS = {"slack_margin_ns", "max_median_setup_drop_ns", "max_median_hold_drop_ns", "max_met_rate_drop",
                    "max_alm_increase", "forbid_watched_on_failing", "forbid_new_failing_clock",
                    "forbid_regression_verdict"}


def check_thresholds(res, th):
    fails = []
    unknown = sorted(set(th) - KNOWN_THRESHOLDS)
    if unknown:
        fails.append("unknown threshold keys: " + ", ".join(unknown))
    m = {x["key"]: x for x in res["metrics"]}

    def drop(key):
        x = m.get(key)
        if not x or x["base"]["median"] is None or x["cand"]["median"] is None:
            return None
        return x["base"]["median"] - x["cand"]["median"]
    for key, name in (("setup", "max_median_setup_drop_ns"), ("hold", "max_median_hold_drop_ns")):
        d = drop(key)
        if name in th and d is not None and d > th[name]:
            fails.append(f"median {key} slack dropped {d:.3f} ns > {th[name]}")
    if "max_met_rate_drop" in th:
        met = res["met"]
        d = len(met["base"]) / max(1, met["base_n"]) - len(met["cand"]) / max(1, met["cand_n"])
        if d > th["max_met_rate_drop"]:
            fails.append(f"timing-met rate dropped {d:.2f} > {th['max_met_rate_drop']}")
    if "max_alm_increase" in th and "alms" in m and m["alms"]["diff_mean"] is not None:
        if m["alms"]["diff_mean"] > th["max_alm_increase"]:
            fails.append(f"mean ALMs rose {m['alms']['diff_mean']:.0f} > {th['max_alm_increase']:.0f}")
    if th.get("forbid_watched_on_failing") and res["watched"] and res["watched"]["on_failing_seeds"]:
        fails.append("watched register on a failing path")
    if th.get("forbid_new_failing_clock") and any(r["new_failing"] for r in res["clocks_setup"] + res["clocks_hold"]):
        fails.append("new failing clock domain")
    if th.get("forbid_regression_verdict") and res["reasons"]:
        fails.append("verdict is 'Possible regression'")
    return {"set": bool(th), "failures": fails}
