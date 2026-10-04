#!/usr/bin/env bash
# pull-runs.sh — copy agent-run outputs from the server into this repo (run on the Mac).
#
# The console on the server runs the committee in its run workspace
# (/var/lib/mirqah/work). This copies ONLY the pipeline's outputs —
# data/**/moves/, data/**/verified/, data/**/committee/ (and committee_profile/, gold/
# for the A/B arm and the reviewers' teaching examples) — into the same paths here,
# so you can review them, commit them on a branch and open a PR (never main).
# Source text (raw/, layers/, spans/, windows/) is never copied or changed.
#
#   bash deploy/mac/pull-runs.sh                # from the repo root; ssh host "mirqah-console"
#   bash deploy/mac/pull-runs.sh other-host     # another ssh host alias
set -euo pipefail
HOST=${1:-mirqah-console}
REMOTE=/var/lib/mirqah/work/data/

cd "$(git rev-parse --show-toplevel)"
echo "pulling run outputs from $HOST:$REMOTE"
rsync -a --rsync-path="sudo rsync" \
  --include='*/' --include='**/moves/**' --include='**/verified/**' --include='**/committee/**' \
  --include='**/committee_profile/**' --include='**/gold/**' \
  --exclude='*' "$HOST:$REMOTE" data/
echo
echo "changed run outputs:"
git status --short -- data | grep -E '/(moves|verified|committee|committee_profile|gold)/' | head -60 || echo "  (none)"
if git status --short -- data | grep -vE '/(moves|verified|committee|committee_profile|gold)/' | grep -q .; then
  echo "WARNING: something outside moves/verified/committee changed — do not commit it:" >&2
  git status --short -- data | grep -vE '/(moves|verified|committee|committee_profile|gold)/' | head -20 >&2
fi
echo
echo "next: git switch -c runs/$(date +%Y%m%d)  →  git add data/**/moves data/**/verified data/**/committee data/**/committee_profile data/**/gold  →  commit  →  PR"
