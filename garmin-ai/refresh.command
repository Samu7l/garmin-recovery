#!/bin/bash
# macOS equivalent of refresh.bat: double-click this file in Finder to run it.
cd "$(dirname "$0")"

# Uses the project's own venv (.venv/, created by "python3 -m venv .venv" +
# "pip install -r requirements.txt") so it never depends on whichever
# python3/pip happens to be first on PATH in a given terminal session.
PYTHON="./.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
    echo "No .venv found. Run this first:"
    echo "  cd garmin-ai && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
    read -n 1 -s -r -p "Press any key to close this window..."
    echo
    exit 1
fi

echo "=== Pulling recent Garmin data ==="
"$PYTHON" garmin_sync.py --days 14

echo
echo "=== Fetching GPS/pace/laps for any new activities ==="
"$PYTHON" garmin_activity_detail.py

echo
echo "=== Rebuilding the GitHub Pages site ==="
"$PYTHON" build_site.py

echo
echo "=== Publishing to GitHub ==="
cd ..
git add docs/ garmin-ai/
git commit -m "Refresh Garmin data"
git push

echo
echo "Done. GitHub Pages will redeploy in about a minute."
echo "Ask Claude to refresh the other dashboard (the Claude one still needs to go through Claude)."
read -n 1 -s -r -p "Press any key to close this window..."
echo
