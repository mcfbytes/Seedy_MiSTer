#!/usr/bin/env bash
# compile-shard.sh: compile one variant's shard of seeds in the Quartus container, one
# full `quartus_sh --flow compile` per seed, then seedy_sta.tcl, then parse to JSON records.
#
#   compile-shard.sh --src <ref.tar> --variant <name> --seeds 1,11,21 --out <dir> [options]
#
# Options (defaults in brackets): --project/--revision [auto] --image [theypsilon/quartus-lite-c5:17.0.2]
#   --concurrency [auto] --threads [4] --npaths [40] --watch-file [none] --build-epoch [ref tar mtime]
#   --keep-rbf none|all [none] --work [$RUNNER_TEMP or /tmp]/seedy-work --name [seedy-<variant>]
#   --peak-gb [7, RAM per compile for --concurrency auto] --timeout [4h per compile] --meta '<json merged into every record>'
# Hunt mode (hard-to-close cores): seeds are tried in the order given, and no new seed starts once
#   --stop-after-met K   K seeds of this shard have met timing, or
#   --deadline EPOCH     a new compile would likely run past this time (uses the slowest compile so far).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

SRC= VARIANT= SEEDS= OUT= PROJECT= REVISION= IMAGE=theypsilon/quartus-lite-c5:17.0.2
CONC=auto THREADS=4 NPATHS=40 WATCH= EPOCH= KEEP_RBF=none NAME= TIMEOUT=4h META='{}' STOP_MET=0 DEADLINE=0 PEAK_GB=7
WORK="${RUNNER_TEMP:-/tmp}/seedy-work"
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC=$2;; --variant) VARIANT=$2;; --seeds) SEEDS=$2;; --out) OUT=$2;;
    --project) PROJECT=$2;; --revision) REVISION=$2;; --image) IMAGE=$2;;
    --concurrency) CONC=$2;; --threads) THREADS=$2;; --npaths) NPATHS=$2;;
    --watch-file) WATCH=$2;; --build-epoch) EPOCH=$2;; --keep-rbf) KEEP_RBF=$2;;
    --work) WORK=$2;; --name) NAME=$2;; --timeout) TIMEOUT=$2;; --meta) META=$2;;
    --stop-after-met) STOP_MET=$2;; --deadline) DEADLINE=$2;; --peak-gb) PEAK_GB=$2;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
  shift 2
done
[ -n "$SRC" ] && [ -n "$VARIANT" ] && [ -n "$SEEDS" ] && [ -n "$OUT" ] || { echo "need --src --variant --seeds --out" >&2; exit 2; }
NAME=${NAME:-seedy-$VARIANT}
SRC=$(realpath "$SRC"); mkdir -p "$OUT/records" "$OUT/logs" "$WORK"; OUT=$(realpath "$OUT"); WORK=$(realpath "$WORK")
[ -n "$WATCH" ] && WATCH=$(realpath "$WATCH")

# project / revision / build date come from the source itself
probe="$WORK/$NAME-probe"; rm -rf "$probe"; mkdir -p "$probe"
tar -xf "$SRC" -C "$probe"
eval "$(python3 -m seedy find-project "$probe" --project "$PROJECT" --revision "$REVISION")"
PROJECT=$project REVISION=$revision
rm -rf "$probe"
EPOCH=${EPOCH:-$(stat -c %Y "$SRC")}
if [ "$CONC" = auto ]; then CONC=$(python3 -m seedy concurrency --threads "$THREADS" --peak-gb "$PEAK_GB"); fi
echo "seedy: $VARIANT seeds $SEEDS of $PROJECT/$REVISION, $CONC at a time x $THREADS threads, image $IMAGE"

CONTAINERS="$WORK/$NAME.containers"; : > "$CONTAINERS"
cleanup() {
  # stop exactly the containers this script started; never pattern-kill
  while read -r c; do [ -n "$c" ] && docker rm -f "$c" >/dev/null 2>&1 || true; done < "$CONTAINERS"
}
trap cleanup EXIT

run_seed() {
  local seed=$1 d="$WORK/$NAME-s$1" cname="$NAME-s$1" rc=0
  rm -rf "$d"; mkdir -p "$d"
  tar -xf "$SRC" -C "$d"
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
  local log="$d/compile.log"
  python3 -m seedy collect "$d" --revision "$REVISION" --seed "$seed" --variant "$VARIANT" \
    --meta "$(python3 -c 'import json,sys; m=json.loads(sys.argv[1]); m.update(image=sys.argv[2], wall_s=int(sys.argv[3])); print(json.dumps(m))' "$META" "$IMAGE" "$((SECONDS - t0))")" \
    --log "$log" --out "$OUT/records/$VARIANT-$seed.json"
  if [ -s "$d/mem.peak" ]; then
    python3 - "$OUT/records/$VARIANT-$seed.json" "$(cat "$d/mem.peak")" <<'PY'
import json, sys
p = sys.argv[1]; r = json.load(open(p)); r["cgroup_peak_bytes"] = int(sys.argv[2]); json.dump(r, open(p, "w"), indent=1, sort_keys=True)
PY
  fi
  for f in compile.log sta.log; do [ -f "$d/$f" ] && tail -c 20000 "$d/$f" > "$OUT/logs/$VARIANT-$seed-$f" || true; done
  if [ "$KEEP_RBF" = all ] && [ -f "$d/output_files/$REVISION.rbf" ]; then
    mkdir -p "$OUT/rbf"; cp "$d/output_files/$REVISION.rbf" "$OUT/rbf/$PROJECT-$VARIANT-seed$seed.rbf"
  fi
  rm -rf "$d"
  echo "seedy: $VARIANT seed $seed done in $((SECONDS - t0)) s (docker rc=$rc, quartus rc=$(cat "$OUT/records/$VARIANT-$seed.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'))"
}

met_so_far() {
  python3 - "$OUT/records" "$VARIANT" <<'PY'
import glob, json, os, sys
n = 0
for p in glob.glob(os.path.join(sys.argv[1], sys.argv[2] + "-*.json")):
    r = json.load(open(p))
    n += bool(r.get("status") == "ok" and r.get("headline", {}).get("timing_met"))
print(n)
PY
}
slowest=0   # seconds; the longest finished compile, for the deadline check
STATUS="$OUT/logs/shard-status-$VARIANT.txt"
stop_reason=""
should_stop() {
  if [ "$STOP_MET" -gt 0 ] && [ "$(met_so_far)" -ge "$STOP_MET" ]; then stop_reason="found $STOP_MET seed(s) meeting timing"; return 0; fi
  if [ "$DEADLINE" -gt 0 ]; then
    local s; s=$(python3 -c 'import glob,json,sys; print(max([json.load(open(p)).get("wall_s",0) for p in glob.glob(sys.argv[1]+"/*.json")] or [0]))' "$OUT/records")
    [ "$s" -gt "$slowest" ] && slowest=$s
    if [ $(( $(date +%s) + slowest )) -gt "$DEADLINE" ]; then stop_reason="time budget reached"; return 0; fi
  fi
  return 1
}

# a simple job pool: at most $CONC compiles in flight
pids=()
started=()
for seed in ${SEEDS//,/ }; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONC" ]; do wait -n || true; done
  if should_stop; then echo "seedy: $VARIANT stopping before seed $seed: $stop_reason"; break; fi
  run_seed "$seed" &
  pids+=($!)
  started+=("$seed")
done
[ -n "$stop_reason" ] || stop_reason="seed list exhausted"
echo "variant=$VARIANT started=${started[*]:-} stop=$stop_reason" >> "$STATUS"
fail=0
for p in "${pids[@]}"; do wait "$p" || fail=1; done
# a failed compile is data (status compile_failed); only a script error fails the shard
[ $fail -eq 0 ] || { echo "seedy: a seed's driver script failed" >&2; exit 1; }
