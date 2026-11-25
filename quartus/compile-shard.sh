#!/usr/bin/env bash
# compile-shard.sh: compile one shard of seeds in the Quartus container, one full
# `quartus_sh --flow compile` per seed, then seedy_sta.tcl, then parse to JSON records.
#
#   compile-shard.sh --src <ref.tar> --variant <name> --seeds 1,11,21 --out <dir> [options]
#   compile-shard.sh --src baseline=<a.tar> --src candidate=<b.tar> \
#                    --items 'baseline=1,11;candidate=1,11' --out <dir> [options]
#
# The second form mixes variants in one pool, seed by seed (baseline 1, candidate 1, baseline 11, ...),
# so both share the machine and finish together. --sha <variant>=<sha> records each variant's commit.
#
# Options (defaults in brackets): --project/--revision [auto] --image [theypsilon/quartus-lite-c5:17.0.2]
#   --concurrency [auto] --threads [0: keep the .qsf's NUM_PARALLEL_PROCESSORS] --npaths [40] --watch-file [none] --build-epoch [ref tar mtime]
#   --keep-rbf none|all [none] --keep-reports yes|no [no] --work [$RUNNER_TEMP/seedy-work, else next to --out] --name [seedy-shard] --sha <variant>=<sha> (repeatable)
#   --peak-gb [7, RAM per compile for --concurrency auto] --timeout [4h per compile] --meta '<json merged into every record>'
#   --slots [$SEEDY_SLOTS, else 0] --slot-dir [$SEEDY_SLOT_DIR, else /var/tmp/seedy-slots]
# Machine-wide limit: with --slots N (or SEEDY_SLOTS=N in the runner's environment), a compile starts only
#   while it holds one of N lock files in the slot dir, so every Seedy job on the machine (several runner
#   instances, overlapping runs) shares one budget of N compiles. --concurrency auto then means N.
# Hunt mode (hard-to-close cores): seeds are tried in the order given, and no new seed starts once
#   --stop-after-met K   K seeds of this shard have met timing, or
#   --deadline EPOCH     a new compile would likely run past this time (uses the slowest compile so far).
#   --stop-variant V     count only V's seeds toward --stop-after-met (default: every variant).
#   --first 'v:s,...'    compile these first, in this order, and never skip them for a stop (hunt references).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

SRC_ARGS=() SHA_ARGS=() FIRST= STOP_VARIANT= WORK_SPEC= VARIANT= SEEDS= OUT= PROJECT= REVISION= IMAGE=theypsilon/quartus-lite-c5:17.0.2
CONC=auto THREADS=0 NPATHS=40 WATCH= EPOCH= KEEP_RBF=none KEEP_REPORTS=no NAME= TIMEOUT=4h META='{}' STOP_MET=0 DEADLINE=0 PEAK_GB=7
WORK= SLOTS=${SEEDY_SLOTS:-0} SLOT_DIR=${SEEDY_SLOT_DIR:-/var/tmp/seedy-slots}
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC_ARGS+=("$2");; --sha) SHA_ARGS+=("$2");; --items) WORK_SPEC=$2;;
    --first) FIRST=$2;; --stop-variant) STOP_VARIANT=$2;; --slots) SLOTS=$2;; --slot-dir) SLOT_DIR=$2;; --variant) VARIANT=$2;; --seeds) SEEDS=$2;; --out) OUT=$2;;
    --project) PROJECT=$2;; --revision) REVISION=$2;; --image) IMAGE=$2;;
    --concurrency) CONC=$2;; --threads) THREADS=$2;; --npaths) NPATHS=$2;;
    --watch-file) WATCH=$2;; --build-epoch) EPOCH=$2;; --keep-rbf) KEEP_RBF=$2;; --keep-reports) KEEP_REPORTS=$2;;
    --work) WORK=$2;; --name) NAME=$2;; --timeout) TIMEOUT=$2;; --meta) META=$2;;
    --stop-after-met) STOP_MET=$2;; --deadline) DEADLINE=$2;; --peak-gb) PEAK_GB=$2;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
  shift 2
done
die() { echo "compile-shard.sh: $*" >&2; exit 2; }
[ ${#SRC_ARGS[@]} -gt 0 ] && [ -n "$OUT" ] || die "need --src and --out"
if [ -z "$WORK_SPEC" ]; then
  [ -n "$VARIANT" ] && [ -n "$SEEDS" ] || die "need --items, or --variant and --seeds"
  WORK_SPEC="$VARIANT=$SEEDS"
fi
[[ "$SLOTS" =~ ^[0-9]+$ ]] || die "--slots must be a number"
declare -A SRC=() SHA=()
for a in "${SRC_ARGS[@]}"; do
  if [[ "$a" =~ ^([a-z]+)=(.+)$ ]]; then SRC[${BASH_REMATCH[1]}]=${BASH_REMATCH[2]}
  elif [ -n "$VARIANT" ] && [ ${#SRC_ARGS[@]} -eq 1 ]; then SRC[$VARIANT]=$a
  else die "with several variants, give each source as --src <variant>=<tar>"; fi
done
for a in "${SHA_ARGS[@]}"; do [[ "$a" =~ ^([a-z]+)=([0-9a-f]+)$ ]] || die "bad --sha $a"; SHA[${BASH_REMATCH[1]}]=${BASH_REMATCH[2]}; done
NAME=${NAME:-seedy-shard}
# never default to /tmp: each in-flight seed needs ~1-2 GB, and /tmp is often a small shared tmpfs
mkdir -p "$OUT/records" "$OUT/logs"; OUT=$(realpath "$OUT")
WORK=${WORK:-${RUNNER_TEMP:+$RUNNER_TEMP/seedy-work}}; WORK=${WORK:-$OUT/../seedy-work}
mkdir -p "$WORK"; WORK=$(realpath "$WORK")
# one "variant seed first|-" line per compile, in run order
ITEMS=$(python3 -m seedy expand-work "$WORK_SPEC" --first "$FIRST")
VARIANTS=$(awk '!seen[$1]++ {print $1}' <<<"$ITEMS")
[ -n "$WATCH" ] && WATCH=$(realpath "$WATCH")

# project / revision / build date come from the sources themselves; every variant must have the same one
for v in $VARIANTS; do
  [ -n "${SRC[$v]:-}" ] || die "no --src for variant $v"
  SRC[$v]=$(realpath "${SRC[$v]}")
  probe="$WORK/$NAME-probe"; rm -rf "$probe"; mkdir -p "$probe"
  tar -xf "${SRC[$v]}" -C "$probe"
  eval "$(python3 -m seedy find-project "$probe" --project "$PROJECT" --revision "$REVISION")"
  PROJECT=$project REVISION=$revision
  rm -rf "$probe"
  EPOCH=${EPOCH:-$(stat -c %Y "${SRC[$v]}")}
done
if [ "$SLOTS" -gt 0 ]; then
  command -v flock >/dev/null || die "--slots needs flock (util-linux)"
  mkdir -p "$SLOT_DIR" && chmod 1777 "$SLOT_DIR" 2>/dev/null || true
  [ -w "$SLOT_DIR" ] || die "slot dir $SLOT_DIR is not writable"
fi
if [ "$CONC" = auto ]; then
  if [ "$SLOTS" -gt 0 ]; then CONC=$SLOTS   # the slots already hold the machine's budget
  else CONC=$(python3 -m seedy concurrency --threads "$THREADS" --peak-gb "$PEAK_GB"); fi
fi
THREADS_TEXT="NUM_PARALLEL_PROCESSORS $THREADS (override)"; [ "$THREADS" = 0 ] && THREADS_TEXT="the .qsf's NUM_PARALLEL_PROCESSORS"
SLOTS_TEXT=""; [ "$SLOTS" -gt 0 ] && SLOTS_TEXT=", sharing $SLOTS machine-wide slots in $SLOT_DIR"
echo "seedy: $(echo $WORK_SPEC | tr ';' ' ') of $PROJECT/$REVISION, $CONC at a time$SLOTS_TEXT, $THREADS_TEXT, image $IMAGE"

CONTAINERS="$WORK/$NAME.containers"; : > "$CONTAINERS"
cleanup() {
  # stop exactly the containers this script started; never pattern-kill
  while read -r c; do [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1 || true; done < "$CONTAINERS"
}
trap cleanup EXIT

# one machine-wide compile slot: an exclusive flock on one of $SLOTS files, held through an inherited
# fd. The parent takes it before forking run_seed and closes its own copy; the child holds it until its
# container exits. A killed job closes its fds, so a slot is never left taken.
SLOT_FD=
acquire_slot() {
  [ "$SLOTS" -gt 0 ] || return 0
  local i f told=0
  while :; do
    for ((i = 0; i < SLOTS; i++)); do
      f="$SLOT_DIR/slot-$i"
      [ -e "$f" ] || { : >> "$f" && chmod 0666 "$f"; } 2>/dev/null || true
      [ -r "$f" ] || continue
      exec {SLOT_FD}<"$f"
      flock -n -x "$SLOT_FD" && return 0
      exec {SLOT_FD}<&-; SLOT_FD=
    done
    [ $told -eq 1 ] || { echo "seedy: all $SLOTS machine-wide compile slots are busy; waiting"; told=1; }
    sleep $((10 + RANDOM % 10))
  done
}
release_slot() { if [ -n "$SLOT_FD" ]; then exec {SLOT_FD}<&-; SLOT_FD=; fi; }

run_seed() {
  local variant=$1 seed=$2 d="$WORK/$NAME-$1-s$2" cname="$NAME-$1-s$2" rc=0 meta
  rm -rf "$d"; mkdir -p "$d"
  tar -xf "${SRC[$variant]}" -C "$d"
  python3 -m seedy prepare "$d" --revision "$REVISION" --seed "$seed" --threads "$THREADS" --build-epoch "$EPOCH" > "$d/seedy-prepare.json"
  cp "$HERE/seedy_sta.tcl" "$d/"
  [ -n "$WATCH" ] && cp "$WATCH" "$d/seedy-watch.txt" || : > "$d/seedy-watch.txt"
  echo "$cname" >> "$CONTAINERS"
  local t0=$SECONDS
  docker run --rm --name "$cname" -u "$(id -u):$(id -g)" -e HOME=/tmp -v "$d:/build" -w /build "$IMAGE" sh -c "
      timeout $TIMEOUT quartus_sh --flow compile '$PROJECT' -c '$REVISION' > compile.log 2>&1; rc=\$?; echo \$rc > compile.rc
      if [ \$rc -eq 0 ]; then
        timeout 1h quartus_sta -t seedy_sta.tcl '$PROJECT' '$REVISION' sta.tsv $NPATHS seedy-watch.txt > sta.log 2>&1 || rm -f sta.tsv
      fi
      cat /sys/fs/cgroup/memory.peak > mem.peak 2>/dev/null || true" || rc=$?
  release_slot   # parsing and archiving below need little; let the next compile on this machine start
  local log="$d/compile.log" peak=0 rec="$OUT/records/$variant-$seed.json"
  meta=$(python3 -c 'import json,sys; m=json.loads(sys.argv[1]); m.update({"sha": sys.argv[2]} if sys.argv[2] else {}); print(json.dumps(m))' "$META" "${SHA[$variant]:-}")
  [ -s "$d/mem.peak" ] && peak=$(tr -dc 0-9 < "$d/mem.peak")
  # written to a temp name and renamed, so the stop checks below never read a half-written record
  python3 -m seedy collect "$d" --revision "$REVISION" --seed "$seed" --variant "$variant" \
    --meta "$(python3 -c 'import json,sys; m=json.loads(sys.argv[1]); p=json.load(open(sys.argv[5])); m.update(image=sys.argv[2], wall_s=int(sys.argv[3]), cgroup_peak_bytes=int(sys.argv[4] or 0), threads=p["threads"], threads_override=p["threads_override"]); print(json.dumps(m))' "$meta" "$IMAGE" "$((SECONDS - t0))" "$peak" "$d/seedy-prepare.json")" \
    --log "$log" --out "$rec.tmp"
  mv "$rec.tmp" "$rec"
  for f in compile.log sta.log; do [ -f "$d/$f" ] && tail -c 20000 "$d/$f" > "$OUT/logs/$variant-$seed-$f" || true; done
  if [ "$KEEP_REPORTS" = yes ]; then
    # full logs and every Quartus text report, so a run can be re-examined (or re-parsed) later;
    # text compresses ~20x with xz. Best effort: a failure here never fails the compile.
    mkdir -p "$OUT/reports"
    local files=() z=J ext=xz
    command -v xz >/dev/null || { z=z; ext=gz; }
    while IFS= read -r f; do files+=("$f"); done < <(cd "$d" && find . -maxdepth 2 -type f \
      \( -name '*.log' -o -name 'sta.tsv' -o -name 'compile.rc' -o -name 'mem.peak' \
         -o -path './output_files/*' \( -name '*.rpt' -o -name '*.summary' -o -name '*.smsg' -o -name '*.pin' \) \) | sort)
    [ ${#files[@]} -gt 0 ] && XZ_OPT=-6 tar -c${z}f "$OUT/reports/$PROJECT-$variant-seed$seed.tar.$ext" -C "$d" \
      --transform "s,^\./,$variant-seed$seed/," -- "${files[@]}" \
      || echo "seedy: warning: could not archive the reports of $variant seed $seed" >&2
  fi
  if [ "$KEEP_RBF" = all ] && [ -f "$d/output_files/$REVISION.rbf" ]; then
    mkdir -p "$OUT/rbf"; cp "$d/output_files/$REVISION.rbf" "$OUT/rbf/$PROJECT-$variant-seed$seed.rbf"
  fi
  rm -rf "$d"
  echo "seedy: $variant seed $seed done in $((SECONDS - t0)) s (docker rc=$rc, $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["status"])' "$rec"))"
}

progress() {   # "<seeds meeting timing> <slowest compile in s>" over this shard's finished records
  python3 - "$OUT/records" "$STOP_VARIANT" <<'PY'
import glob, json, os, sys
met = slowest = 0
for p in glob.glob(os.path.join(sys.argv[1], (sys.argv[2] or "*") + "-*.json")):
    try:
        with open(p) as fh:
            r = json.load(fh)
    except (OSError, ValueError):
        continue
    met += bool(r.get("status") == "ok" and r.get("headline", {}).get("timing_met"))
    slowest = max(slowest, int(r.get("wall_s") or 0))
print(met, slowest)
PY
}
STATUS="$OUT/logs/shard-status-$NAME.txt"
stop_reason=""
should_stop() {
  [ "$STOP_MET" -gt 0 ] || [ "$DEADLINE" -gt 0 ] || return 1
  local met slowest
  read -r met slowest < <(progress)
  if [ "$STOP_MET" -gt 0 ] && [ "$met" -ge "$STOP_MET" ]; then stop_reason="found $STOP_MET seed(s) meeting timing"; return 0; fi
  if [ "$DEADLINE" -gt 0 ] && [ $(( $(date +%s) + slowest )) -gt "$DEADLINE" ]; then stop_reason="time budget reached"; return 0; fi
  return 1
}

# a simple job pool: at most $CONC compiles in flight here, and (with slots) on the whole machine
pids=()
started=()
single=$([ "$(wc -w <<<"$VARIANTS")" -eq 1 ] && echo yes || echo no)
while read -r variant seed first; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do wait -n || true; done
  acquire_slot
  if [ "$first" != first ] && should_stop; then release_slot; echo "seedy: stopping before $variant seed $seed: $stop_reason"; break; fi
  run_seed "$variant" "$seed" &
  pids+=($!)
  release_slot   # the child holds the slot now
  if [ "$single" = yes ]; then started+=("$seed"); else started+=("$variant:$seed"); fi
done <<<"$ITEMS"
[ -n "$stop_reason" ] || stop_reason="seed list exhausted"
echo "variant=$(paste -sd, <<<"$VARIANTS") started=${started[*]:-} stop=$stop_reason" >> "$STATUS"
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
# a failed compile is data (status compile_failed); only a script error fails the shard
[ $fail -eq 0 ] || { echo "seedy: a seed's driver script failed" >&2; exit 1; }
