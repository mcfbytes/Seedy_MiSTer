#!/usr/bin/env bash
# seedy-runner-agent.sh: run GitHub Actions jobs on this VM, then delete the VM.
#
#   seedy-runner-agent.sh run           seedy-runner.service, at boot
#   seedy-runner-agent.sh self-delete   seedy-runner-watchdog.timer (max lifetime) and failed provisioning
#
# Each job gets its own just-in-time (JIT) runner registration, so nothing on the VM can register more
# runners later. The GitHub credential (a fine-grained PAT, or a GitHub App's private key) stays in Key
# Vault; the VM reads it with its managed identity, which job steps and containers are firewalled from.
# The VM deletes itself after MAX_JOBS jobs, or once it has waited IDLE_MINUTES without getting one.
set -euo pipefail

CONFIG=${SEEDY_RUNNER_CONFIG:-/etc/seedy-runner/config.env}
# shellcheck source=/dev/null
. "$CONFIG"
: "${GITHUB_SCOPE:?}" "${KEY_VAULT_NAME:?}" "${IDENTITY_CLIENT_ID:?}"
GITHUB_API=${GITHUB_API:-https://api.github.com}
GITHUB_APP_ID=${GITHUB_APP_ID:-}
GITHUB_APP_INSTALLATION_ID=${GITHUB_APP_INSTALLATION_ID:-}
RUNNER_LABELS=${RUNNER_LABELS:-seedy-azure}
RUNNER_GROUP_ID=${RUNNER_GROUP_ID:-1}
IDLE_MINUTES=${IDLE_MINUTES:-10}
MAX_JOBS=${MAX_JOBS:-1}
IMDS=http://169.254.169.254/metadata
RUNNER_HOME=/home/runner/actions-runner

log() { echo "seedy-runner: $*"; }

imds_token() {  # $1: resource
  curl -fsS --retry 5 --retry-all-errors --noproxy '*' -H Metadata:true \
    "$IMDS/identity/oauth2/token?api-version=2018-02-01&client_id=$IDENTITY_CLIENT_ID&resource=$1" | jq -er .access_token
}

kv_secret() {  # $1: secret name
  local token
  token=$(imds_token https://vault.azure.net) || return 1
  curl -fsS --retry 3 -H "Authorization: Bearer $token" \
    "https://$KEY_VAULT_NAME.vault.azure.net/secrets/$1?api-version=7.4" | jq -er .value
}

scope_path() { case $GITHUB_SCOPE in */*) echo "repos/$GITHUB_SCOPE" ;; *) echo "orgs/$GITHUB_SCOPE" ;; esac; }

gh_api() {  # $1: method, $2: path, [$3: JSON body]; uses $GH_TOKEN; fails on HTTP errors
  local args=(-fsS -X "$1" -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28")
  if [ $# -ge 3 ]; then args+=(-H "Content-Type: application/json" -d "$3"); fi
  curl "${args[@]}" "$GITHUB_API/$2"
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

app_jwt() {
  local key now header payload sig
  key=$(mktemp /run/seedy-app-key.XXXXXX)
  if ! kv_secret github-app-private-key > "$key"; then rm -f "$key"; return 1; fi
  now=$(date +%s)
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$GITHUB_APP_ID" | b64url)
  sig=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -binary -sign "$key" | b64url)
  rm -f "$key"
  [ -n "$sig" ] && echo "$header.$payload.$sig"
}

github_token() {
  if [ -z "$GITHUB_APP_ID" ]; then kv_secret github-pat; return; fi
  local GH_TOKEN inst=$GITHUB_APP_INSTALLATION_ID
  GH_TOKEN=$(app_jwt) || return 1
  if [ -z "$inst" ]; then inst=$(gh_api GET "$(scope_path)/installation" | jq -er .id) || return 1; fi
  gh_api POST "app/installations/$inst/access_tokens" | jq -er .token
}

block_imds() {
  # Job steps run as `runner`, Quartus in Docker containers: neither may use the VM's managed identity.
  # Defence in depth only: `runner` is in the docker group, so a malicious workflow step could get root.
  iptables -C OUTPUT -d 169.254.169.254 -m owner --uid-owner runner -j REJECT 2>/dev/null ||
    iptables -I OUTPUT -d 169.254.169.254 -m owner --uid-owner runner -j REJECT
  iptables -N DOCKER-USER 2>/dev/null || true
  iptables -C DOCKER-USER -d 169.254.169.254 -j REJECT 2>/dev/null ||
    iptables -I DOCKER-USER -d 169.254.169.254 -j REJECT
}

# Register a JIT runner and run it. Returns 0 after a job, 1 when it idled out, 2 on an error.
run_one_job() {
  local n=$1 GH_TOKEN name body resp runner_id jit pid busy=0 t0
  if ! GH_TOKEN=$(github_token); then log "no GitHub credential (Key Vault $KEY_VAULT_NAME)"; return 2; fi
  name="$(hostname)-$n"
  body=$(jq -nc --arg name "$name" --argjson group "$RUNNER_GROUP_ID" --arg labels "$RUNNER_LABELS" \
    '{name: $name, runner_group_id: $group, work_folder: "_work",
      labels: (["self-hosted", "linux", "x64"] + ($labels | split(",") | map(select(length > 0))))}')
  if ! resp=$(gh_api POST "$(scope_path)/actions/runners/generate-jitconfig" "$body"); then
    log "could not register a runner with $GITHUB_SCOPE"; return 2
  fi
  runner_id=$(jq -er .runner.id <<<"$resp") && jit=$(jq -er .encoded_jit_config <<<"$resp") || return 2

  rm -rf "$RUNNER_HOME" && cp -a /opt/actions-runner "$RUNNER_HOME" && chown -R runner:runner "$RUNNER_HOME" || return 2
  log "runner $name (id $runner_id) is waiting for a job with labels $RUNNER_LABELS"
  # own session, so an idle runner and everything it started can be stopped together
  # shellcheck disable=SC2016 # $1 and $2 expand in the inner shell
  setsid runuser -u runner -- bash -c 'cd "$1" && exec ./run.sh --jitconfig "$2"' _ "$RUNNER_HOME" "$jit" &
  pid=$!
  t0=$SECONDS
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$busy" = 0 ] && pgrep -u runner -f Runner.Worker >/dev/null; then busy=1; log "job started"; fi
    if [ "$busy" = 0 ] && [ $((SECONDS - t0)) -ge $((IDLE_MINUTES * 60)) ]; then
      # GitHub refuses to remove a runner it is handing a job to, so no job is lost in between
      if GH_TOKEN=$(github_token) && gh_api DELETE "$(scope_path)/actions/runners/$runner_id" >/dev/null; then
        log "no job in $IDLE_MINUTES min; unregistered"
        kill -TERM -- "-$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        return 1
      fi
    fi
    sleep 5
  done
  wait "$pid" || log "runner exited with status $?"
  return 0
}

run_jobs() {
  block_imds || log "WARNING: could not firewall the managed-identity endpoint from jobs"
  local n=0 rc
  while [ "$n" -lt "$MAX_JOBS" ]; do
    n=$((n + 1))
    rc=0; run_one_job "$n" || rc=$?
    [ "$rc" = 0 ] || break
    # leftovers of a cancelled job must not run into the next one
    docker ps -aq | xargs -r docker rm -f >/dev/null 2>&1 || true
  done
}

self_delete() {
  local meta sub rg vmss name token base
  until meta=$(curl -fsS --retry 10 --retry-all-errors --noproxy '*' -H Metadata:true "$IMDS/instance/compute?api-version=2021-02-01"); do
    sleep 30
  done
  sub=$(jq -r .subscriptionId <<<"$meta"); rg=$(jq -r .resourceGroupName <<<"$meta")
  vmss=$(jq -r .vmScaleSetName <<<"$meta"); name=$(jq -r .name <<<"$meta")
  base="https://management.azure.com/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.Compute"
  log "deleting this VM ($name) from scale set $vmss"
  # keep trying: a VM that only shuts down is still billed
  while :; do
    if token=$(imds_token https://management.azure.com/); then
      if curl -fsS -X POST -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
          -d "{\"instanceIds\": [\"$name\"]}" "$base/virtualMachineScaleSets/$vmss/delete?api-version=2024-07-01" >/dev/null ||
        curl -fsS -X DELETE -H "Authorization: Bearer $token" "$base/virtualMachines/$name?api-version=2024-07-01" >/dev/null; then
        log "delete accepted"
        sleep 600
      fi
    fi
    sleep 30
  done
}

case "${1:-run}" in
  # however run_jobs ends, even on an unexpected error, the VM goes: an idle VM still bills
  run) trap self_delete EXIT; run_jobs ;;
  self-delete) self_delete ;;
  *) echo "usage: $0 [run|self-delete]" >&2; exit 2 ;;
esac
