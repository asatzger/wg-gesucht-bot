#!/bin/zsh
set -euo pipefail

VENV=".venv"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
source "$VENV/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements.txt

export STATE_PATH=${STATE_PATH:-data/seen_listings.json}
mkdir -p "$(dirname "$STATE_PATH")"

if [ -n "${HTML_FILE:-}" ]; then
  python bot/scrape_and_notify.py --html-file "$HTML_FILE"
else
  python bot/scrape_and_notify.py
fi
