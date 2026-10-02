"""Markdown (PR comment, job summary) and CSV outputs."""
import csv
import io

from seedy.compare import short_clock
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
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def _details(summary, body):
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def headline(res):
    meta = res["meta"]
    m = {x["key"]: x for x in res["metrics"]}
    met = res["met"]
    bl, cl = meta["baseline"]["label"], meta["candidate"]["label"]
    rows = [["Seeds meeting timing", f"{len(met['base'])}/{met['base_n']}",
             f"{len(met['cand'])}/{met['cand_n']} (Fisher p = {fp(met['p'])})"]]

    def mean_median(key, unit):
        x = m.get(key)
        if not x:
            return None
        b, c = x["base"], x["cand"]
        return [f"{x['label']}, mean / median",
                f"{fval(key, b['mean'])} / {fval(key, b['median'])} {unit}".strip(),
                f"{fval(key, c['mean'])} / {fval(key, c['median'])} {unit} ({peq(x['p'])})"]
    for key, unit in (("setup", "ns"), ("hold", "ns")):
        r = mean_median(key, unit)
        if r:
            rows.append(r)
    if "setup" in m:
        rows.append(["WC slack: setup, range", f"{f3(m['setup']['base']['min'])} … {f3(m['setup']['base']['max'])}",
                     f"{f3(m['setup']['cand']['min'])} … {f3(m['setup']['cand']['max'])}"])
    if "hold" in m:
        def neg(variant):
            recs = [r for r in res["_records"] if r["variant"] == variant and r.get("status") == "ok"]
            vals = [r["headline"]["hold"] for r in recs if r["headline"].get("hold") is not None]
            n = sum(v < 0 for v in vals)
            return f"{n}" + (f" (worst {f3(min(vals))})" if n else "")
        rows.append(["Seeds with negative hold", neg("baseline"), neg("candidate")])
    for key in ("recovery", "removal"):
        if key in m:
            rows.append([f"WC slack: {key}, worst", f3(m[key]["base"]["min"]),
                         f"{f3(m[key]['cand']['min'])} ({peq(m[key]['p'])})"])
    for key, unit in (("fmax_geomean", "MHz"), ("alms", "ALMs"), ("qof", "")):
        if key in m:
            u = f" {unit}" if unit else ""
            rows.append([f"{m[key]['label']}, mean", f"{fval(key, m[key]['base']['mean'])}{u}",
                         f"{fval(key, m[key]['cand']['mean'])}{u} ({peq(m[key]['p'])})"])
    if "compile_s" in m:
        b, c = m["compile_s"]["base"], m["compile_s"]["cand"]
        rows.append(["Compile time, range", f"{fmt_hms(b['min'])} … {fmt_hms(b['max'])}",
                     f"{fmt_hms(c['min'])} … {fmt_hms(c['max'])} ({peq(m['compile_s']['p'])})"])
    sb, sc = res["shipped"]["baseline"], res["shipped"]["candidate"]
    if sb or sc:
        def sh(r):
            if not r:
                return "–"
            if r.get("status") != "ok":
                return "compile failed"
            h = r["headline"]
            return f"{f3(h['setup'])} / {f3(h['hold'])}" + (" ✓" if h.get("timing_met") else "")
        seeds = meta.get("shipped_seed", {})
        label = f"Shipped seed ({seeds.get('baseline')}" + \
            (f" / {seeds.get('candidate')}" if seeds.get("candidate") != seeds.get("baseline") else "") + ") setup / hold"
        rows.append([label, sh(sb), sh(sc)])
    return _table(["", bl, cl], rows)


def seed_section(res):
    s = res["seed"]
    meta = res["meta"]
    if s.get("best") is None:
        return "**Seed:** no candidate seed compiled successfully."
    lines = []
    tag = "Recommended seed" if s["best_met"] else "Least-bad seed"
    lines.append(f"**{tag} for hardware testing: {s['best']}**: {s['best_why']}.")
    if meta.get("rbf_artifact"):
        lines.append(f"Its `.rbf` is in the `{meta['rbf_artifact']}` artifact; that exact bitstream is what was measured.")
    if s.get("applied"):
        lines.append(f"Committed to `{meta['revision']}.qsf` as {s['applied']}.")
    elif meta.get("seed_policy", "never") not in ("never", "off"):
        lines.append(f"Not committed: {s['reason']}.")
    if len(s.get("top", [])) > 1:
        lines.append("Runners-up: " + "; ".join(t["why"] for t in s["top"][1:4]) + ".")
    return "\n".join(lines)


def signals(res):
    out = []
    cs = res["clocks_setup"]
    bf = sorted({r["short"] for r in cs if r["base_fail"]})
    cf = sorted({r["short"] for r in cs if r["cand_fail"]})
    if bf == cf:
        out.append("Failing setup clocks are the same in both: " + (", ".join(cf) if cf else "none") + ".")
    else:
        out.append(f"Failing setup clocks: baseline {', '.join(bf) or 'none'}; this PR {', '.join(cf) or 'none'}.")
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
            out.append("Failing endpoints only this PR has: " + ", ".join(
                f"`{short_node(k, 3)}` ({v} seeds)" for k, v in sorted(co.items(), key=lambda kv: -kv[1])[:8]) + ".")
        else:
            out.append("No failing endpoint appears that the baseline does not also have.")
    return "\n".join(out)


def per_seed_table(records):
    rows = []
    for r in sorted(records, key=lambda r: (r["variant"] != "baseline", r["seed"])):
        if r.get("status") != "ok":
            rows.append([r["variant"], r["seed"]] + ["compile failed"] + [""] * 8)
            continue
        h = r["headline"]
        rows.append([r["variant"], r["seed"], fval("qof", h.get("qof")), fval("fmax_geomean", h.get("fmax_geomean")),
                     f3(h.get("setup")), f3(h.get("hold")), f3(h.get("recovery")), f3(h.get("removal")),
                     fint(h.get("alms")), fmt_hms(h.get("compile_s")), "✓" if h.get("timing_met") else ""])
    return _table(["variant", "seed", "QoF", "f(MAX) MHz", "setup", "hold", "recovery", "removal", "ALMs", "time", "met"], rows)


def clock_section(rows):
    return _table(["clock", "base fails", "PR fails", "base min / median", "PR min / median", "Fisher p"],
                  [[f"`{r['short']}`" + (" 🆕" if r["new_failing"] else ""), f"{r['base_fail']}/{r['base_n']}",
                    f"{r['cand_fail']}/{r['cand_n']}", f"{f3(r['base_min'])} / {f3(r['base_median'])}",
                    f"{f3(r['cand_min'])} / {f3(r['cand_median'])}", fp(r["p"])] for r in rows])


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
                     f"{min(p):.2f} / {sum(p)/len(p):.2f}" if p else "–"])
    return _table(["clock", "baseline min / mean MHz", "PR min / mean MHz"], rows)


def dict_section(records, field, fmt):
    keys = []
    for r in records:
        for k in (r.get(field) or {}):
            if k not in keys and k != "status" and k != "device":
                keys.append(k)
    rows = []
    for k in keys:
        cells = [f"`{k}`"]
        for v in ("baseline", "candidate"):
            vals = [r[field][k] for r in records if r["variant"] == v and r.get(field) and
                    isinstance(r[field].get(k), (int, float))]
            cells.append(f"{fmt(min(vals))} … {fmt(max(vals))}" if vals else "–")
        rows.append(cells)
    return _table(["", "baseline (min … max)", "PR (min … max)"], rows)


def endpoints_section(res):
    e = res["endpoints"]
    fams = sorted(set(e["base"]) | set(e["cand"]), key=lambda k: -(e["cand"].get(k, 0) + e["base"].get(k, 0)))
    return _table(["failing endpoint (normalised)", "baseline seeds", "PR seeds"],
                  [[f"`{short_node(k, 3)}`", e["base"].get(k, 0), e["cand"].get(k, 0)] for k in fams[:40]])


def metrics_section(res):
    rows = []
    for m in res["metrics"]:
        lo, hi = m["ci"]
        k = m["key"]
        rows.append([m["label"], fval(k, m["base"]["mean"]), fval(k, m["cand"]["mean"]),
                     fval(k, m["diff_median"], True) + (f" [{fval(k, lo, True)}, {fval(k, hi, True)}]" if lo is not None else ""),
                     fp(m["p"]), "⚠️ flagged" if m["flag"] else m.get("note", "")])
    return _table(["metric", "baseline mean", "PR mean", "median diff [95% CI]", "perm. p", ""], rows)


def _at(variant_meta):
    short = variant_meta.get("short")
    return f" @ {short}" if short and short != "?" else ""


def _seeds(n):
    return f"{n} seed" if n == 1 else f"{n} seeds"


def _seed_count(res):
    b, c = res["met"]["base_n"], res["met"]["cand_n"]
    return f"{_seeds(c)} each" if b == c else f"{b} baseline / {c} PR seeds"


def comment(res, run_url=None, artifact_note=None):
    meta = res["meta"]
    title = (f"**Seedy — {meta['project']}{_at(meta['candidate'])} vs {meta['baseline']['label']}"
             f"{_at(meta['baseline'])}** · Quartus {meta.get('quartus_version_short', '?')} · "
             f"{_seed_count(res)} · *{res['verdict']}*")
    parts = [marker(meta["project"]), title, ""]
    if res["reasons"]:
        parts.append("Flags: " + "; ".join(res["reasons"]) + ".")
        parts.append("")
    parts += [headline(res), "", signals(res), "", seed_section(res), ""]
    if res["missing"]:
        parts.append("⚠️ Compile failed: " + ", ".join(f"{v} seed {s}" for v, s in res["missing"]) + ".")
        parts.append("")
    if res["thresholds"]["set"]:
        t = res["thresholds"]["failures"]
        parts.append("**Thresholds:** " + ("❌ " + "; ".join(t) if t else "✅ all passed"))
        parts.append("")
    head = "\n".join(parts)
    recs = res["_records"]
    blocks = [
        _details("Statistics (all metrics)", metrics_section(res)),
        _details(f"Per-seed table ({len(recs)} rows)", per_seed_table(recs)),
        _details("Per-clock setup slack (worst over corners)", clock_section(res["clocks_setup"])),
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
    foot = ("<sub>" + f"{res['met']['base_n']} seeds per variant detect only large shifts; seeds are unpaired samples. "
            f"~{len(res['metrics']) + 1} metrics tested, p-values uncorrected (two-sided permutation test, "
            "20,000 shuffles, fixed RNG; Fisher exact for counts). "
            + ("QoF exists only for DSE runs. " if not any(m["key"] == "qof" for m in res["metrics"]) else "")
            + (f"[Run and artifacts]({run_url}). " if run_url else "")
            + (artifact_note or "") + "</sub>")
    body = head + "\n" + "\n".join(blocks) + "\n\n" + foot
    if len(body) > COMMENT_LIMIT - 200:
        body = head + "\n" + blocks[0] + "\n\n_Detail tables were too large for a comment; see the `seedy-results` artifact._\n\n" + foot
    return body


def summary(res, run_url=None):
    """GitHub job summary: the comment plus nothing hidden."""
    return comment(res, run_url).replace(marker(res["meta"]["project"]) + "\n", "")


# ---------------------------------------------------------------- single variant (hunt / baseline-only)
def single(merged, decision, run_url=None, status_lines=()):
    from seedy import seedpick
    from seedy.compare import clock_table
    meta, recs = merged["meta"], merged["records"]
    variant = recs[0]["variant"]
    v = meta.get(variant, {})
    ok = [r for r in recs if r.get("status") == "ok"]
    met = sorted(r["seed"] for r in ok if r["headline"].get("timing_met"))
    not_run = meta.get("not_run", {}).get(variant, [])
    hunt = meta.get("mode") == "hunt"
    title = (f"**Seedy {'seed hunt' if hunt else 'baseline'} — {meta['project']}{_at(v)}** · "
             f"Quartus {meta.get('quartus_version_short', '?')} · {_seeds(len(recs))} compiled · "
             f"*{len(met)} meet timing*")
    out = [marker(meta["project"]), title, ""]
    if hunt:
        target = meta.get("min_met", 1)
        out.append(f"Hunted seeds {meta.get('seeds')}: compiled {len(recs)}, {len(recs) - len(ok)} failed to compile, "
                   f"{len(not_run)} not started. Target was {target} seed(s) meeting timing: "
                   + ("**reached**." if len(met) >= target else "**not reached**."))
        if not_run:
            out.append(f"To continue the hunt, run again with `seed_start: {max(r['seed'] for r in recs) + 1}`"
                       " (seeds already compiled are not repeated)." if not met or len(met) < target else "")
        out.append("")
    out.append(f"Seeds meeting timing: {', '.join(map(str, met)) if met else 'none'}.")
    out.append("")
    if decision.get("best") is not None:
        tag = "Recommended seed" if decision["best_met"] else "Closest seed (none met timing)"
        out.append(f"**{tag}: {decision['best']}**: {decision['best_why']}.")
        if meta.get("rbf_artifact"):
            out.append(f"Its `.rbf` is in the `{meta['rbf_artifact']}` artifact: the exact bitstream that was measured.")
        if meta.get("seed_policy", "never") not in ("never", "off"):
            out.append(("Will be committed: " if decision.get("apply") else "Not committed: ") + decision["reason"] + ".")
        out.append("")
    ranked = seedpick.rank(ok)
    rows = []
    for r in ranked[:15]:
        h = r["headline"]
        neg = seedpick._neg_tns(r)
        rows.append([r["seed"], "✓" if h.get("timing_met") else "", f3(h.get("setup")), f3(h.get("hold")),
                     f3(h.get("recovery")), f3(h.get("removal")), f3(neg) if r.get("clocks") and neg else "–",
                     fval("fmax_geomean", h.get("fmax_geomean")), fint(h.get("alms"))])
    out.append(_table(["seed", "met", "setup", "hold", "recovery", "removal", "TNS sum", "f(MAX)", "ALMs"], rows))
    out.append("")
    fails = [c for c in clock_table(ok, ok, "setup") if c["cand_fail"]]
    if fails:
        out.append("Clocks failing setup, by seeds: " + ", ".join(
            f"`{c['short']}` {c['cand_fail']}/{c['cand_n']} (worst {f3(c['cand_min'])})"
            for c in sorted(fails, key=lambda c: -c["cand_fail"])) + ".")
        out.append("")
    fam = {}
    for r in ok:
        for k in r.get("derived", {}).get("failing_endpoints", {}):
            fam[k] = fam.get(k, 0) + 1
    blocks = [_details(f"All seeds ({len(recs)})", per_seed_table(recs))]
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
