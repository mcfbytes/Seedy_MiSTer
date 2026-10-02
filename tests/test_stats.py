"""A2 from the spec: the comparison numbers of the 2026-10-02 SNES run."""
import unittest

from seedy import compare, seedpick, stats
from tests import helpers


class StatsTest(unittest.TestCase):
    def test_fisher(self):
        self.assertAlmostEqual(stats.fisher_exact(6, 24, 3, 27), 0.4716, places=4)
        self.assertAlmostEqual(stats.fisher_exact(3, 1, 1, 3), 0.4857, places=4)
        self.assertEqual(stats.fisher_exact(0, 10, 0, 10), 1.0)

    def test_permutation_is_reproducible(self):
        x, y = [1, 2, 3, 4, 5], [3, 4, 5, 6, 7]
        self.assertEqual(stats.permutation_test(x, y), stats.permutation_test(x, y))


class A2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = compare.compare(helpers.merged())
        cls.m = {x["key"]: x for x in cls.res["metrics"]}

    def test_met(self):
        met = self.res["met"]
        self.assertEqual(met["base"], [4, 8, 11, 13, 19, 30])
        self.assertEqual(met["cand"], [2, 4, 18])
        self.assertAlmostEqual(met["p"], 0.47, places=2)

    def test_means_medians(self):
        m = self.m
        self.assertAlmostEqual(m["setup"]["base"]["mean"], -0.469, places=3)
        self.assertAlmostEqual(m["setup"]["cand"]["mean"], -0.341, places=3)
        self.assertAlmostEqual(m["setup"]["base"]["median"], -0.403, places=3)
        self.assertAlmostEqual(m["setup"]["cand"]["median"], -0.275, places=3)
        self.assertEqual(m["recovery"]["base"]["min"], 3.223)
        self.assertEqual(m["recovery"]["cand"]["min"], 2.539)
        self.assertEqual(m["removal"]["base"]["min"], 0.143)
        self.assertEqual(m["removal"]["cand"]["min"], 0.164)
        self.assertAlmostEqual(m["fmax_geomean"]["base"]["mean"], 78.85, places=2)
        self.assertAlmostEqual(m["fmax_geomean"]["cand"]["mean"], 78.61, places=2)
        self.assertEqual(round(m["alms"]["base"]["mean"]), 35116)
        self.assertEqual(round(m["alms"]["cand"]["mean"]), 34939)

    def test_negative_hold_counts(self):
        recs = helpers.dse_records()
        neg = lambda v: sum(r["headline"]["hold"] < 0 for r in recs if r["variant"] == v)
        self.assertEqual((neg("baseline"), neg("candidate")), (5, 8))

    def test_pinned_p_values(self):
        # RNG pinned (stats.RNG_SEED); spec: setup ~0.29, hold ~0.47, f(MAX) ~0.61, ALMs < 0.001
        self.assertAlmostEqual(self.m["setup"]["p"], 0.28549, places=4)
        self.assertAlmostEqual(self.m["hold"]["p"], 0.47088, places=4)
        self.assertAlmostEqual(self.m["fmax_geomean"]["p"], 0.60502, places=4)
        self.assertLess(self.m["alms"]["p"], 0.001)

    def test_verdict(self):
        # recovery shifts (p ~ 0.04) but keeps > 2.5 ns of margin, so it is noted, not flagged
        self.assertEqual(self.res["verdict"], "No measurable regression")
        self.assertIn("note", self.m["recovery"])
        self.assertFalse(any(r["new_failing"] for r in self.res["clocks_setup"]))

    def test_seed_pick(self):
        s = self.res["seed"]
        self.assertEqual(s["best"], 18)
        self.assertTrue(s["best_met"])
        self.assertFalse(s["apply"])  # policy off
        cand = [r for r in helpers.dse_records() if r["variant"] == "candidate"]
        self.assertTrue(seedpick.decide(cand, 1, "if-failing")["apply"])
        self.assertFalse(seedpick.decide(cand, 4, "if-failing")["apply"])   # seed 4 already meets timing
        self.assertTrue(seedpick.decide(cand, 4, "always")["apply"])
        self.assertFalse(seedpick.decide(cand, 18, "always")["apply"])      # already best

    def test_thresholds(self):
        th = compare.parse_thresholds("max_met_rate_drop: 0.05  # ten percent\nforbid_new_failing_clock: true\n")
        self.assertEqual(th, {"max_met_rate_drop": 0.05, "forbid_new_failing_clock": True})
        res = compare.compare(helpers.merged(), th)
        self.assertEqual(len(res["thresholds"]["failures"]), 1)
        self.assertIn("timing-met rate", res["thresholds"]["failures"][0])
        self.assertTrue(compare.compare(helpers.merged(), {"bogus": 1.0})["thresholds"]["failures"])


if __name__ == "__main__":
    unittest.main()
