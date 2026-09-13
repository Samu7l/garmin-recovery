@echo off
cd /d "%~dp0"
echo === Pulling recent Garmin data ===
python garmin_sync.py --days 5
echo.
echo === Fetching GPS/pace/laps for any new activities ===
python garmin_activity_detail.py
echo.
echo === Rebuilding the GitHub Pages site ===
python build_site.py
echo.
echo === Publishing to GitHub ===
cd /d "%~dp0.."
git add -A
git commit -m "Refresh Garmin data"
git push
echo.
echo Done. GitHub Pages will redeploy in about a minute.
echo Ask Claude to refresh the other dashboard (the Claude one still needs to go through Claude).
