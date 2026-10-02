"""Pick the 'best' seed of a variant: the one to ship or hand to hardware testers."""

KINDS = ("setup", "hold", "recovery", "removal")


def _worst_slack(h):
    vals = [h.get(k) for k in KINDS if h.get(k) is not None]
    return min(vals) if vals else float("-inf")


def _neg_tns(rec):
    """Total negative slack summed over clocks and corners (0 when everything passes)."""
    return sum(c["tns"] for c in rec.get("clocks", []) if c.get("tns") is not None and c["tns"] < 0)


def rank_key(rec):
    """Higher sorts first: meets timing, then the worst of the four WC slacks (the binding margin),
    then least total negative slack, then setup slack, then f(MAX) geomean, then the lower seed."""
    h = rec["headline"]
    return (bool(h.get("timing_met")), _worst_slack(h), _neg_tns(rec),
            h.get("setup") if h.get("setup") is not None else float("-inf"),
            h.get("fmax_geomean") or 0.0, -rec["seed"])


def rank(records):
    ok = [r for r in records if r.get("status") == "ok" and r.get("headline")]
    return sorted(ok, key=rank_key, reverse=True)


def why(rec):
    h = rec["headline"]
    met = "meets timing" if h.get("timing_met") else "does not meet timing"
    def f(v):
        return "–" if v is None else f"{v:+.3f}".replace("-", "−")
    return f"seed {rec['seed']} {met}; worst slack {f(_worst_slack(h))} ns (setup {f(h.get('setup'))}, hold {f(h.get('hold'))})"


def decide(records, shipped_seed, policy):
    """policy: never | if-failing | always ('off' is accepted for never). Returns the
    recommendation and whether to commit it."""
    ranked = rank(records)
    if not ranked:
        return {"best": None, "apply": False, "reason": "no seed compiled successfully"}
    best = ranked[0]
    shipped = next((r for r in ranked if r["seed"] == shipped_seed), None)
    shipped_met = bool(shipped and shipped["headline"].get("timing_met"))
    out = {"best": best["seed"], "best_met": bool(best["headline"].get("timing_met")),
           "best_why": why(best), "shipped": shipped_seed, "shipped_met": shipped_met,
           "top": [{"seed": r["seed"], "why": why(r)} for r in ranked[:5]], "apply": False}
    return apply_policy(out, policy)


def apply_policy(d, policy):
    """Decide whether to commit d['best'] given the .qsf's shipped seed. Also used to re-apply a
    trusted policy to a best-seed.json produced by an earlier, untrusted run."""
    out = dict(d)
    if out.get("best") is None:
        return dict(out, apply=False)
    if policy in ("never", "off", "", None):
        out.update(apply=False, reason="override_seed is 'never': suggestion only")
    elif not out.get("best_met"):
        out.update(apply=False, reason="no seed met timing, so the .qsf is left alone")
    elif out["best"] == out.get("shipped"):
        out.update(apply=False, reason=f"the .qsf already uses the best seed ({out['best']})")
    elif policy == "if-failing" and out.get("shipped_met"):
        out.update(apply=False, reason=f"the .qsf's seed {out.get('shipped')} already meets timing (policy if-failing)")
    else:
        out.update(apply=True, reason=f"SEED {out.get('shipped')} -> {out['best']}")
    return out
