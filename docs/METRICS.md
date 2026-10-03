# What Seedy measures

Every number comes from Quartus's own reports, or from the timing analyzer itself (`quartus_sta -t
quartus/seedy_sta.tcl`), for **one full compile per seed**. Nothing is estimated.

## Headline columns (the #462 table)

| column | source | unit | notes |
|---|---|---|---|
| Quality of Fit | DSE summary | — | **DSE imports only.** Intel doesn't publish the formula, so Seedy doesn't invent one. Met points score ≥ 100 (e.g. 103.24), failing points ~0–3. Shown only when DSE CSVs are imported. |
| f(MAX) geomean | `get_clock_fmax_info`, every corner | MHz | geometric mean, over clocks, of each clock's **worst-corner** restricted f(MAX). This reproduces DSE's *f(MAX) Geomean* exactly (78.509 MHz on the fixture). The slow-100 °C corner alone doesn't. |
| WC slack: setup / hold / recovery / removal | `get_clock_domain_info -setup` etc. | ns | worst over all clocks, at the **corners the core's own timing report covers** (see below) |
| Total negative slack (TNS) | `get_clock_domain_info -setup` | ns | per clock the worst corner's setup TNS, summed over clocks; 0 when the seed closes. Compiles only. |
| Logic utilization | `<rev>.fit.summary` | ALMs | |
| Compilation time | `<rev>.flow.rpt`, *Flow Elapsed Time → Total* | hh:mm:ss | depends on runner load, so it's informational and never flagged |
| Timing met | all four WC slacks ≥ 0 | bool | DSE's definition, at the reported corners |

**Which corners.** Quartus can model the chip at four corners: slow silicon at 100 °C and −40 °C, and fast
silicon at both. MiSTer's `Template.qsf` sets `TIMEQUEST_MULTICORNER_ANALYSIS Off`, so a maintainer's own build
reports only the slow 100 °C corner, and that is the number they quote and release by. Seedy reads the setting
from each compile's `flow.rpt` and builds the headline from the same corners. It still analyses all four
(`seedy_sta.tcl`) and keeps the all-corner headline as `headline_all`. The comment notes seeds that fail hold only
at the corners the core's report leaves out. On SNES the difference is real: master closed on 12/30 seeds at slow
100 °C but 9/30 over all four corners. DSE imports always cover all four corners (that is how the #462 table was
made), so DSE numbers match `headline_all`, not the headline.

## Extended data (collapsible tables, `seeds.csv`, `per-clock.csv`, `paths.csv`, `merged.json`)

- **Per clock and per corner:** setup, hold, recovery and removal slack, plus **TNS** (total negative slack).
  Clock names stay full Quartus names in the data. Tables shorten them (`emu c2` = `emu|pll|…|counter[2]…`).
- **f(MAX) per clock and corner:** unrestricted and restricted.
- **Utilization:** ALMs, registers, pins, block memory bits, RAM blocks, DSP blocks and PLLs (`fit.summary`).
- **Runtime per module** and **peak virtual memory per module** (`flow.rpt`). The container's cgroup
  `memory.peak` is recorded as `cgroup_peak_bytes` when the kernel exposes it, and it is what to size
  `compile_peak_gb` by.
- **Paths:** the N worst setup and hold paths per corner (slack, from, to, launch and latch clock).
- **Watched registers:** for each `watch_registers` glob, the 10 worst setup and hold paths **from** and **to**
  the matching registers on every corner. A glob that matches nothing is reported as a warning, because an empty
  match would otherwise read as "clean".

Derived per seed:

- `failing_endpoints`: destination nodes of failing paths, with bus indices and `~DUPLICATE` suffixes removed.
- `watched_on_failing`: any watched-register path has negative slack.
- `watched_min_setup` / `watched_min_hold`: the worst slack of any path touching a watched register.

## Statistics

Fitter seeds are chaotic: seed 7 on master and seed 7 on the PR are unrelated draws. Seedy therefore treats each
variant as an **unpaired** sample.

| quantity | method |
|---|---|
| seeds meeting timing | counts; two-sided **Fisher exact** test |
| every headline metric | mean, median, min, max; two-sided **permutation test** on the difference of means (20,000 shuffles, RNG seed 20261002, so p is reproducible); **bootstrap 95 % CI** of the median difference |
| per-clock setup/hold | fail counts per clock per variant, Fisher p. A clock that **never** fails in the baseline but fails in the PR is a *new failing clock domain*. |
| failing endpoints | union over seeds per variant; families only the PR has are listed with seed counts, and flag only when they recur (Fisher p < 0.05) |
| shipped seed | the `.qsf`'s own `SEED`, always compiled and shown as its own row |

**Verdict.** *Possible regression* when any of these trips:

- a metric is worse with p < 0.05. Setup and hold count only if some PR seed falls below `slack_margin_ns`
  (default 0.5 ns); recovery and removal (reset timing, which reviewers ignore unless it fails) count only if
  some PR seed goes negative.
- fewer seeds meet timing with Fisher p < 0.05.
- more seeds have a hold violation, Fisher p < 0.05.
- a new failing clock domain appears.
- a new failing endpoint family recurs: it fails on no baseline seed and on enough PR seeds for Fisher p < 0.05
  (6 of 30). One or two seeds failing somewhere new is placement noise; those are listed but don't flag.
- a watched register is on a failing path, or a watch glob matched nothing.

**Needs a maintainer's eye.** Listed separately, whatever the statistics say, because MiSTer maintainers object
to these on sight: the PR adds or removes a clock (a new clock makes its paths asynchronous and can improve slack
by hiding real problems), changes the `.qsf` `SEED`, or edits files under `sys/` (the shared framework), `.sdc`
constraints or the `.qsf`. The workflow records the changed paths with `git diff --name-only`.

**Constraint health.** Slack only describes paths Quartus was told to check. Seedy reads the flow's
`<rev>.sta.rpt` for each compile and lists what the numbers do not cover:

| item | where Quartus reports it | why reviewers care |
|---|---|---|
| clocks with no constraint | `Warning (332060): Node: … was determined to be a clock but was found without an associated clock assignment` | usually a latch or a logic-made clock; its paths are not timed (SNES #471) |
| constraints that match nothing | `Warning (332049): Ignored set_false_path at sys_top.sdc(47): …` | a rename silently disables a constraint (Template_MiSTer #80) |
| combinational loops timed as latches | `Warning (335093)` | latches are hard to time and sorgelig rejects them |
| I/O pins with no timing constraint | *Unconstrained Input/Output Ports* panels | SDRAM pins without I/O constraints were never checked (MacLC #5) |
| `.sdc` files not read cleanly | *SDC File List* status | |

These come from synthesis and constraints, not placement, so they don't vary by seed; Seedy takes the union over
seeds. The framework leaves many HDMI, SD and LED pins unconstrained on purpose, so only what the PR **adds**
goes under *Needs a maintainer's eye*; the full counts are in the collapsed *Constraint health* table.

Otherwise the verdict is *No measurable regression*. It is never "safe": 30 seeds detect only large shifts (the
SNES run had 6/30 vs 3/30 seeds meeting timing, p = 0.47). About ten metrics are tested and the p-values are not
corrected; the comment says so.

## Thresholds (optional gating)

The default is report-only. `thresholds:` takes flat YAML; any failure turns the run red after the results are
uploaded.

| key | fails when |
|---|---|
| `max_median_setup_drop_ns` | median setup slack drops by more than this |
| `max_median_hold_drop_ns` | median hold slack drops by more than this |
| `max_met_rate_drop` | the timing-met rate drops by more than this fraction (e.g. `0.2`) |
| `max_alm_increase` | mean ALMs rise by more than this |
| `forbid_watched_on_failing` | `true`: a watched register is on a failing path |
| `forbid_new_failing_clock` | `true`: a new failing clock domain appears |
| `forbid_regression_verdict` | `true`: the verdict is *Possible regression* |
| `forbid_untimed_changes` | `true`: the PR adds an unconstrained clock, an ignored constraint, a latch loop, an unconstrained pin or an unreadable `.sdc` |
| `slack_margin_ns` | (tuning, not a gate) the margin below which slack shifts count; default 0.5 |

Unknown keys fail the run, so a typo can't silently disable a gate.

## Best-seed ranking

The ranking key, highest first: meets timing → worst of the four WC slacks → least total negative slack (all
clocks and corners) → setup slack → f(MAX) geomean → lower seed number.
