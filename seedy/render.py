"""Markdown (PR comment, job summary) and CSV outputs."""
import csv
import io
import re

from seedy import seedpick
from seedy.compare import ALPHA, short_clock
from seedy.parse import fmt_hms
from seedy.records import short_node

COMMENT_LIMIT = 65536
SEEDS_CSV_COLS = ["seed", "variant", "Quality of Fit", "f(MAX) Geomean (MHz)", "WC Slack: Setup",
                  "WC Slack: Hold", "WC Slack: Recovery", "WC Slack: Removal", "Logic Utilization",
                  "Compilation Time", "Timing met"]


def marker(project):
    return f"<!-- seedy:{project} -->"


def f3(v, sign=True):
    if v is None:
        return "–"
    s = f"{v:+.3f}" if sign else f"{v:.3f}"
    return s.replace("-", "−")


def fint(v):
    return "–" if v is None else f"{v:,.0f}"


def fp(p):
    if p is None:
        return "–"
    return "< 0.001" if p < 0.001 else f"{p:.2f}" if p >= 0.01 else f"{p:.3f}"


def peq(p):
    """'p = 0.29' / 'p < 0.001'."""
    s = fp(p)
    return "p " + s if s.startswith("<") else "p = " + s


def fval(key, v, signed=False):
    if v is None:
        return "–"
    sign = ("+" if v >= 0 else "−") if signed else ("" if v >= 0 else "−")
    if key == "alms":
        return f"{sign}{abs(v):,.0f}"
    if key == "compile_s":
        return sign + fmt_hms(abs(v))
    if key in ("fmax_geomean", "qof"):
        return f"{sign}{abs(v):.2f}"
    return f3(v)


# ---------------------------------------------------------------- CSV
def seeds_csv(records, variant_names=None):
    """The #462 columns, one row per variant x seed (reproduces the hand-made sweep CSV)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(SEEDS_CSV_COLS)
    for r in records:
        name = (variant_names or {}).get(r["variant"], r["variant"])
        if r.get("status") != "ok":
            w.writerow([r["seed"], name] + ["compile_failed"] + [""] * 8)
            continue
        h = r["headline"]

        def g(k, fmt="{:.3f}"):
            return "" if h.get(k) is None else fmt.format(h[k])
        w.writerow([r["seed"], name, g("qof"), g("fmax_geomean"), g("setup"), g("hold"), g("recovery"),
                    g("removal"), g("alms", "{:.0f}"), fmt_hms(h.get("compile_s")),
                    "yes" if h.get("timing_met") else "no"])
    return buf.getvalue()


def per_clock_csv(records):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["variant", "seed", "corner", "kind", "clock", "slack_ns", "tns_ns"])
    for r in records:
        for c in r.get("clocks", []):
            w.writerow([r["variant"], r["seed"], c["corner"], c["kind"], c["clock"], c["slack"], c["tns"]])
    w.writerow([])
    w.writerow(["variant", "seed", "corner", "clock", "fmax_mhz", "restricted_fmax_mhz"])
    for r in records:
        for f in r.get("fmax", []):
            w.writerow([r["variant"], r["seed"], f["corner"], f["clock"], f["fmax"], f["restricted"]])
    return buf.getvalue()


def paths_csv(records):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["variant", "seed", "set", "glob", "dir", "corner", "kind", "slack_ns", "from", "to", "launch", "latch"])
    for r in records:
        for p in r.get("paths", []):
            w.writerow([r["variant"], r["seed"], "worst", "", "", p["corner"], p["kind"], p["slack"],
                        p["from"], p["to"], p["launch"], p["latch"]])
        for p in r.get("watch", []):
            w.writerow([r["variant"], r["seed"], "watch", p["glob"], p["dir"], p["corner"], p["kind"],
                        p["slack"], p["from"], p["to"], p["launch"], p["latch"]])
    return buf.getvalue()


# ---------------------------------------------------------------- Markdown
def _table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    # GFM splits cells on '|' even inside code spans (endpoint names are full of them); '\|' renders as '|'
    out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in row) + " |" for row in rows]
    return "\n".join(out)


def _details(summary, body):
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def _d(key, b, c):
    """Delta cell, PR minus baseline, in the metric's own format."""
    return "–" if b is None or c is None else fval(key, c - b, True)


def _dn(b, c):
    """Delta cell for counts."""
    d = c - b
    return "0" if d == 0 else f"{d:+d}".replace("-", "−")


def _alms_total(records):
    for r in records:
        u = r.get("utilization") or {}
        if u.get("alms_total"):
            return u["alms_total"]
        if str(u.get("device", "")).upper().startswith("5CSEBA6"):  # the DE10-Nano's Cyclone V
            return 41910
    return None


def _pct(v, total):
    return f" ({100 * v / total:.1f}%)" if v is not None and total else ""


def headline(res):
    """The rows MiSTer reviewers actually quote: seeds closing, worst setup slack, TNS, hold, logic."""
    meta = res["meta"]
    m = {x["key"]: x for x in res["metrics"]}
    met = res["met"]
    bl, cl = _name(meta["baseline"]), _name(meta["candidate"])
    rows = [["Seeds that close timing", f"{len(met['base'])}/{met['base_n']}", f"{len(met['cand'])}/{met['cand_n']}",
             _dn(len(met["base"]), len(met["cand"])), fp(met["p"])]]

    def pair(key, stat_a, stat_b):
        b, c = m[key]["base"], m[key]["cand"]
        return [f"{fval(key, b[stat_a])} / {fval(key, b[stat_b])}", f"{fval(key, c[stat_a])} / {fval(key, c[stat_b])}",
                f"{_d(key, b[stat_a], c[stat_a])} / {_d(key, b[stat_b], c[stat_b])}"]
    if "setup" in m:
        rows.append(["Worst setup slack (ns), average / typical seed"] + pair("setup", "mean", "median") + [fp(m["setup"]["p"])])
        b, c = m["setup"]["base"]["min"], m["setup"]["cand"]["min"]
        rows.append(["Worst setup slack (ns), unluckiest seed", f3(b), f3(c), _d("setup", b, c), ""])
    if "tns" in m:
        b, c = m["tns"]["base"]["mean"], m["tns"]["cand"]["mean"]
        rows.append(["Total negative slack (ns), average", f3(b), f3(c), _d("tns", b, c), fp(m["tns"]["p"])])
    hn = res.get("hold_neg")
    if hn:
        rows.append(["Seeds with a hold violation", f"{hn['base']}/{met['base_n']}", f"{hn['cand']}/{met['cand_n']}",
                     _dn(hn["base"], hn["cand"]), fp(hn["p"])])
    for key in ("recovery", "removal"):  # reset timing: shown only when it actually fails somewhere
        if key in m and min(v for v in (m[key]["base"]["min"], m[key]["cand"]["min"], 0) if v is not None) < 0:
            b, c = m[key]["base"]["min"], m[key]["cand"]["min"]
            rows.append([f"{key.capitalize()} slack (ns), unluckiest seed", f3(b), f3(c), _d(key, b, c), fp(m[key]["p"])])
    if "alms" in m:
        total = _alms_total(res["_records"])
        b, c = m["alms"]["base"]["mean"], m["alms"]["cand"]["mean"]
        rows.append(["Logic used (ALMs), average", fval("alms", b) + _pct(b, total), fval("alms", c) + _pct(c, total),
                     _d("alms", b, c), fp(m["alms"]["p"])])
    sb, sc = res["shipped"]["baseline"], res["shipped"]["candidate"]
    if sb or sc:
        def ok(r):
            return r and r.get("status") == "ok"

        def sh(r):
            if not r:
                return "not compiled"
            if not ok(r):
                return "compile failed"
            h = r["headline"]
            return f"{f3(h['setup'])} / {f3(h['hold'])}" + (" ✓" if h.get("timing_met") else " ✗")
        d = "–"
        if ok(sb) and ok(sc):
            hb, hc = sb["headline"], sc["headline"]
            d = f"{_d('setup', hb.get('setup'), hc.get('setup'))} / {_d('hold', hb.get('hold'), hc.get('hold'))}"
        seeds = meta.get("shipped_seed", {})
        label = f"The `.qsf`'s seed ({seeds.get('baseline')}" + \
            (f" / {seeds.get('candidate')}" if seeds.get("candidate") != seeds.get("baseline") else "") + "): setup / hold (ns)"
        rows.append([label, sh(sb), sh(sc), d, ""])
    return _table(["", bl, cl, "Δ", "p"], rows)


def failing_clocks(res):
    """Per-clock setup, only for clocks that fail on some seed: the table reviewers argue over."""
    rows = [r for r in res["clocks_setup"] if r["base_fail"] or r["cand_fail"]]
    if not rows:
        return "No clock fails setup on any seed of either side."
    return _table(["clock failing setup", "seeds (base)", "seeds (PR)", "Δ", "typical slack (base)", "typical slack (PR)",
                   "Δ", "unluckiest (base)", "unluckiest (PR)", "p"],
                  [[f"`{r['short']}`", f"{r['base_fail']}/{r['base_n']}", f"{r['cand_fail']}/{r['cand_n']}",
                    _dn(r["base_fail"], r["cand_fail"]), f3(r["base_median"]), f3(r["cand_median"]),
                    _d("setup", r["base_median"], r["cand_median"]), f3(r["base_min"]), f3(r["cand_min"]), fp(r["p"])]
                   for r in sorted(rows, key=lambda r: -(r["base_fail"] + r["cand_fail"]))])


def _corner_text(res):
    cs = res.get("hidden_hold", {}).get("corners") or []
    if len(cs) == 1:
        m = re.search(r"(slow|fast)_\d+mv_(-?\d+)c", cs[0], re.I)
        return f"the {m.group(1).lower()} {m.group(2)} °C corner" if m else cs[0]
    return "all timing corners" if cs else None


def plain_summary(res):
    """Two or three sentences a non-specialist can act on."""
    meta, met = res["meta"], res["met"]
    bl, cl = _name(meta["baseline"]), _name(meta["candidate"])
    b, c = len(met["base"]), len(met["cand"])
    out = [f"Timing closed on {c} of {met['cand_n']} seeds of {cl}, against {b} of {met['base_n']} on {bl}."]
    if met["p"] is not None and b != c:
        out.append("A difference that large is unlikely to be chance." if met["p"] < ALPHA else
                   f"With {met['base_n']} seeds a difference that size can be chance (p = {fp(met['p'])}).")
    grew = max(res.get("clocks_setup") or [], key=lambda r: r["cand_fail"] - r["base_fail"], default=None)
    if grew and grew["cand_fail"] - grew["base_fail"] >= 3:
        out.append(f"The clock that fails more often is `{grew['short']}` "
                   f"({grew['base_fail']} → {grew['cand_fail']} seeds, p = {fp(grew['p'])}).")
    sc = res["shipped"]["candidate"]
    seed = meta.get("shipped_seed", {}).get("candidate")
    if sc and sc.get("status") == "ok":
        h = sc["headline"]
        out.append(f"The seed in the `.qsf` ({seed}) " + ("closes timing on " + cl + "." if h.get("timing_met") else
                   f"does not close timing on {cl} (worst setup {f3(h.get('setup'))} ns, hold {f3(h.get('hold'))} ns)."))
    return " ".join(out)


GLOSSARY = """- **Slack** is how much time a signal has to spare, in nanoseconds, under Quartus's worst-case model of the chip. \
Positive means on time; negative means late *in the model*.
- **Setup** means a signal must arrive before the next clock tick. A small negative setup slack (tens to a few \
hundred ps) is common in released MiSTer cores and usually works, because the model assumes a 100 °C chip. The \
risk grows with heat and varies from chip to chip.
- **Hold** means a signal must stay steady just after the tick. A cooler chip or a slower clock does not fix a hold \
violation, so it is the more serious of the two.
- **Closes timing** (✓, "met") means every setup, hold, recovery and removal slack of that seed is ≥ 0. A seed that \
doesn't close still builds and usually runs; it just has no guaranteed margin. Maintainers rebuild with other seeds \
until a release build closes.
- **Seed** shuffles where the fitter places logic. Each seed is an independent random draw, so one build proves \
little; Seedy compiles many seeds of both sides and compares the two groups. A PR should not make the group worse.
- **Total negative slack** adds up the lateness of every failing path: 0 when a seed closes, more negative when more \
paths fail or fail by more.
- **Recovery / removal** are setup and hold for reset signals. They appear above only when some seed fails them.
- **Δ** is this PR minus the baseline. For slack, negative Δ means less margin. For ALMs, negative means smaller.
- **p** is the chance of seeing a difference this large if the PR changed nothing. Below 0.05 deserves a look; \
about ten numbers are tested, so an occasional p < 0.05 is expected by chance alone.
- **Timing constraints** (the `.sdc` files) tell Quartus each clock's speed and which paths to check. A path with \
no constraint, or under a constraint that matches nothing, is never checked, so good slack says nothing about it.
- **Corner** is the temperature and voltage case the model assumes. Seedy's headline uses the corners the core's \
own Quartus report uses (MiSTer's template reports only slow 100 °C); every corner is in the detail tables."""


def ranked_table(ranked, shipped=None, limit=15):
    rows = []
    for r in ranked[:limit]:
        h = r["headline"]
        neg = seedpick._neg_tns(r)
        rows.append([f"{r['seed']}" + (" (.qsf)" if r["seed"] == shipped else ""), "✓" if h.get("timing_met") else "",
                     f3(seedpick._worst_slack(h)), f3(h.get("setup")), f3(h.get("hold")), f3(h.get("recovery")),
                     f3(h.get("removal")), f3(neg) if r.get("clocks") and neg else "–",
                     fval("fmax_geomean", h.get("fmax_geomean")), fint(h.get("alms"))])
    return _table(["seed", "met", "worst", "setup", "hold", "recovery", "removal", "TNS sum", "f(MAX)", "ALMs"], rows)


def _best_line(tag, best, rec, why):
    if rec is None:
        return f"**{tag}: {best}**: {why}."
    h = rec["headline"]
    return (f"**{tag}: {best}** ({'meets' if h.get('timing_met') else 'does not meet'} timing; "
            f"worst slack {f3(seedpick._worst_slack(h))} ns).")


def _shipped_note(decision, ranked):
    """Put the recommendation in proportion when the .qsf's own seed already closes."""
    shipped, best = decision.get("shipped"), decision.get("best")
    if shipped is None or shipped == best:
        return "That is the `.qsf`'s current seed." if shipped == best else None
    rec = next((r for r in ranked if r["seed"] == shipped), None)
    if rec is None:
        return f"The `.qsf`'s seed {shipped} was not compiled in this run."
    h = rec["headline"]
    if not h.get("timing_met"):
        return f"The `.qsf`'s seed {shipped} does not meet timing (worst slack {f3(seedpick._worst_slack(h))} ns)."
    gap = seedpick._worst_slack(ranked[0]["headline"]) - seedpick._worst_slack(h)
    return (f"The `.qsf`'s seed {shipped} already meets timing (worst slack {f3(seedpick._worst_slack(h))} ns, "
            f"{gap:.3f} ns less than seed {best}).")


def seed_section(res):
    s = res["seed"]
    meta = res["meta"]
    if s.get("best") is None:
        return "**Seed:** no candidate seed compiled successfully."
    ranked = seedpick.rank([r for r in res["_records"] if r["variant"] == "candidate"])
    rec = next((r for r in ranked if r["seed"] == s["best"]), None)
    tag = "Recommended seed for hardware testing" if s["best_met"] else "Least-bad seed for hardware testing"
    bullets = []
    if meta.get("rbf_artifact"):
        bullets.append(f"Its `.rbf` is in the `{meta['rbf_artifact']}` artifact; that exact bitstream is what was measured.")
    note = _shipped_note(s, ranked)
    if note:
        bullets.append(note)
    if meta.get("seed_policy", "never") not in ("never", "off"):
        bullets.append(("Will be committed to the branch (if it hasn't moved since this run): " if s.get("apply")
                        else "Not committed: ") + s["reason"] + ".")
    out = [_best_line(tag, s["best"], rec, s.get("best_why")), ""] + [f"- {b}" for b in bullets]
    if len(ranked) > 1:
        out += ["", _details(f"Top {min(5, len(ranked))} seeds of {_name(meta['candidate'])}",
                             ranked_table(ranked, s.get("shipped"), 5))]
    return "\n".join(out)


_CONSTRAINT_ROWS = (("Clocks with no constraint (paths not timed)", lambda c: len(c["clocks"])),
                    ("Constraints that match nothing (ignored)", lambda c: len(c["ignored"])),
                    ("Combinational loops timed as latches", lambda c: c["latch_loops"]),
                    ("I/O pins with no timing constraint", lambda c: len(c["ports"])),
                    ("`.sdc` files not read cleanly", lambda c: len(c["bad_sdc"])))


def constraint_line(res):
    cd = res.get("constraints") or {}
    if not cd.get("known"):
        return None
    b, c = cd["base"], cd["cand"]
    worse = any(cd["new_" + k] for k in ("clocks", "ignored", "ports", "bad_sdc")) or c["latch_loops"] > b["latch_loops"]
    fixed = [x for k in ("clocks", "ignored", "ports", "bad_sdc") for x in cd["fixed_" + k]]
    have = ", ".join(f"{f(c)} {label.split(' (')[0].lower()}" for label, f in _CONSTRAINT_ROWS if f(c))
    if worse:
        return "Timing constraints: this PR leaves something new untimed (listed under *Needs a maintainer's eye*)."
    line = "Timing constraints: nothing new is left untimed."
    if fixed:
        line += f" This PR fixes {len(fixed)} existing gap(s)."
    if have:
        line += f" Both sides share: {have}; see *Constraint health*."
    return line


def constraint_section(res):
    cd = res["constraints"]
    b, c = cd["base"], cd["cand"]
    rows = [[label, f(b), f(c), _dn(f(b), f(c))] for label, f in _CONSTRAINT_ROWS]
    out = [_table(["", "baseline", "PR", "Δ"], rows)]
    for k, label in (("clocks", "Clocks with no constraint"), ("ignored", "Ignored constraints"),
                     ("ports", "Unconstrained I/O pins")):
        if c[k]:
            new = set(cd["new_" + k])
            items = [short_node(x, 3) if k == "clocks" else x for x in c[k]]
            shown = ", ".join(f"`{x}`" + (" 🆕" if raw in new else "") for x, raw in zip(items[:30], c[k][:30]))
            out.append(f"**{label} (PR):** {shown}" + (f" and {len(items) - 30} more" if len(items) > 30 else ""))
    out.append("These do not depend on the seed. A clock with no constraint or an ignored constraint means the "
               "slack numbers above never looked at those paths. MiSTer's framework leaves many HDMI/SD/LED pins "
               "unconstrained on purpose; what matters is what the PR adds.")
    return "\n\n".join(out)


def signals(res):
    out = []
    cl = constraint_line(res)
    if cl:
        out.append(cl)
    hh = res.get("hidden_hold") or {}
    if hh.get("base") or hh.get("cand"):
        out.append(f"Outside {_corner_text(res) or 'the reported corners'}, at the cold/fast corners Quartus also models "
                   f"but this core's report leaves out, hold fails on {_seeds(len(hh['base']))} of the baseline and "
                   f"{_seeds(len(hh['cand']))} of the PR. Real, but not what maintainers' own builds show.")
    w = res.get("watched")
    if w:
        names = res["meta"].get("watch_registers") or sorted({x["glob"] for r in res["_records"] for x in r.get("watch", [])})
        globs = " ".join(f"`{g}`" for g in names)
        if w["unmatched"]:
            out.append(f"⚠️ Watch glob(s) matched no registers: {', '.join('`'+g+'`' for g in w['unmatched'])}. "
                       "Fix the glob; an empty match is not evidence.")
        on = w["on_failing_seeds"]
        out.append(f"Watched registers {globs}: worst setup {f3(w['min_setup'])} ns, hold {f3(w['min_hold'])} ns, "
                   + (f"**on a failing path on seeds {', '.join(map(str, on))}**." if on else "never on a failing path.")
                   + f" ({_seeds(w['seeds_with_data'])})")
    e = res["endpoints"]
    if e["known"]:
        co = e["cand_only"]
        if co:
            top = sorted(co.items(), key=lambda kv: -kv[1])
            line = f"Failing paths end in {len(co)} place(s) the baseline never fails: " + ", ".join(
                f"`{short_node(k, 3)}` ({v})" for k, v in top[:8]) + (f" and {len(top) - 8} more" if len(top) > 8 else "")
            if not e.get("cand_only_recurring"):
                line += f". Each shows up on too few of {res['met']['cand_n']} seeds to tell from placement luck"
            out.append(line + ".")
        else:
            out.append("Every failing path ends somewhere the baseline also fails.")
    return "\n".join(f"- {x}" for x in out)


def per_seed_table(records):
    qof = any(r.get("headline", {}).get("qof") is not None for r in records)
    rows = []
    for r in sorted(records, key=lambda r: (r["variant"] != "baseline", r["seed"])):
        if r.get("status") != "ok":
            rows.append([r["variant"], r["seed"]] + ["compile failed"] + [""] * (8 + qof))
            continue
        h = r["headline"]
        rows.append([r["variant"], r["seed"]] + ([fval("qof", h.get("qof"))] if qof else []) +
                    [fval("fmax_geomean", h.get("fmax_geomean")),
                     f3(h.get("setup")), f3(h.get("hold")), f3(h.get("recovery")), f3(h.get("removal")),
                     fint(h.get("alms")), fmt_hms(h.get("compile_s")), "✓" if h.get("timing_met") else ""])
    return _table(["variant", "seed"] + (["QoF"] if qof else []) +
                  ["f(MAX) MHz", "setup", "hold", "recovery", "removal", "ALMs", "time", "met"], rows)


def clock_section(rows):
    return _table(["clock", "base fails", "PR fails", "Δ fails", "base min / median", "PR min / median",
                   "Δ min / median", "Fisher p"],
                  [[f"`{r['short']}`" + (" 🆕" if r["new_failing"] else ""), f"{r['base_fail']}/{r['base_n']}",
                    f"{r['cand_fail']}/{r['cand_n']}", _dn(r["base_fail"], r["cand_fail"]),
                    f"{f3(r['base_min'])} / {f3(r['base_median'])}", f"{f3(r['cand_min'])} / {f3(r['cand_median'])}",
                    f"{_d('setup', r['base_min'], r['cand_min'])} / {_d('setup', r['base_median'], r['cand_median'])}",
                    fp(r["p"])] for r in rows])


def fmax_section(records):
    per = {}
    for r in records:
        if r.get("status") != "ok":
            continue
        worst = {}
        for f in r.get("fmax", []):
            v = f["restricted"] if f["restricted"] is not None else f["fmax"]
            if v is not None:
                worst[f["clock"]] = min(v, worst.get(f["clock"], v))
        for c, v in worst.items():
            per.setdefault(c, {}).setdefault(r["variant"], []).append(v)
    rows = []
    for c in sorted(per, key=short_clock):
        b, p = per[c].get("baseline", []), per[c].get("candidate", [])
        rows.append([f"`{short_clock(c)}`", f"{min(b):.2f} / {sum(b)/len(b):.2f}" if b else "–",
                     f"{min(p):.2f} / {sum(p)/len(p):.2f}" if p else "–",
                     f"{_d('fmax_geomean', min(b), min(p))} / {_d('fmax_geomean', sum(b)/len(b), sum(p)/len(p))}"
                     if b and p else "–"])
    return _table(["clock", "baseline min / mean MHz", "PR min / mean MHz", "Δ min / mean"], rows)


def dict_section(records, field, fmt, dfmt=None):
    keys = []
    for r in records:
        for k in (r.get(field) or {}):
            if k not in keys and k != "status" and k != "device":
                keys.append(k)
    rows = []
    for k in keys:
        cells, means = [f"`{k}`"], []
        for v in ("baseline", "candidate"):
            vals = [r[field][k] for r in records if r["variant"] == v and r.get(field) and
                    isinstance(r[field].get(k), (int, float))]
            cells.append(f"{fmt(min(vals))} … {fmt(max(vals))}" if vals else "–")
            means.append(sum(vals) / len(vals) if vals else None)
        cells.append("–" if None in means else (dfmt or _signed(fmt))(means[1] - means[0]))
        rows.append(cells)
    return _table(["", "baseline (min … max)", "PR (min … max)", "Δ mean"], rows)


def _signed(fmt):
    def f(d):
        mag = fmt(abs(d))
        return mag if mag == fmt(0) else ("+" if d > 0 else "−") + mag
    return f


def endpoints_section(res):
    e = res["endpoints"]
    fams = sorted(set(e["base"]) | set(e["cand"]), key=lambda k: -(e["cand"].get(k, 0) + e["base"].get(k, 0)))
    return _table(["failing endpoint (normalised)", "baseline seeds", "PR seeds", "Δ"],
                  [[f"`{short_node(k, 3)}`", e["base"].get(k, 0), e["cand"].get(k, 0),
                    _dn(e["base"].get(k, 0), e["cand"].get(k, 0))] for k in fams[:40]])


def metrics_section(res):
    rows = []
    for m in res["metrics"]:
        lo, hi = m["ci"]
        k = m["key"]
        rows.append([m["label"], fval(k, m["base"]["mean"]), fval(k, m["cand"]["mean"]),
                     _d(k, m["base"]["mean"], m["cand"]["mean"]), fval(k, m["diff_median"], True) + (f" [{fval(k, lo, True)}, {fval(k, hi, True)}]" if lo is not None else ""),
                     fp(m["p"]), "⚠️ flagged" if m["flag"] else m.get("note", "")])
    return _table(["metric", "baseline mean", "PR mean", "Δ mean", "median diff [95% CI]", "perm. p", ""], rows)


def _at(variant_meta):
    short = variant_meta.get("short")
    return f" @ {short}" if short and short != "?" else ""


def _name(variant_meta):
    """Display label; a SHA given as the ref collapses to its short form."""
    label, sha = variant_meta.get("label", ""), variant_meta.get("sha") or ""
    if label and sha and sha.startswith(label):
        return variant_meta.get("short") or label[:7]
    return label


def _ref(variant_meta):
    name = _name(variant_meta)
    return name if name == variant_meta.get("short") else name + _at(variant_meta)


def _seeds(n):
    return f"{n} seed" if n == 1 else f"{n} seeds"


def _seed_count(res):
    b, c = res["met"]["base_n"], res["met"]["cand_n"]
    return f"{_seeds(c)} each" if b == c else f"{b} baseline / {c} PR seeds"


def comment(res, run_url=None, artifact_note=None):
    meta = res["meta"]
    corner = _corner_text(res)
    title = f"### Seedy — {meta['project']}: {_ref(meta['candidate'])} vs {_ref(meta['baseline'])}"
    sub = (f"**{res['verdict']}** · Quartus {meta.get('quartus_version_short', '?')} · {_seed_count(res)}"
           + (f" · timing at {corner}" if corner else ""))
    parts = [marker(meta["project"]), title, "", sub, "", plain_summary(res), ""]
    if res["reasons"]:
        parts += ["**Flagged** (timing got measurably worse):", ""] + [f"- {r}" for r in res["reasons"]] + [""]
    if res.get("review"):
        parts += ["**Needs a maintainer's eye** (whatever the numbers say, this PR):", ""] + \
                 [f"- {r}" for r in res["review"]] + [""]
    parts += [headline(res), "", failing_clocks(res), ""]
    sig = signals(res)
    if sig:
        parts += [sig, ""]
    parts += [seed_section(res), ""]
    if res["missing"]:
        parts.append("⚠️ Compile failed: " + ", ".join(f"{v} seed {s}" for v, s in res["missing"]) + ".")
        parts.append("")
    if res["thresholds"]["set"]:
        t = res["thresholds"]["failures"]
        parts += (["**Thresholds:** ❌", ""] + [f"- {x}" for x in t] if t else ["**Thresholds:** ✅ all passed"]) + [""]
    head = "\n".join(parts)
    recs = res["_records"]
    blocks = [
        _details("How to read this", GLOSSARY),
        _details("Statistics (all metrics)", metrics_section(res)),
        _details(f"Per-seed table ({len(recs)} rows)", per_seed_table(recs)),
        _details("Per-clock setup slack, every clock", clock_section(res["clocks_setup"])),
    ]
    if res["clocks_hold"] and any(r.get("source") == "compile" for r in recs):
        blocks.append(_details("Per-clock hold slack", clock_section(res["clocks_hold"])))
    blocks.append(_details("f(MAX) per clock (worst corner)", fmax_section(recs)))
    blocks.append(_details("Utilization", dict_section(recs, "utilization", lambda v: f"{v:,.0f}")))
    blocks.append(_details("Runtime", dict_section(recs, "runtime_s", fmt_hms)))
    if any(r.get("peak_mem_mb") for r in recs):
        blocks.append(_details("Peak memory (MB)", dict_section(recs, "peak_mem_mb", lambda v: f"{v:,.0f}")))
    if res["endpoints"]["known"]:
        blocks.append(_details("Failing endpoints", endpoints_section(res)))
    if (res.get("constraints") or {}).get("known"):
        blocks.append(_details("Constraint health", constraint_section(res)))
    foot = ("<sub>" + f"{res['met']['base_n']} seeds per variant detect only large shifts; seeds are unpaired samples. "
            f"~{len(res['metrics']) + 2} metrics tested, p-values uncorrected (two-sided permutation test on means, "
            "20,000 shuffles, fixed RNG; Fisher exact for counts). "
            + ("QoF exists only for DSE runs. " if not any(m["key"] == "qof" for m in res["metrics"]) else "")
            + (f"[Run and artifacts]({run_url}). " if run_url else "")
            + (artifact_note or "") + "</sub>")
    body = head + "\n" + "\n".join(blocks) + "\n\n" + foot
    if len(body) > COMMENT_LIMIT - 200:
        body = head + "\n" + blocks[0] + "\n" + blocks[1] + \
            "\n\n_Detail tables were too large for a comment; see the `seedy-results` artifact._\n\n" + foot
    return body


def summary(res, run_url=None):
    """GitHub job summary: the comment plus nothing hidden."""
    return comment(res, run_url).replace(marker(res["meta"]["project"]) + "\n", "")


# ---------------------------------------------------------------- single variant (hunt / baseline-only)
def single(merged, decision, run_url=None, status_lines=()):
    from seedy.compare import clock_table
    meta, recs = merged["meta"], merged["records"]
    variant = recs[0]["variant"]
    v = meta.get(variant, {})
    ok = [r for r in recs if r.get("status") == "ok"]
    met = sorted(r["seed"] for r in ok if r["headline"].get("timing_met"))
    not_run = meta.get("not_run", {}).get(variant, [])
    hunt = meta.get("mode") == "hunt"
    title = f"### Seedy {'seed hunt' if hunt else 'baseline'} — {meta['project']}: {_ref(v)}"
    sub = (f"**{len(met)} meet timing** · Quartus {meta.get('quartus_version_short', '?')} · "
           f"{_seeds(len(recs))} compiled")
    out = [marker(meta["project"]), title, "", sub, ""]
    if hunt:
        from seedy.plan import parse_seeds
        target = meta.get("min_met", 1)
        planned = parse_seeds(meta["seeds"]) if meta.get("seeds") else [r["seed"] for r in recs]
        out.append(f"- Hunted seeds {meta.get('seeds')}: compiled {len(recs)}, {len(recs) - len(ok)} failed to compile, "
                   f"{len(not_run)} not started. Target was {target} seed(s) meeting timing: "
                   + ("**reached**." if len(met) >= target else "**not reached**."))
        if meta.get("incomplete"):
            out.append("- ⚠️ **Some compile jobs failed or timed out**, so some of the seeds counted as not started were "
                       "lost, not skipped. See the run's job logs.")
        if len(met) < target:
            # seeds are interchangeable random draws: continuing past the planned range repeats nothing,
            # and the unstarted seeds inside it are no more promising than new ones
            out.append(f"- To continue, run again with `seed_start: {max(planned) + 1}`; no seed is compiled twice.")
        out.append("")
    out.append(f"Seeds meeting timing: {', '.join(map(str, met)) if met else 'none'}.")
    out.append("")
    ranked = seedpick.rank(ok)
    if decision.get("best") is not None:
        tag = "Recommended seed" if decision["best_met"] else "Closest seed (none met timing)"
        rec = next((r for r in ranked if r["seed"] == decision["best"]), None)
        out += [_best_line(tag, decision["best"], rec, decision.get("best_why")), ""]
        bullets = []
        if meta.get("rbf_artifact"):
            bullets.append(f"Its `.rbf` is in the `{meta['rbf_artifact']}` artifact: the exact bitstream that was measured.")
        note = _shipped_note(decision, ranked)
        if note:
            bullets.append(note)
        if meta.get("seed_policy", "never") not in ("never", "off"):
            bullets.append(("Will be committed: " if decision.get("apply") else "Not committed: ") + decision["reason"] + ".")
        out += [f"- {b}" for b in bullets] + ([""] if bullets else [])
    out.append(ranked_table(ranked, decision.get("shipped")))
    out.append("")
    fails = [c for c in clock_table(ok, ok, "setup") if c["cand_fail"]]
    if fails:
        out.append("Clocks failing setup, by seeds: " + ", ".join(
            f"`{c['short']}` {c['cand_fail']}/{c['cand_n']} (worst {f3(c['cand_min'])})"
            for c in sorted(fails, key=lambda c: -c["cand_fail"])) + ".")
        out.append("")
    from seedy.compare import constraint_summary
    cs = constraint_summary(ok)
    if cs:
        issues = [f"{f(cs)} {label.split(' (')[0].lower()}" for label, f in _CONSTRAINT_ROWS[:3] if f(cs)]
        if issues:
            out.append("Timing constraints: " + ", ".join(issues) + ". Those paths are not covered by the slack numbers.")
            out.append("")
    fam = {}
    for r in ok:
        for k in r.get("derived", {}).get("failing_endpoints", {}):
            fam[k] = fam.get(k, 0) + 1
    blocks = [_details("How to read this", GLOSSARY), _details(f"All seeds ({len(recs)})", per_seed_table(recs))]
    if fam:
        blocks.append(_details("Failing endpoints (seeds)", _table(["endpoint", "seeds"], [
            [f"`{short_node(k, 3)}`", n] for k, n in sorted(fam.items(), key=lambda kv: -kv[1])[:40]])))
    blocks.append(_details("Utilization", dict_section(recs, "utilization", lambda x: f"{x:,.0f}")))
    blocks.append(_details("Runtime", dict_section(recs, "runtime_s", fmt_hms)))
    if status_lines:
        blocks.append(_details("Shard stop reasons", "```\n" + "\n".join(status_lines) + "\n```"))
    foot = "<sub>" + (f"[Run and artifacts]({run_url}). " if run_url else "") + \
        "Ranking: meets timing, then worst of the four WC slacks, then total negative slack.</sub>"
    body = "\n".join(out) + "\n" + "\n".join(blocks) + "\n\n" + foot
    if len(body) > COMMENT_LIMIT - 200:
        body = "\n".join(out) + "\n_Detail tables too large; see the `seedy-results` artifact._\n\n" + foot
    return body
