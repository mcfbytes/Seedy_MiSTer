"""Baseline vs candidate: distributions, tests, per-clock and path signals, verdict, thresholds."""
import re
import statistics

from seedy import seedpick, stats
from seedy.records import short_node

# key, label, unit, which direction is better
METRICS = [
    ("qof", "Quality of Fit", "", "higher"),
    ("fmax_geomean", "f(MAX) geomean", "MHz", "higher"),
    ("setup", "WC slack: setup", "ns", "higher"),
    ("hold", "WC slack: hold", "ns", "higher"),
    ("recovery", "WC slack: recovery", "ns", "higher"),
    ("removal", "WC slack: removal", "ns", "higher"),
    ("tns", "Total negative setup slack", "ns", "higher"),
    ("alms", "Logic utilization", "ALMs", "lower"),
    ("compile_s", "Compilation time", "s", "lower"),
]
ALPHA = 0.05
SLACK_KEYS = ("setup", "hold", "recovery", "removal")
# A slack shift only matters for closure if some seed gets near zero; recovery dropping from
# +3.8 to +3.6 ns is a real shift but not a timing risk. Override with the slack_margin_ns threshold.
# Reviewers never discuss recovery/removal (async reset timing) unless it actually fails, so those
# two flag only when some seed goes negative.
SLACK_MARGIN_NS = 0.5
RESET_KEYS = ("recovery", "removal")


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


def threads_setting(recs):
    """NUM_PARALLEL_PROCESSORS the records were compiled with, e.g. ["ALL"] or ["4 (override)"]; [] for records
    from before Seedy recorded it."""
    return sorted({str(r["threads"]) + (" (override)" if r.get("threads_override") else "")
                   for r in recs if r.get("threads")})


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
        km = 0.0 if key in RESET_KEYS else margin
        if m["flag"] and key in SLACK_KEYS and m["cand"]["min"] is not None and m["cand"]["min"] >= km:
            m["flag"] = False
            m["note"] = (f"significant shift, but every seed keeps >= {km:g} ns of {key} slack" if km
                         else f"significant shift, but no seed fails {key}")
        res["metrics"].append(m)
        if m["flag"]:
            why = f"{label} worse by {abs(diff):.3f} {unit} on average (p = {p:.3f})".replace("  ", " ")
            if key in SLACK_KEYS and m["cand"]["min"] is not None:
                why += f"; worst seed {m['cand']['min']:+.3f} ns".replace("-", "−")
            res["reasons"].append(why)

    bm = sorted(r["seed"] for r in base if r["headline"].get("timing_met"))
    cm = sorted(r["seed"] for r in cand if r["headline"].get("timing_met"))
    pm = stats.fisher_exact(len(cm), len(cand) - len(cm), len(bm), len(base) - len(bm)) if base and cand else None
    res["met"] = {"base": bm, "cand": cm, "base_n": len(base), "cand_n": len(cand), "p": pm}
    if pm is not None and pm < ALPHA and len(cm) / max(1, len(cand)) < len(bm) / max(1, len(base)):
        res["reasons"].append(f"fewer seeds meet timing ({len(cm)}/{len(cand)} vs {len(bm)}/{len(base)}, Fisher p = {pm:.3f})")

    def neg_hold(recs):
        return sum(r["headline"].get("hold") is not None and r["headline"]["hold"] < 0 for r in recs)
    nb, nc = neg_hold(base), neg_hold(cand)
    ph = stats.fisher_exact(nc, len(cand) - nc, nb, len(base) - nb) if base and cand else None
    res["hold_neg"] = {"base": nb, "cand": nc, "p": ph}
    if ph is not None and ph < ALPHA and nc / max(1, len(cand)) > nb / max(1, len(base)):
        res["reasons"].append(f"more seeds with a hold violation ({nc}/{len(cand)} vs {nb}/{len(base)}, Fisher p = {ph:.3f})")

    # hold failures at corners the core's own report leaves out (Template.qsf: multicorner off)
    def hidden(recs):
        return sorted(r["seed"] for r in recs if r.get("headline_all") and
                      (r["headline_all"].get("hold") or 0) < 0 <= (r["headline"].get("hold") or 0))
    res["hidden_hold"] = {"base": hidden(base), "cand": hidden(cand),
                          "corners": sorted({c for r in base + cand for c in r.get("reported_corners") or []})}

    res["clocks_setup"] = clock_table(base, cand, "setup")
    res["clocks_hold"] = clock_table(base, cand, "hold")
    for row in res["clocks_setup"] + res["clocks_hold"]:
        if row["new_failing"]:
            res["reasons"].append(f"new failing clock domain: {row['short']} {row['kind']} "
                                  f"fails on {row['cand_fail']} seeds (0 in baseline)")

    be, ce = endpoint_seeds(base), endpoint_seeds(cand)
    paths_known = any(r.get("paths") for r in base) and any(r.get("paths") for r in cand)
    cand_only = {k: v for k, v in ce.items() if k not in be}
    # an endpoint failing on 1-2 of 30 seeds is placement noise (any seed can fail anywhere near the
    # critical paths); only a new failure that recurs often enough to be significant is a flag
    recurring = {k: v for k, v in cand_only.items()
                 if stats.fisher_exact(v, len(cand) - v, 0, len(base)) < ALPHA}
    res["endpoints"] = {"known": paths_known, "base": be, "cand": ce,
                        "cand_only": cand_only, "cand_only_recurring": recurring}
    if paths_known and recurring:
        res["reasons"].append("new failing endpoints: " + ", ".join(
            f"`{short_node(k, 3)}` ({v}/{len(cand)} seeds)" for k, v in sorted(recurring.items(), key=lambda kv: (-kv[1], kv[0]))))

    res["threads"] = {"base": threads_setting(base), "cand": threads_setting(cand)}
    res["constraints"] = constraint_diff(base, cand)
    res["review"] = review_flags(meta, base, cand) + constraint_flags(res["constraints"])

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


def review_flags(meta, base, cand):
    """Changes MiSTer maintainers object to on sight, whatever the statistics say: a new clock (it can
    hide real problems by making paths asynchronous), edits to the shared sys/ framework, constraint
    (.sdc) and project (.qsf) edits, and a changed fitter SEED or NUM_PARALLEL_PROCESSORS."""
    out = []
    bc = {c["clock"] for r in base for c in r.get("clocks", [])}
    cc = {c["clock"] for r in cand for c in r.get("clocks", [])}
    if bc and cc:
        new, gone = sorted(cc - bc, key=short_clock), sorted(bc - cc, key=short_clock)
        if new:
            out.append("adds clock(s) " + ", ".join(f"`{short_clock(c)}`" for c in new)
                       + ": a new clock makes its paths asynchronous to the rest, which can improve slack by hiding real problems")
        if gone:
            out.append("removes clock(s) " + ", ".join(f"`{short_clock(c)}`" for c in gone))
    seeds = meta.get("shipped_seed") or {}
    if seeds.get("baseline") is not None and seeds.get("candidate") is not None and seeds["baseline"] != seeds["candidate"]:
        out.append(f"changes the `.qsf` SEED ({seeds['baseline']} → {seeds['candidate']}); maintainers pick the release seed themselves")
    bt, ct = threads_setting(base), threads_setting(cand)
    if bt and ct and bt != ct:
        out.append(f"changes the `.qsf` NUM_PARALLEL_PROCESSORS ({', '.join(bt)} → {', '.join(ct)}); "
                   "like a new SEED, that alone gives every seed a different fit")
    paths = meta.get("changed_paths") or []
    groups = (("edits the shared `sys/` framework", lambda p: p.startswith("sys/")),
              ("edits timing constraints (`.sdc`)", lambda p: p.lower().endswith(".sdc")),
              ("edits the project settings (`.qsf`)", lambda p: p.lower().endswith(".qsf")))
    for text, match in groups:
        hit = [p for p in paths if match(p)]
        if hit:
            shown = ", ".join(f"`{p}`" for p in hit[:5]) + (f" and {len(hit) - 5} more" if len(hit) > 5 else "")
            out.append(f"{text}: {shown}")
    return out


def constraint_summary(recs):
    """Union over seeds (synthesis, and so the constraint picture, barely depends on the fitter seed)."""
    cs = [r["constraints"] for r in recs if r.get("constraints")]
    if not cs:
        return None
    def union(k):
        return sorted({x for c in cs for x in c.get(k, [])})
    def most(k):
        v = [c["unconstrained"].get(k) for c in cs if c.get("unconstrained", {}).get(k) is not None]
        return max(v) if v else None
    bad_sdc = sorted({f"{f} ({st})" for c in cs for f, st in c.get("sdc_files", {}).items() if st.upper() != "OK"})
    return {"clocks": union("unconstrained_clocks"), "ignored": union("ignored"), "ports": union("unconstrained_ports"),
            "latch_loops": max(c.get("latch_loops", 0) for c in cs), "bad_sdc": bad_sdc,
            "input_paths": most("input_paths"), "output_paths": most("output_paths")}


def constraint_diff(base, cand):
    b, c = constraint_summary(base), constraint_summary(cand)
    out = {"known": bool(b and c), "base": b, "cand": c}
    if out["known"]:
        for k in ("clocks", "ignored", "ports", "bad_sdc"):
            out["new_" + k] = [x for x in c[k] if x not in b[k]]
            out["fixed_" + k] = [x for x in b[k] if x not in c[k]]
    return out


def _few(items, n=4, fmt="`{}`"):
    return ", ".join(fmt.format(x) for x in items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def constraint_flags(cd):
    """What the timing numbers silently stop covering: the failure mode behind Template_MiSTer #80
    (constraints that match nothing after a rename), SNES #471 (a latch inferred as a clock) and
    MacLC #5 (SDRAM pins without I/O constraints)."""
    if not cd.get("known"):
        return []
    out = []
    if cd["new_ignored"]:
        out.append(f"has {len(cd['new_ignored'])} timing constraint(s) that now match nothing, so Quartus skips "
                   f"them and those paths are not timed as the author intended: " + _few(cd["new_ignored"], 3))
    if cd["new_clocks"]:
        out.append("makes Quartus treat " + _few([short_node(x, 3) for x in cd["new_clocks"]]) +
                   " as a clock with no constraint (usually a latch or a logic-generated clock), so its paths are not timed at all")
    if cd["cand"]["latch_loops"] > cd["base"]["latch_loops"]:
        out.append(f"adds combinational loops that Quartus times as latches "
                   f"({cd['base']['latch_loops']} → {cd['cand']['latch_loops']})")
    if cd["new_ports"]:
        out.append("leaves new I/O pins without timing constraints, so their timing is never checked: " + _few(cd["new_ports"]))
    if cd["new_bad_sdc"]:
        out.append("has an `.sdc` file Quartus could not read cleanly: " + _few(cd["new_bad_sdc"], fmt="{}"))
    return out


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
                    "forbid_regression_verdict", "forbid_untimed_changes"}


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
    if th.get("forbid_untimed_changes") and constraint_flags(res.get("constraints") or {}):
        fails.append("the PR leaves new paths untimed (constraint health)")
    if th.get("forbid_regression_verdict") and res["reasons"]:
        fails.append("verdict is 'Possible regression'")
    return {"set": bool(th), "failures": fails}
