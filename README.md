## Tübingen WG Bot

- Checks hourly for new WG-Zimmer listings in Tübingen (≤ 430€) and posts to a Telegram channel, one message per listing, with link and image when available.
- Source site: [WG-Gesucht – Tübingen WG-Zimmer ≤ 430€](https://www.wg-gesucht.de/wg-zimmer-in-Tuebingen.127.0.1.0.html?offer_filter=1&city_id=127&sort_order=0&noDeact=1&categories%5B%5D=0&rMax=430)

### Local run

1) Create a venv and install deps:

```bash
./scripts/run_local.sh
```

- Optional: set environment variables or create `.env` from `.env.example`
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - `WG_URL` (defaults to Tübingen WG link above)
  - `STATE_PATH` (defaults to `data/seen_listings.json`)

- To test parser offline with a local HTML file:

```bash
HTML_FILE=sample/sample_search.html ./scripts/run_local.sh
```

2) First run will populate `data/seen_listings.json`. Subsequent runs only send new listings.

### GitHub Actions

- Workflow: `.github/workflows/scrape.yml`
- Required repo secrets:
  - `TELEGRAM_BOT_TOKEN`: your bot token
  - `TELEGRAM_CHAT_ID`: your channel/group chat id (e.g., `-1004828402445`)
- Runs hourly via cron and stores seen state under `data/` using cache.

### Notes

- Messages include title, price/size if found, address/meta when present, link, and image when available.
- The scraper is conservative; if elements are missing it still sends the link.
