#!/bin/bash
# upgrade-validate.sh
#
# Runs the standard six-test TDD validation suite against a service.
# Designed to be re-run before AND after an upgrade — same exit code,
# same output shape — so you can diff or just compare visually.
#
# === AI/AGENT USAGE METADATA (read me first) ===
#
#   purpose       : Health-check a service via a fixed 6-test suite. The
#                   tests are deliberately uniform so you run them BEFORE
#                   and AFTER an upgrade with identical output shape and
#                   compare. If they pass before and pass after, the
#                   upgrade did not regress the basic invariants.
#
#   when_to_use   : - Step 6 of the seven-step upgrade process
#                     (architecture/upgrade-playbook.md). Run twice:
#                       --label baseline  (before changing anything)
#                       --label post       (after the chart bump syncs)
#                   - Spot-check a service's general health any time.
#                     The script is read-only and idempotent.
#
#   when_not_to_use:
#                 : - As the *only* sign-off on an upgrade. T1..T5 cover
#                     the 'is it serving requests' surface. They do NOT
#                     verify functional correctness (e.g. logging in,
#                     reading a secret, pushing an image). Pair with an
#                     app-specific functional smoke test.
#                   - For services that don't expose an HTTP health
#                     endpoint. T3 will fail; either pass --probe-path
#                     to a different endpoint, or skip with a wrapper.
#                   - For services without a kubernetes Deployment (e.g.
#                     StatefulSet-based databases). T2 will fail. v2
#                     could generalize but doesn't yet.
#
#   input         : Three positional args:
#                     <argo-app>     - ArgoCD Application name (in argocd ns).
#                     <namespace>    - Where the Deployment lives.
#                     <deployment>   - Deployment name to validate.
#                   Options:
#                     --label <name>            tag printed in output (no
#                                               semantic effect).
#                     --probe-path <path>       HTTP path for T3
#                                               (default: /api/status).
#                     --service <name>          Service name override
#                                               (default: same as deployment).
#                     --probe-port <port>       force a specific port.
#                     --extra-check '<cmd>'     custom T6 check; treated
#                                               as PASS if exit 0.
#
#   output        : Stdout is a fixed-width 6-line table + RESULT footer.
#                     T1 (Argo Synced|Healthy)        : PASS  Synced|Healthy
#                     T2 (Deploy 2/2 ready)           : PASS  2/2
#                     T3 (HTTP /api/status = 200)     : PASS  200
#                     T4 (>=1 200-OK in last 60s)     : PASS  18
#                     T5 (0 ERR/FATAL in last 15m)    : PASS  0
#                     T6 (custom check)               : SKIP  (no --extra-check)
#                     RESULT: PASS (5/5 hard, 1 skip) [<label>]
#                   The format is stable enough that two runs (baseline
#                   and post) are diff-able with `diff baseline.out post.out`.
#
#   exit_codes    : 0 if every hard test passes (T6 SKIP is fine).
#                   Non-zero if any hard test FAILs, OR if --extra-check
#                   was supplied and T6 FAILs.
#
#   side_effects  : Read-only. Spawns a short-lived `validate-probe-$$`
#                   pod in the target namespace for T3, with --rm so it's
#                   gone after the probe. Tails logs (read), queries Argo
#                   Application status (read), inspects Deployment status
#                   (read). No writes.
#
#   requires      : kubectl with read across argocd + target namespace,
#                   and `run --rm` permission for the probe pod (uses
#                   curlimages/curl).
#
#   safe_in_dry_run:
#                 : Yes — already effectively dry-run; the script doesn't
#                   mutate anything. Safe to run on a heavily-loaded
#                   service.
#
#   composable_with:
#                 : - homelab/bin/pgo-pre-upgrade-backup.sh (Step 3 of
#                     the upgrade flow; this script is Step 6).
#                   - The seven-step upgrade process in
#                     architecture/upgrade-playbook.md.
#                   - Almost any chart-bump commit message that closes
#                     an upgrade issue should reference the baseline +
#                     post runs as evidence.
#
#   skill_pointer : See ~/.claude/skills/upgrade-validate/SKILL.md for
#                   the canonical skill description (Claude Code /
#                   opencode-readable).
#
# === END METADATA ===
#
# Usage:
#   upgrade-validate.sh <argo-app> <namespace> <deployment> [options]
#
# Output (machine-parseable contract):
#   T1 (Argo Synced|Healthy)         : PASS  Synced|Healthy
#   T2 (Deploy 2/2 ready)            : PASS  2/2
#   T3 (HTTP /api/status = 200)      : PASS  200
#   T4 (>=1 200-OK in last 60s)      : PASS  18
#   T5 (0 ERR/FATAL in last 15m)     : PASS  0
#   T6 (custom check)                : SKIP  (no --extra-check)
#   RESULT: PASS (5/5 hard, 1 skip)
#
# Exit 0 if every hard test PASSes (skips OK). Non-zero if any hard test
# FAILs, OR if --extra-check was provided and T6 FAILs.

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib/common.sh"

print_usage() {
    cat <<EOF
Usage: upgrade-validate.sh <argo-app> <namespace> <deployment> [options]

Runs the standard six-test TDD validation suite.

Args:
  <argo-app>     Argo Application name (in argocd namespace)
  <namespace>    Namespace where the Deployment lives
  <deployment>   Deployment name to validate

Options:
  --label <name>            tag printed in the output (e.g. baseline / post)
  --probe-path <path>       HTTP path for T3; default /api/status
  --service <name>          override Service name; default = <deployment>
  --probe-port <port>       Service port for T3; default 80 (or 8080 if 80 fails)
  --extra-check '<cmd>'     custom T6 check; treated as PASS if exit 0
  -h, --help                show this help

Example:
  upgrade-validate.sh infisical infisical infisical-infisical-standalone-infisical \\
    --label baseline --probe-path /api/status
EOF
}

# disable -e for arg parsing
set +e

label=""
probe_path="/api/status"
probe_port=""
service_override=""
extra_check=""
positional=()
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)        print_usage; exit 0 ;;
        --label)          label="$2"; shift 2 ;;
        --probe-path)     probe_path="$2"; shift 2 ;;
        --probe-port)     probe_port="$2"; shift 2 ;;
        --service)        service_override="$2"; shift 2 ;;
        --extra-check)    extra_check="$2"; shift 2 ;;
        --*)              err "unknown flag: $1" ;;
        *)                positional+=("$1"); shift ;;
    esac
done
set -e

[ ${#positional[@]} -ge 3 ] || err "missing required arguments. Need <argo-app> <namespace> <deployment>. Run with --help."

ARGO_APP=${positional[0]}
NS=${positional[1]}
DEPLOY=${positional[2]}
SERVICE=${service_override:-$DEPLOY}

require kubectl

declare -A status
declare -A value

# ---- T1: Argo health ----
T1=$(kubectl -n argocd get application "$ARGO_APP" -o jsonpath='{.status.sync.status}|{.status.health.status}' 2>&1) || T1="MISSING|MISSING"
[ "$T1" = "Synced|Healthy" ] && status[T1]=PASS || status[T1]=FAIL
value[T1]=$T1

# ---- T2: Deployment readiness ----
ready=$(kubectl -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
desired=$(kubectl -n "$NS" get deploy "$DEPLOY" -o jsonpath='{.status.replicas}' 2>/dev/null)
ready=${ready:-0}
desired=${desired:-0}
T2="${ready}/${desired}"
if [ "$ready" = "$desired" ] && [ "$ready" -gt 0 ] 2>/dev/null; then
    status[T2]=PASS
else
    status[T2]=FAIL
fi
value[T2]=$T2

# ---- T3: HTTP probe ----
# Try common service ports (80, 8080, 5678) unless overridden.
ports=()
if [ -n "$probe_port" ]; then
    ports=("$probe_port")
else
    # discover service ports
    mapfile -t svc_ports < <(kubectl -n "$NS" get svc "$SERVICE" -o jsonpath='{.spec.ports[*].port}' 2>/dev/null | tr ' ' '\n')
    if [ ${#svc_ports[@]} -gt 0 ]; then
        ports=("${svc_ports[@]}")
    else
        ports=(80 8080 5678)
    fi
fi

probe_code=""
probe_port_used=""
for p in "${ports[@]}"; do
    code=$(kubectl -n "$NS" run "validate-probe-$$" --rm -i --restart=Never --quiet \
        --image=curlimages/curl:8.10.1 --timeout=15s -- \
        curl -sf --max-time 8 -o /dev/null -w '%{http_code}' \
        "http://${SERVICE}:${p}${probe_path}" 2>/dev/null) || true
    if [ "$code" = "200" ]; then
        probe_code=$code
        probe_port_used=$p
        break
    fi
done
T3=${probe_code:-FAIL}
[ "$T3" = "200" ] && status[T3]=PASS || status[T3]=FAIL
value[T3]=$T3

# ---- T4: ≥1 200-OK in last 60s ----
log_60s=$(kubectl -n "$NS" logs deploy/"$DEPLOY" --since=60s 2>/dev/null || true)
T4_count=$(echo "$log_60s" | grep -c '"statusCode":200\|" 200 "\|HTTP/1.1" 200\|200 OK' || true)
T4=${T4_count:-0}
[ "$T4" -ge 1 ] 2>/dev/null && status[T4]=PASS || status[T4]=FAIL
value[T4]=$T4

# ---- T5: 0 ERROR/FATAL in last 15m ----
log_15m=$(kubectl -n "$NS" logs deploy/"$DEPLOY" --since=15m 2>/dev/null || true)
T5_count=$(echo "$log_15m" | grep -ciE '\[error\]|"severity":"ERROR"|"severity":"FATAL"|panic|fatal error' || true)
T5=${T5_count:-0}
[ "$T5" = "0" ] && status[T5]=PASS || status[T5]=FAIL
value[T5]=$T5

# ---- T6: custom check ----
if [ -n "$extra_check" ]; then
    if eval "$extra_check" >/dev/null 2>&1; then
        status[T6]=PASS
    else
        status[T6]=FAIL
    fi
    value[T6]="exit=$?"
else
    status[T6]=SKIP
    value[T6]="(no --extra-check)"
fi

# ---- output ----

label_suffix=""
[ -n "$label" ] && label_suffix=" [$label]"
printf '%-32s : %-4s  %s\n' "T1 (Argo Synced|Healthy)"      "${status[T1]}" "${value[T1]}"
printf '%-32s : %-4s  %s\n' "T2 (Deploy ${desired}/${desired} ready)"   "${status[T2]}" "${value[T2]}"
if [ -n "$probe_port_used" ]; then
    printf '%-32s : %-4s  %s\n' "T3 (HTTP ${probe_path} = 200)"  "${status[T3]}" "${value[T3]}"
else
    printf '%-32s : %-4s  %s\n' "T3 (HTTP ${probe_path} = 200)"  "${status[T3]}" "${value[T3]}"
fi
printf '%-32s : %-4s  %s\n' "T4 (>=1 200-OK in last 60s)"    "${status[T4]}" "${value[T4]}"
printf '%-32s : %-4s  %s\n' "T5 (0 ERR/FATAL in last 15m)"   "${status[T5]}" "${value[T5]}"
printf '%-32s : %-4s  %s\n' "T6 (custom check)"               "${status[T6]}" "${value[T6]}"

# tally
hard_pass=0; hard_fail=0; skip=0
for k in T1 T2 T3 T4 T5; do
    case "${status[$k]}" in
        PASS) hard_pass=$((hard_pass+1)) ;;
        FAIL) hard_fail=$((hard_fail+1)) ;;
    esac
done
case "${status[T6]}" in
    PASS) hard_pass=$((hard_pass+1)) ;;
    FAIL) hard_fail=$((hard_fail+1)) ;;
    SKIP) skip=$((skip+1)) ;;
esac

total=$((hard_pass + hard_fail))
if [ $hard_fail -eq 0 ]; then
    echo "RESULT: PASS (${hard_pass}/${total} hard${skip:+, $skip skip})${label_suffix}"
    exit 0
else
    echo "RESULT: FAIL (${hard_pass}/${total} hard${skip:+, $skip skip})${label_suffix}"
    exit 1
fi
