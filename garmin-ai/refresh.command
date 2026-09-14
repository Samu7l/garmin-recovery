#!/bin/bash
# macOS equivalent of refresh.bat: double-click this file in Finder to run it.
cd "$(dirname "$0")"

echo "=== Pulling recent Garmin data ==="
python3 garmin_sync.py --days 5

echo
echo "=== Fetching GPS/pace/laps for any new activities ==="
python3 garmin_activity_detail.py

echo
echo "=== Rebuilding the GitHub Pages site ==="
python3 build_site.py

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
