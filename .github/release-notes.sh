#!/bin/sh
# Print CHANGELOG.md's section for one version: everything between its
# "## <version> ..." heading and the next "## " heading. Prints nothing when
# the version has no section, which the release workflow treats as an error.
version="$1"
awk -v v="$version" '
    /^## / { if (found) exit; if ($2 == v) { found = 1; next } }
    found { print }
' "$(dirname "$0")/../CHANGELOG.md"
