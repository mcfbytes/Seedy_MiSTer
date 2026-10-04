"""A3: the comment's headline table, collapsible detail and the size limit."""
import copy
import unittest

from seedy import compare, render
from tests import helpers


def result(merged=None, policy="off"):
    merged = merged or helpers.merged()
    res = compare.compare(merged, {}, policy)
    res["_records"] = merged["records"]
    return res


class RenderTest(unittest.TestCase):
    def test_headline_rows(self):
        c = render.comment(result())
        self.assertTrue(c.startswith("<!-- seedy:SNES -->"))
        for row in ("### [MiSTer Seedy](https://github.com/mcfbytes/Seedy_MiSTer) — SNES: this PR @ 75f10d3 vs master @ c61bfd4",
                    "Report by [MiSTer Seedy](https://github.com/mcfbytes/Seedy_MiSTer) ",
                    "Timing closed on 3 of 30 seeds of this PR, against 6 of 30 on master.",
                    "| master | this PR | Δ | p |",
                    "Seeds that close timing | 6/30 | 3/30 | −3 | 0.47",
                    "average / typical seed | −0.469 / −0.403 | −0.341 / −0.275 | +0.128 / +0.128 | 0.29",
                    "Seeds with a hold violation | 5/30 | 8/30 | +3 | 0.53",
                    "Logic used (ALMs), average | 35,116 | 34,939 | −177 | < 0.001",
                    "| `emu c0` | 21/30 | 14/30 | −7 |",
                    "seed (1): setup / hold (ns) | −0.515 / +0.021 ✗ | −0.898 / +0.076 ✗ | −0.383 / +0.055",
                    "**No measurable regression**", "**Recommended seed for hardware testing: 18** (meets timing",
                    "The `.qsf`'s seed 1 does not meet timing", "<details><summary>How to read this"):
            self.assertIn(row, c)
        self.assertIn("<details><summary>Per-seed table (60 rows)", c)
        self.assertIn("<details><summary>Per-clock setup slack", c)
        self.assertIn("| QoF |", render.per_seed_table(helpers.dse_records()))
        no_qof = helpers.dse_records()
        for r in no_qof:
            r["headline"]["qof"] = None
        self.assertNotIn("| QoF |", render.per_seed_table(no_qof))
        self.assertIn("| Δ fails |", c)

    def test_sha_label_collapses(self):
        m = helpers.merged()
        m["meta"]["baseline"] = {"label": "c61bfd45171c62000417333cd4679890bcd091a6",
                                 "sha": "c61bfd45171c62000417333cd4679890bcd091a6", "short": "c61bfd4"}
        c = render.comment(result(m))
        self.assertIn("vs c61bfd4\n", c)
        self.assertNotIn("c61bfd45171c", c)

    def test_rare_new_endpoints_do_not_flag(self):
        m = helpers.merged()
        path = {"corner": "slow", "kind": "setup", "slack": -0.1, "from": "a", "to": "emu:emu|new:new|reg", "launch": "", "latch": ""}
        for r in m["records"]:
            r["paths"] = [dict(path, to="emu:emu|old:old|reg")]
            r["derived"] = {"failing_endpoints": {"emu|old|reg": 1}}
        cand = [r for r in m["records"] if r["variant"] == "candidate"]
        cand[0]["derived"]["failing_endpoints"]["emu|new|reg"] = 1
        res = result(m)
        self.assertFalse(any("endpoint" in x for x in res["reasons"]))
        self.assertIn("too few of 30 seeds", render.comment(res))
        for r in cand[:8]:
            r["derived"]["failing_endpoints"]["emu|new|reg"] = 1
        res = result(m)
        self.assertIn("new failing endpoints: `emu|new|reg` (8/30 seeds)", res["reasons"])

    def test_review_flags(self):
        m = helpers.merged()
        m["meta"]["shipped_seed"] = {"baseline": 1, "candidate": 4}
        m["meta"]["changed_paths"] = ["rtl/ppu.vhd", "sys/ascal.vhd", "SNES.sdc", "SNES.qsf"]
        for r in m["records"]:
            r["clocks"] = [{"corner": "worst", "kind": "setup", "clock": "emu|pll|counter[0].x", "slack": 1.0, "tns": 0.0}]
            if r["variant"] == "candidate":
                r["clocks"].append({"corner": "worst", "kind": "setup", "clock": "emu|pll|counter[3].x", "slack": 1.0, "tns": 0.0})
        res = result(m)
        text = "\n".join(res["review"])
        for want in ("adds clock(s) `emu c3`", "SEED (1 → 4)", "`sys/` framework: `sys/ascal.vhd`", "(`.sdc`): `SNES.sdc`",
                     "(`.qsf`): `SNES.qsf`"):
            self.assertIn(want, text)
        self.assertNotIn("ppu", text)
        self.assertIn("Needs a maintainer's eye", render.comment(res))

    def test_threads_setting_shown_and_flagged(self):
        m = helpers.merged()
        for r in m["records"]:
            r["threads"], r["threads_override"] = "ALL", False
        res = result(m)
        self.assertEqual(res["threads"], {"base": ["ALL"], "cand": ["ALL"]})
        self.assertFalse(any("NUM_PARALLEL_PROCESSORS" in x for x in res["review"]))
        self.assertIn("· NUM_PARALLEL_PROCESSORS ALL", render.comment(res))
        for r in m["records"]:
            if r["variant"] == "candidate":
                r["threads"] = "16"
        res = result(m)
        self.assertIn("NUM_PARALLEL_PROCESSORS (ALL → 16)", "\n".join(res["review"]))
        self.assertIn("· NUM_PARALLEL_PROCESSORS 16 / ALL", render.comment(res))
        for r in m["records"]:
            r["threads"], r["threads_override"] = "4", True
        res = result(m)
        self.assertFalse(any("NUM_PARALLEL_PROCESSORS" in x for x in res["review"]))
        self.assertIn("· NUM_PARALLEL_PROCESSORS 4 (override)", render.comment(res))

    def test_reset_slack_flags_only_when_failing(self):
        res = result()  # recovery shifts with p = 0.04 but every seed keeps > +2.5 ns
        self.assertFalse(any("recovery" in r for r in res["reasons"]))
        self.assertNotIn("Recovery slack", render.comment(res))

    def test_constraint_regressions_flag(self):
        import os
        from seedy import parse
        text = open(os.path.join(os.path.dirname(__file__), "fixtures", "galaksija-2025-11-27", "Galaksija.sta.rpt")).read()
        worse = text.replace("analyzing 8 combinational loops", "analyzing 9 combinational loops") + (
            "Warning (332049): Ignored set_false_path at sys_top.sdc(47): Argument <to> is an empty collection\n"
            "Warning (332060): Node: emu:emu|core:core|blank_latch was determined to be a clock but was found "
            "without an associated clock assignment.\n")
        m = helpers.merged()
        for r in m["records"]:
            r["constraints"] = parse.sta_rpt(worse if r["variant"] == "candidate" else text)
        res = result(m)
        text_flags = "\n".join(res["review"])
        self.assertIn("sys_top.sdc(47)", text_flags)
        self.assertIn("`emu|core|blank_latch`", text_flags)
        self.assertIn("(8 → 9)", text_flags)
        c = render.comment(res)
        self.assertIn("this PR leaves something new untimed", c)
        self.assertIn("<details><summary>Constraint health", c)
        self.assertIn("| Clocks with no constraint (paths not timed) | 3 | 4 | +1 |", c)
        # unchanged constraints: one calm line, no flags
        for r in m["records"]:
            r["constraints"] = parse.sta_rpt(text)
        res = result(m)
        self.assertEqual(res["review"], [])
        self.assertIn("nothing new is left untimed", render.comment(res))

    def test_size_limit_truncates(self):
        m = helpers.merged()
        big = copy.deepcopy(m)
        # 3000 seeds' worth of rows forces truncation
        recs = []
        for i in range(1500):
            for r in m["records"][:2]:
                x = copy.deepcopy(r)
                x["seed"] = i + 1
                x["variant"] = "baseline" if len(recs) % 2 == 0 else "candidate"
                recs.append(x)
        big["records"] = recs
        c = render.comment(result(big))
        self.assertLess(len(c), render.COMMENT_LIMIT)
        self.assertIn("too large for a comment", c)

    def test_regression_is_named(self):
        m = helpers.merged()
        for r in m["records"]:
            if r["variant"] == "candidate":
                r["headline"]["setup"] -= 1.0
                r["headline"]["timing_met"] = False
        res = result(m)
        self.assertEqual(res["verdict"], "Possible regression")
        self.assertIn("WC slack: setup worse", render.comment(res))

    def test_delta_is_the_difference_of_the_printed_columns(self):
        # 35,138.40 vs 35,137.83 ALMs both print as 35,138: the delta must read 0, not -1 (run 37214664117).
        self.assertEqual(render._d("alms", 35138.40, 35137.83), "+0")
        self.assertEqual(render._d("alms", 35138.4, 35139.6), "+2")
        self.assertEqual(render._d("setup", -0.1734, -0.2656), "−0.093")

    def test_csv_outputs(self):
        recs = helpers.dse_records()
        self.assertEqual(render.seeds_csv(recs).count("\n"), 61)
        self.assertIn("variant,seed,corner,kind,clock", render.per_clock_csv(recs))


if __name__ == "__main__":
    unittest.main()
