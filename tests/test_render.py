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
        for row in ("Seeds meeting timing | 6/30 | 3/30 (Fisher p = 0.47)",
                    "−0.469 / −0.403 ns | −0.341 / −0.275 ns (p = 0.29)",
                    "Seeds with negative hold | 5 (worst −0.382) | 8 (worst −0.328)",
                    "WC slack: recovery, worst | +3.223 | +2.539",
                    "f(MAX) geomean, mean | 78.85 MHz | 78.61 MHz",
                    "35,116 ALMs | 34,939 ALMs (p < 0.001)",
                    "Shipped seed (1) setup / hold | −0.515 / +0.021 | −0.898 / +0.076",
                    "No measurable regression", "Recommended seed for hardware testing: 18"):
            self.assertIn(row, c)
        self.assertIn("<details><summary>Per-seed table (60 rows)", c)
        self.assertIn("<details><summary>Per-clock setup slack", c)

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

    def test_csv_outputs(self):
        recs = helpers.dse_records()
        self.assertEqual(render.seeds_csv(recs).count("\n"), 61)
        self.assertIn("variant,seed,corner,kind,clock", render.per_clock_csv(recs))


if __name__ == "__main__":
    unittest.main()
