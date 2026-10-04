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

Quartus is deterministic, but `NUM_PARALLEL_PROCESSORS` is an input to the fit, just like `SEED`. Measured
2026-10-04 on SNES `c61bfd4`, seed 1, build date pinned, Seedy's `prepare`, CPUs limited with `docker --cpuset-cpus`:

| run | `NUM_PARALLEL_PROCESSORS` | CPUs visible | Quartus says | `.rbf` sha256 | ALMs | setup | met |
|---|---|---|---|---|---|---|---|
| A | `16` | 32 | up to 16 | `f93f77fc…` | 35,045 | +0.065 | yes |
| B | `16` | 4 | up to 16 (warns) | `f93f77fc…` | 35,045 | +0.065 | yes |
| G | `16` (A repeated) | 32 | up to 16 | `f93f77fc…` | 35,045 | +0.065 | yes |
| C | `ALL` | 32 | 16 of 32 | `ec083578…` | 35,094 | −0.830 | no |
| D | `ALL` | 8 | 8 of 8 | `ec083578…` | 35,094 | −0.830 | no |
| E | `4` | 32 | up to 4 | `ec083578…` | 35,094 | −0.830 | no |
| — | `8` | 32 | up to 8 | (not kept) | 35,060 | +0.221 | yes |

- **Same settings, same bitstream:** A, B and G are byte-identical, as are C, D and E.
- **The CPU count changes nothing**, for an explicit number (A = B) and for `ALL` (C = D).
- **The setting's value changes the fit:** `ALL`, `8` and `16` are three different designs from one seed, and
  here seed 1 fails at `ALL` but meets timing at `8` and `16`.
- **`ALL` fits exactly like `4`** (C = E), even though `ALL` runs up to 16 threads (`min(CPUs, 16)`; Quartus 17
  caps every setting at 16). The 2026-10-02 runs agree: seed 1 of `75f10d3` at `ALL` matched DSE at 4 threads
  (table above). This has been seen on SNES only.
- **Unset behaves like `ALL`** ("16 of 32 processors detected" in a small test project).

So Seedy keeps each `.qsf`'s own `NUM_PARALLEL_PROCESSORS` (`threads_per_compile: 0`, the default since 1.2.0)
and every seed compiles exactly as the core's release build would. Up to 1.1.0 Seedy forced `4`, which per the
row above gave the same bitstreams as the `ALL` that MiSTer cores ship. Results from cores that pin some other
number were measured at the wrong setting.

The thread count costs memory: at `ALL` on 32 CPUs a compile peaked at 6.4 GiB (cgroup), against 4.7 GiB at
`ALL` on 8 CPUs.

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

- **`ALL` on fewer than 4 CPUs** (2-vCPU runners): `ALL` then runs 2 threads; untested whether it still fits like `4`.

- **End-to-end CI:** a run on GitHub (fork of SNES_MiSTer, `seed_count: 4`, `shards: 2`), the comment post, and
  the baseline cache hit on a re-run.
- **Hosted runner disk and time:** the free-disk step and `shards: 10` assume ~14 GB free and ~20 min per compile
  at 2 concurrent; both still need measuring.
- **Quartus versions other than 17.0.2:** the image digests are pinned, but those versions haven't been run here.
