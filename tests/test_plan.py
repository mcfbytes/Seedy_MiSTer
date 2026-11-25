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

    def test_matrix_mixes_variants_in_every_job(self):
        m = plan.matrix([1, 2, 3, 4], 2, ["baseline", "candidate"])
        self.assertEqual(len(m["include"]), 2)
        self.assertEqual(m["include"][1], {"shard": 1, "work": "baseline=2,4;candidate=2,4",
                                           "label": "baseline 2,4 + candidate 2,4"})

    def test_split_work_covers_every_compile_once(self):
        seeds, vs = list(range(1, 32)), ["baseline", "candidate"]
        want = sorted((v, s) for v in vs for s in seeds)
        for jobs in (1, 2, 3, 7, 31, 32, 45, 62, 100, "max"):
            groups = plan.split_work(seeds, vs, jobs)
            self.assertEqual(sorted(x for g in groups for x in g), want, jobs)
            self.assertTrue(all(groups), jobs)  # no idle jobs
            sizes = [len(g) for g in groups]
            self.assertLessEqual(max(sizes) - min(sizes), 2, jobs)  # balanced
        self.assertEqual(len(plan.split_work(seeds, vs, "max")), 62)
        self.assertEqual(len(plan.split_work(seeds, vs, 100)), 62)
        # one job runs baseline and candidate of a seed back to back
        self.assertEqual(plan.split_work([1, 2], vs, 1), [[("baseline", 1), ("candidate", 1),
                                                           ("baseline", 2), ("candidate", 2)]])
        # a matrix holds at most 256 jobs
        self.assertEqual(len(plan.split_work(list(range(1, 201)), vs, "max")), plan.MAX_JOBS)

    def test_hunt_split_matches_round_robin(self):
        # a single-variant plan splits exactly as before, so hunts still try low seeds first everywhere
        groups = plan.split_work(list(range(1, 101)), ["candidate"], 10)
        self.assertEqual([s for _, s in groups[0]], list(range(1, 101, 10)))

    def test_work_roundtrip(self):
        items = plan.split_work([1, 2, 5, 9], ["baseline", "candidate"], 2)[0]
        self.assertEqual(plan.parse_work(plan.format_work(items)), items)
        self.assertEqual(plan.parse_work("candidate=3;baseline=1-3"),
                         [("baseline", 1), ("baseline", 2), ("candidate", 3), ("baseline", 3)])
        for bad in ("", "baseline", "Base=1", "baseline=1;baseline=2", "x y=1"):
            with self.assertRaises(ValueError):
                plan.parse_work(bad)

    def test_parse_jobs(self):
        vs = ["baseline", "candidate"]
        self.assertEqual(plan.parse_jobs("", 10, vs), 20)  # the older per-variant shards
        self.assertEqual(plan.parse_jobs("", 1, ["candidate"]), 1)
        self.assertEqual(plan.parse_jobs(" 7 ", 10, vs), 7)
        self.assertEqual(plan.parse_jobs("MAX", 10, vs), "max")
        for bad in ("0", "-1", "auto", "2.5"):
            with self.assertRaises(ValueError):
                plan.parse_jobs(bad, 10, vs)

    def test_cache_key_sensitivity(self):
        kw = dict(project="SNES", revision="SNES", baseline_sha="abc", image="img@sha256:1",
                  seeds=[1, 2], threads=4, build_epoch=1)
        k = plan.cache_key(**kw)
        self.assertEqual(k, plan.cache_key(**kw))
        for field, val in (("baseline_sha", "abd"), ("image", "img@sha256:2"), ("seeds", [1, 3]),
                           ("threads", 2), ("build_epoch", 2), ("npaths", 100)):
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

    def test_read_threads(self):
        self.assertEqual(quartus.read_threads("set_global_assignment -name NUM_PARALLEL_PROCESSORS all\n"), "ALL")
        self.assertEqual(quartus.read_threads("set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL\r\n"
                                              "set_global_assignment -name NUM_PARALLEL_PROCESSORS 8 # last wins\r\n"), "8")
        self.assertEqual(quartus.read_threads("set_global_assignment -name SEED 1\n"), "unset")

    def test_prepare_keeps_qsf_threads_unless_overridden(self):
        import os, tempfile
        d = tempfile.mkdtemp()
        q = os.path.join(d, "SNES.qsf")
        qsf = "set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL\nset_global_assignment -name SEED 1\n"
        files.write(q, qsf)
        info = quartus.prepare(d, "SNES", 7, 0, 1790000000)
        self.assertEqual((info["threads"], info["threads_override"]), ("ALL", False))
        self.assertEqual(files.read(q), qsf.replace("SEED 1", "SEED 7"))
        info = quartus.prepare(d, "SNES", 7, 4, 1790000000)
        self.assertEqual((info["threads"], info["threads_override"]), ("4", True))
        self.assertEqual(quartus.read_threads(files.read(q)), "4")

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
