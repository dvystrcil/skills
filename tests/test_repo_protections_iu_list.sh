#!/usr/bin/env bash
# Hermetic tests: which repos are CD (argocd-image-updater git write-back
# targets) comes from the explicit IU_WRITEBACK_REPOS list in solo-ruleset.sh,
# never from an `image-updater/` directory.
#
# The directory heuristic was wrong both ways (audit --all, 2026-11-11):
#   - kroger-mcp-docker and syncthing HAVE the dir (their IU CRs live there)
#     but IU writes to kroger-mcp and syncthing-chart. Treated as CD, they got
#     neither Ruleset: both sat with NO protection at all.
#   - cloudflare, syncthing-chart and trilium-notes ARE write-back targets with
#     no dir: apply.sh would have given them a Ruleset with no IU bypass and
#     broken every image update ("never run apply.sh on them").
# iu-targets.sh diffs the list against the live CRs so it can't silently rot.
#
# Run: bash tests/test_repo_protections_iu_list.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/../repo-protections/bin"
STUB_DIR="$(mktemp -d)"
trap 'rm -rf "$STUB_DIR"' EXIT
fail=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1"; [ -n "${out:-}" ] && echo "$out" | sed 's/^/    | /'; fail=1; }
run() { set +e; out=$(env "$@" 2>&1); rc=$?; set -e; }

echo "the real list"
# shellcheck source=../repo-protections/bin/solo-ruleset.sh
list=$(unset IU_WRITEBACK_REPOS_OVERRIDE; . "$BIN/solo-ruleset.sh"; printf '%s\n' "${IU_WRITEBACK_REPOS[@]}")
# A floor against an accidentally emptied list. 37 until homelab#2320 moved
# the release-action deploy repos to DIRECT_PUSH_APPS (2026-11-16), 23 since.
[ "$(wc -l <<<"$list")" -ge 20 ] && ok "has $(wc -l <<<"$list") entries" || bad "only $(wc -l <<<"$list") entries"
[ -z "$(sort <<<"$list" | uniq -d)" ] && ok "no duplicates" || bad "duplicates: $(sort <<<"$list" | uniq -d | tr '\n' ' ')"
[ -z "$(grep -vE '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' <<<"$list")" ] && ok "every entry is owner/repo" \
  || bad "malformed: $(grep -vE '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$' <<<"$list" | tr '\n' ' ')"
for r in cloudflare syncthing-chart trilium-notes; do
  grep -qx "dvystrcil/$r" <<<"$list" && ok "lists $r (write-back target, no image-updater/ dir)" || bad "$r missing"
done
for r in kroger-mcp-docker syncthing; do
  grep -qx "dvystrcil/$r" <<<"$list" && bad "lists $r (has the dir, is NOT a target)" || ok "does not list $r"
done

# release-action deploy repos push as the CICD App: the CD Ruleset exempts
# only the IU App, so listing one here breaks its deploys (writing-desk v0.0.2).
direct=$(unset IU_WRITEBACK_REPOS_OVERRIDE; . "$BIN/solo-ruleset.sh"; for k in "${!DIRECT_PUSH_APPS[@]}"; do printf '%s=%s\n' "$k" "${DIRECT_PUSH_APPS[$k]}"; done)
for r in story-mcp wiki-mcp tor-dice writing-desk ollama; do
  grep -qx "dvystrcil/$r" <<<"$list" && bad "lists $r (release-action deploys; not an IU target)" || ok "does not list $r"
  grep -q "^dvystrcil/$r=.*3693085" <<<"$direct" && ok "$r: CICD App in DIRECT_PUSH_APPS" || bad "$r: no CICD App in DIRECT_PUSH_APPS"
done

echo "is_iu_writeback_repo"
chk() { (export IU_WRITEBACK_REPOS_OVERRIDE="$1"; . "$BIN/solo-ruleset.sh"; is_iu_writeback_repo "$2"); }
chk "a/b o/r" o/r && ok "listed repo -> yes" || bad "listed repo -> no"
chk "a/b o/rr" o/r && bad "prefix match counted" || ok "o/rr does not match o/r"
chk "a/b" o/r && bad "unlisted repo -> yes" || ok "unlisted repo -> no"
chk "" dvystrcil/cloudflare && bad "empty override kept the real list" || ok "empty override = empty list"

echo "iu-targets.sh (live CRs vs the list)"
cat > "$STUB_DIR/kubectl" <<'STUB'
#!/usr/bin/env bash
[ -n "${KFAIL:-}" ] && { echo "error: the server doesn't have a resource type" >&2; exit 1; }
case "$*" in
  "get imageupdaters.argocd-image-updater.argoproj.io -A -o json") echo "$CRS" ;;
  *) echo "stub kubectl: unexpected call: $*" >&2; exit 98 ;;
esac
STUB
chmod +x "$STUB_DIR/kubectl"
export PATH="$STUB_DIR:$PATH"
ref() {  # repo-url [method]
  jq -nc --arg u "$1" --arg m "${2:-git}" '{writeBackConfig: {method: $m, gitConfig: {repository: $u, branch: "main"}}}'
}
CRS=$(jq -nc --argjson a "$(ref https://github.com/o/a.git)" --argjson b "$(ref https://github.com/o/b)" \
  --argjson c "$(ref https://github.com/o/c.git argocd)" \
  '{items: [{spec: {applicationRefs: [$a, $c]}}, {spec: {writeBackConfig: $b.writeBackConfig}}]}')

run CRS="$CRS" IU_WRITEBACK_REPOS_OVERRIDE="o/a o/b" bash "$BIN/iu-targets.sh"
[ "$rc" = 0 ] && grep -q "in sync" <<<"$out" && ok "matching list: exit 0, in sync (per-ref + top-level, .git stripped, argocd method ignored)" \
  || bad "matching list (rc=$rc)"

run CRS="$CRS" IU_WRITEBACK_REPOS_OVERRIDE="o/a" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && grep -q "o/b" <<<"$out" && ok "live target missing from the list: non-zero, names it" || bad "missing target not reported (rc=$rc)"

run CRS="$CRS" IU_WRITEBACK_REPOS_OVERRIDE="o/a o/b o/old" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && grep -q "o/old" <<<"$out" && ok "listed repo no longer a target: non-zero, names it" || bad "stale entry not reported (rc=$rc)"

run CRS="$CRS" IU_WRITEBACK_REPOS_OVERRIDE="o/a o/b o/c" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && grep -q "o/c" <<<"$out" && ok "argocd-method ref is not a git target" || bad "argocd method counted (rc=$rc)"

run KFAIL=1 CRS="$CRS" IU_WRITEBACK_REPOS_OVERRIDE="o/a o/b" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && grep -q "could not list ImageUpdater" <<<"$out" && ok "kubectl fails: non-zero, says so" || bad "kubectl failure not reported (rc=$rc)"

run CRS='{"items":[]}' IU_WRITEBACK_REPOS_OVERRIDE="o/a" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && ! grep -q "in sync" <<<"$out" && ok "no live targets at all: non-zero (wrong cluster/context?)" || bad "empty cluster passed (rc=$rc)"
run CRS='{"items":[]}' IU_WRITEBACK_REPOS_OVERRIDE="" bash "$BIN/iu-targets.sh"
[ "$rc" != 0 ] && ! grep -q "in sync" <<<"$out" && ok "no live targets and an empty list: still non-zero" || bad "empty == empty reported in sync (rc=$rc)"

[ "$fail" -eq 0 ] && echo "PASS" || { echo "FAILED"; exit 1; }
