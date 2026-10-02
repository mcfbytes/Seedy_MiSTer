"""A1 and A4 from the spec, plus full-compile == DSE equivalence on the golden fixture."""
import os
import unittest

from seedy import parse, records, render
from tests import helpers


class DseImportTest(unittest.TestCase):
    def test_a1_reproduces_hand_made_sweep_csv(self):
        recs = helpers.dse_records()
        self.assertEqual(len(recs), 60)
        got = render.seeds_csv(recs, {"baseline": "up", "candidate": "ir"})
        want = open(os.path.join(helpers.FX, "snes-seed-sweep.csv")).read()
        self.assertEqual(got, want)

    def test_positional_point_names(self):
        recs = records.from_dse_dir(os.path.join(helpers.FX, "dse-up-b"), list(range(17, 31)), "baseline")
        r17 = next(r for r in recs if r["seed"] == 17)
        self.assertEqual(r17["dse_point"], 1)
        self.assertEqual(r17["headline"]["setup"], -0.509)

    def test_values(self):
        self.assertEqual(parse.num('"35,081"'), 35081)
        self.assertEqual(parse.num("78.411 MHz"), 78.411)
        self.assertEqual(parse.hms("00:15:39"), 939)
        self.assertIsNone(parse.num("--"))


class CompileRecordTest(unittest.TestCase):
    def test_full_compile_matches_dse_point(self):
        """Seed 1 compiled with quartus_sh --flow equals DSE's seed-1 point (except QoF and time)."""
        rec = records.from_compile_dir(helpers.compile_dir_ir(), "SNES", seed=1, variant="candidate")
        dse = next(r for r in helpers.dse_records() if r["variant"] == "candidate" and r["seed"] == 1)
        for k in ("setup", "hold", "recovery", "removal", "alms", "timing_met"):
            self.assertEqual(rec["headline"][k], dse["headline"][k], k)
        self.assertAlmostEqual(rec["headline"]["fmax_geomean"], dse["headline"]["fmax_geomean"], places=3)
        self.assertEqual(len(rec["corners"]), 4)
        self.assertEqual(rec["utilization"]["dsp_blocks"], 61)
        self.assertEqual(rec["peak_mem_mb"]["Fitter"], 6411)
        self.assertEqual(rec["runtime_s"]["Total"], 820)

    def test_sta_tsv_watch(self):
        rec = records.from_compile_dir(helpers.compile_dir_ir(), "SNES", seed=1, variant="candidate")
        d = rec["derived"]
        self.assertEqual(d["watched_min_setup"], 1.671)
        self.assertEqual(d["watched_min_hold"], 0.174)
        self.assertFalse(d["watched_on_failing"])
        self.assertEqual(d["watched_unmatched"], ["*nosuchreg*"])  # an empty glob is reported, not hidden

    def test_missing_reports_is_compile_failed(self):
        import tempfile
        rec = records.from_compile_dir(tempfile.mkdtemp(), "SNES", seed=3, variant="baseline")
        self.assertEqual(rec["status"], "compile_failed")

    def test_sta_summary(self):
        s = parse.sta_summary(open(os.path.join(helpers.FX, "full-ir", "SNES.sta.summary")).read())
        setup = [c for c in s if c["kind"] == "setup"]
        self.assertEqual(len(setup), 10)
        self.assertEqual(min(c["slack"] for c in setup), -0.898)


class LegacyPathsTest(unittest.TestCase):
    def test_a4_watched_registers(self):
        d = records.derive_paths(helpers.legacy("ir"))
        self.assertEqual(d["watched_min_setup"], 1.671)
        self.assertEqual(d["watched_min_hold"], 0.174)
        self.assertFalse(d["watched_on_failing"])
        ramimg = [w for w in helpers.legacy("ir")["watch"] if w["slack"] == 1.671]
        self.assertIn("ramimg_valid", ramimg[0]["from"])
        self.assertIn("SDRAM", ramimg[0]["to"])

    def test_a4_failing_endpoints(self):
        ir = {records.short_node(k): n for k, n in records.derive_paths(helpers.legacy("ir"))["failing_endpoints"].items()}
        up = {records.short_node(k): n for k, n in records.derive_paths(helpers.legacy("up"))["failing_endpoints"].items()}
        self.assertEqual(set(ir), {"P65C816|P"})
        self.assertEqual(set(up), {"P65C816|P", "sdram|din", "video_calc|dout"})

    def test_endpoint_family(self):
        self.assertEqual(records.endpoint_family("a|b|din[1][3]~DUPLICATE"), "a|b|din")


if __name__ == "__main__":
    unittest.main()
