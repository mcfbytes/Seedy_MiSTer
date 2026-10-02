# Validation record

The method rests on three facts. Each one is checked here against real Quartus 17.0.2 Lite output.

## 1. One full compile per seed reproduces DSE exactly

Seedy compiles each seed with `quartus_sh --flow compile` after writing `SEED <n>` into the `.qsf`. The
2026-10-02 SNES fixture came from `quartus_dse --explore seed` instead. Both flows give identical results:

| run | flow | setup | hold | recovery | removal | ALMs | f(MAX) geomean | met |
|---|---|---|---|---|---|---|---|---|
| 75f10d3 seed 1 | DSE | −0.898 | +0.076 | +3.413 | +0.276 | 34,843 | 78.509 | no |
| 75f10d3 seed 1 | manual full compile, 32 threads | −0.898 | +0.076 | +3.413 | +0.276 | 34,843 | 78.509 | no |
| c61bfd4 seed 4 | DSE | +0.138 | +0.102 | +3.424 | +0.143 | 35,192 | 79.618 | yes |
| c61bfd4 seed 4 | Seedy `compile-shard.sh`, 4 threads | +0.138 | +0.102 | +3.424 | +0.143 | 35,192 | 79.618 | yes |
| 75f10d3 seed 18 | DSE | +0.182 | +0.078 | +2.539 | +0.305 | 34,943 | 79.353 | yes |
| 75f10d3 seed 18 | Seedy `compile-shard.sh`, 4 threads | +0.182 | +0.078 | +2.539 | +0.305 | 34,943 | 79.353 | yes |

The per-clock setup slacks of seed 1 match DSE's `multicorner_wcslack.csv` too. The test
`tests/test_parse.py::test_full_compile_matches_dse_point` locks this in.

**f(MAX) geomean.** DSE's number is the geometric mean over clocks of each clock's **worst-corner** f(MAX). The
slow-100 °C Fmax Summary in `sta.rpt` alone gives different per-clock values (e.g. FPGA_CLK1_50 88.74 vs DSE's
86.15 MHz, which is the slow −40 °C corner).

## 2. Determinism

- **Seed and project fixed, thread count varied:** the seed-1 full compile used `NUM_PARALLEL_PROCESSORS ALL`
  (32 threads), while DSE used 4. The results are identical (table above). Seedy still pins 4 threads for both
  variants.
- **Repeat runs:** seeds 4 and 18 were compiled again on 2026-10-02 with the build date pinned to the date of
  the original DSE run (`261002`). Every headline number matched the original. A different build date is a
  different design (it lands in the CONF_STR ROM), so Seedy pins it to the baseline commit's date for both
  variants. It has not been measured how often a date change alone moves a seed's result.

## 3. Capacity (measured, 2026-10-02, WSL2 VM with 32 threads and 31 GB)

| | seed 4 (baseline) | seed 18 (PR) |
|---|---|---|
| wall time, 4 threads, 2 compiles side by side | 21:18 | 20:32 |
| container cgroup `memory.peak` | 4.24 GiB | 4.43 GiB |
| Quartus's own "Peak Virtual Memory", Fitter | ~6.4 GB | ~6.4 GB |

`compile_peak_gb` defaults to 7: Quartus's virtual peak plus headroom, which is conservative against the
4.4 GiB resident peak. GitHub-hosted runner capacity has not been measured yet, so the end-to-end CI run is
still to do.

## Still open

- **End-to-end CI:** a run on GitHub (fork of SNES_MiSTer, `seed_count: 4`, `shards: 2`), the comment post, and
  the baseline cache hit on a re-run.
- **Hosted runner disk and time:** the free-disk step and `shards: 10` assume ~14 GB free and ~20 min per compile
  at 2 concurrent; both still need measuring.
- **Quartus versions other than 17.0.2:** the image digests are pinned, but those versions haven't been run here.
