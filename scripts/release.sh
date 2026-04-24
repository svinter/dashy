#!/bin/bash
# Build DMG and create a GitHub release.
#
# Usage:
#   ./scripts/release.sh [VERSION] [NOTES]
#
# If VERSION is omitted, auto-increments the patch version from the latest tag.
# If NOTES is omitted, uses Claude to generate release notes from commits.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

# --- Determine version ---
LATEST_TAG=$(git tag -l 'v*' --sort=-v:refname | head -1)
LATEST_VERSION="${LATEST_TAG#v}"  # strip leading 'v'

if [ -n "${1:-}" ]; then
    VERSION="$1"
else
    read -p "old version=${LATEST_VERSION:-none}; new version? " VERSION
    if [ -z "$VERSION" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# Ensure tag doesn't already exist
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    echo "ERROR: Tag v${VERSION} already exists"
    exit 1
fi

# --- Stamp version into frontend package.json ---
(cd app/frontend && npm version "$VERSION" --no-git-tag-version --allow-same-version)

# --- Build DMG ---
echo ""
./scripts/build-dmg.sh "$VERSION"

DMG_PATH="dist/Dashy-${VERSION}-macOS.dmg"
if [ ! -f "$DMG_PATH" ]; then
    echo "ERROR: DMG not found at $DMG_PATH"
    exit 1
fi

# --- Generate release notes ---
COMMIT_LOG=$(git log --pretty=format:'- %s' "${LATEST_TAG}..HEAD" 2>/dev/null | grep -v 'Co-Authored-By' || echo "- Various improvements")

if [ -n "${2:-}" ]; then
    TITLE="v${VERSION} — $2"
    NOTES="$2

## Commits
${COMMIT_LOG}"
else
    # Use Claude to generate release notes
    echo ""
    echo "--- Generating release notes with Claude ---"
    CLAUDE_NOTES=$(echo "$COMMIT_LOG" | claude --print "Write concise GitHub release notes (2-4 bullet points) from these git commits. Use markdown. Start with '## Changes' header. No preamble." 2>/dev/null || echo "")

    if [ -n "$CLAUDE_NOTES" ]; then
        NOTES="$CLAUDE_NOTES"
        # Extract a short title from first bullet point
        FIRST_LINE=$(echo "$CLAUDE_NOTES" | grep -m1 '^\- ' | sed 's/^- \*\*//' | sed 's/\*\*.*//' | head -c 60)
        TITLE="v${VERSION}${FIRST_LINE:+ — ${FIRST_LINE}}"
    else
        echo "(Claude not available, using commit log)"
        TITLE="v${VERSION}"
        NOTES="## Changes
${COMMIT_LOG}"
    fi
fi

NOTES="${NOTES}

## Install
Download \`Dashy-${VERSION}-macOS.dmg\`, drag to Applications, and launch."

echo ""
echo "--- Release preview ---"
echo "Title: $TITLE"
echo "$NOTES"
echo ""

# --- Tag and release ---
git tag "v${VERSION}"
git push origin "v${VERSION}"
gh repo set-default svinter/dashy
gh release create "v${VERSION}" "$DMG_PATH" \
    --title "$TITLE" \
    --notes "$NOTES"
echo ""
echo "=== Released v${VERSION} ==="
echo "https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/tag/v${VERSION}"
