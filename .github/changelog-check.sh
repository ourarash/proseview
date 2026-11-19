#!/bin/sh
# Warn, without failing CI, when Proseview's code has changed since
# CHANGELOG.md was last edited. Release notes are made from CHANGELOG.md, and
# an Unreleased section that falls weeks behind has to be rebuilt from commit
# subjects at release time.
set -eu
last=$(git log -1 --format=%H -- CHANGELOG.md)
[ -n "$last" ] || exit 0
commits=$(git log --format='%h %s' "$last"..HEAD -- proseview)
[ -n "$commits" ] || exit 0
count=$(printf '%s\n' "$commits" | wc -l | tr -d ' ')
message="$count commit(s) changed proseview/ since CHANGELOG.md was last updated. Add what users will notice to its Unreleased section:"
# GitHub shows a warning's text on one line; %0A starts a new one.
list=$(printf '%s\n' "$commits" | head -20 | sed 's/^/  /' | awk '{printf "%s%%0A", $0}')
if [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "::warning file=CHANGELOG.md,title=CHANGELOG.md is behind::$message%0A$list"
else
    echo "$message"
    printf '%s\n' "$commits" | head -20 | sed 's/^/  /'
fi
