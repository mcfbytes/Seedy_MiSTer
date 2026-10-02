import unittest

from seedy import files, plan, quartus


class PlanTest(unittest.TestCase):
    def test_parse_seeds(self):
        self.assertEqual(plan.parse_seeds("1-3,7, 5"), [1, 2, 3, 5, 7])
        self.assertEqual(plan.parse_seeds("1-30"), list(range(1, 31)))
        for bad in ("", "0", "5-3", "x"):
            with self.assertRaises(ValueError):
                plan.parse_seeds(bad)

    def test_format_roundtrip(self):
        self.assertEqual(plan.format_seeds([1, 2, 3, 5, 7, 8]), "1-3,5,7-8")
        self.assertEqual(plan.parse_seeds(plan.format_seeds([4, 9, 10])), [4, 9, 10])

    def test_shard_round_robin_covers_all(self):
        seeds = list(range(1, 31))
        shards = plan.shard(seeds, 10)
        self.assertEqual(len(shards), 10)
        self.assertEqual(sorted(s for sh in shards for s in sh), seeds)
        self.assertEqual(shards[0], [1, 11, 21])
        self.assertEqual(len(plan.shard([1, 2], 10)), 2)  # no empty shards

    def test_matrix(self):
        m = plan.matrix([1, 2, 3, 4], 2, ["baseline", "candidate"])
        self.assertEqual(len(m["include"]), 4)
        self.assertEqual(m["include"][1], {"variant": "baseline", "shard": 1, "seeds": "2,4"})

    def test_cache_key_sensitivity(self):
        kw = dict(project="SNES", revision="SNES", baseline_sha="abc", image="img@sha256:1",
                  seeds=[1, 2], threads=4, build_epoch=1)
        k = plan.cache_key(**kw)
        self.assertEqual(k, plan.cache_key(**kw))
        for field, val in (("baseline_sha", "abd"), ("image", "img@sha256:2"), ("seeds", [1, 3]),
                           ("threads", 2), ("build_epoch", 2)):
            self.assertNotEqual(k, plan.cache_key(**dict(kw, **{field: val})), field)


class QsfTest(unittest.TestCase):
    def test_set_seed_in_place_crlf(self):
        t = "a\r\nset_global_assignment -name SEED 1\r\nb\r\n"
        self.assertEqual(quartus.set_seed(t, 18), "a\r\nset_global_assignment -name SEED 18\r\nb\r\n")
        self.assertEqual(quartus.read_seed(quartus.set_seed(t, 18)), 18)

    def test_set_seed_duplicates_and_append(self):
        t = "x\nset_global_assignment -name SEED 3\nset_global_assignment -name SEED 4\ny\n"
        self.assertEqual(quartus.read_seed(t), 4)
        self.assertEqual(quartus.set_seed(t, 7), "x\nset_global_assignment -name SEED 7\ny\n")
        self.assertEqual(quartus.set_seed("x\n", 7), "x\nset_global_assignment -name SEED 7\n")
        self.assertEqual(quartus.read_seed("x\n"), 1)

    def test_set_threads(self):
        t = "a\nset_global_assignment -name NUM_PARALLEL_PROCESSORS ALL\nb\n"
        self.assertEqual(quartus.set_threads(t, 4), "a\nb\nset_global_assignment -name NUM_PARALLEL_PROCESSORS 4\n")

    def test_pin_build_date(self):
        import os, tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "sys"))
        files.write(os.path.join(d, "sys", "build_id.tcl"),
                    'set buildDate "`define BUILD_DATE \\"[clock format [ clock seconds ] -format %y%m%d]\\""\n')
        self.assertEqual(quartus.pin_build_date(d, 1790000000), [os.path.join("sys", "build_id.tcl")])
        self.assertIn("[clock format 1790000000 -format", files.read(os.path.join(d, "sys", "build_id.tcl")))


if __name__ == "__main__":
    unittest.main()
