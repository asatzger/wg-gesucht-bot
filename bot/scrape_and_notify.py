#!/usr/bin/env python3
import os
import re
import json
import time
import html
from typing import List, Dict, Optional, Tuple, Set

import requests
from bs4 import BeautifulSoup

# Load .env if present (for local runs)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

WG_URL_DEFAULT = "https://www.wg-gesucht.de/wg-zimmer-in-Tuebingen.127.0.1.0.html?offer_filter=1&city_id=127&sort_order=0&noDeact=1&categories%5B%5D=0&rMax=430"
STATE_PATH_DEFAULT = os.environ.get("STATE_PATH", "data/seen_listings.json")
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
WG_URL = os.environ.get("WG_URL", WG_URL_DEFAULT)

REQUEST_TIMEOUT = 20
DEBUG_DUMP = os.environ.get("DEBUG_DUMP_HTML", "0") == "1"


def read_file_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_seen_ids(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return set(map(str, data))
            elif isinstance(data, dict) and "seen_ids" in data:
                return set(map(str, data.get("seen_ids", [])))
            else:
                return set()
    except Exception:
        return set()


def save_seen_ids(path: str, ids: Set[str]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(list(ids)), f, indent=2, ensure_ascii=False)


def http_get(url: str) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.9"}
    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def extract_listing_ids_and_links(html_text: str) -> List[Tuple[str, str]]:
    """Extract listing IDs and links using multiple strategies (robust to site changes)."""
    results: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    # 1) Regex over raw HTML for absolute and relative links like /1234567.html
    # Prefer IDs with at least 6 digits to avoid false positives
    for m in re.finditer(r"https?://www\\.wg-gesucht\\.de/(\\d{6,})\\.html", html_text):
        listing_id = m.group(1)
        if listing_id in seen:
            continue
        seen.add(listing_id)
        results.append((listing_id, f"https://www.wg-gesucht.de/{listing_id}.html"))

    for m in re.finditer(r"/(\\d{6,})\\.html", html_text):
        listing_id = m.group(1)
        if listing_id in seen:
            continue
        seen.add(listing_id)
        results.append((listing_id, f"https://www.wg-gesucht.de/{listing_id}.html"))

    # 2) Parse DOM and check href/data-href attributes too (if present)
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        # anchors
        for a in soup.find_all("a"):
            href = a.get("href") or a.get("data-href")
            if not href:
                continue
            mm = re.search(r"/(\\d{5,})\\.html", href) or re.search(r"https?://www\\.wg-gesucht\\.de/(\\d{5,})\\.html", href)
            if mm:
                listing_id = mm.group(1)
                if listing_id in seen:
                    continue
                seen.add(listing_id)
                link = href if href.startswith("http") else f"https://www.wg-gesucht.de/{listing_id}.html"
                results.append((listing_id, link))

        # elements carrying listing IDs in attributes, e.g. data-id="7864981" or data-ad_id="7864981"
        for el in soup.find_all(attrs={"data-id": True}):
            listing_id = str(el.get("data-id", "")).strip()
            if re.fullmatch(r"\d{5,}", listing_id) and listing_id not in seen:
                seen.add(listing_id)
                results.append((listing_id, f"https://www.wg-gesucht.de/{listing_id}.html"))
        for el in soup.find_all(attrs={"data-ad_id": True}):
            listing_id = str(el.get("data-ad_id", "")).strip()
            if re.fullmatch(r"\d{5,}", listing_id) and listing_id not in seen:
                seen.add(listing_id)
                results.append((listing_id, f"https://www.wg-gesucht.de/{listing_id}.html"))

        # IDs embedded in element id attributes like id="liste-details-ad-684312"
        for el in soup.find_all(id=True):
            mm = re.search(r"liste-details-ad-(\d{5,})", el.get("id", ""))
            if mm:
                listing_id = mm.group(1)
                if listing_id not in seen:
                    seen.add(listing_id)
                    results.append((listing_id, f"https://www.wg-gesucht.de/{listing_id}.html"))
    except Exception:
        pass

    return results


def extract_text_patterns(text: str) -> Tuple[Optional[str], Optional[str]]:
    price = None
    size = None
    mp = re.search(r"(\d{2,4})\s*€", text.replace("\n", " "))
    if mp:
        price = mp.group(1)
    ms = re.search(r"(\d{1,3})\s*m²", text.replace("\n", " "))
    if ms:
        size = ms.group(1)
    return price, size


def fetch_listing_details(url: str) -> Dict[str, Optional[str]]:
    try:
        page = http_get(url)
    except Exception as e:
        return {"title": None, "price": None, "size": None, "image": None, "address": None, "url": url}
    soup = BeautifulSoup(page, "html.parser")

    title = None
    if soup.find("h1"):
        title = soup.find("h1").get_text(strip=True)
    if not title and soup.title:
        title = soup.title.get_text(strip=True)

    # Try to find price/size in page text
    full_text = soup.get_text(" ", strip=True)
    price, size = extract_text_patterns(full_text)

    # Try to find address/location heuristically
    address = None
    # WG-Gesucht pages often have meta tags
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        address = meta_desc.get("content")

    # No image handling (text-only messages)
    return {"title": title, "price": price, "size": size, "image": None, "address": address, "url": url}


def escape_html(s: str) -> str:
    return html.escape(s or "")


def build_caption(details: Dict[str, Optional[str]]) -> str:
    parts: List[str] = []
    if details.get("title"):
        parts.append(f"<b>{escape_html(details['title'])}</b>")
    if details.get("price") or details.get("size"):
        dims = []
        if details.get("price"):
            dims.append(f"{escape_html(details['price'])} €")
        if details.get("size"):
            dims.append(f"{escape_html(details['size'])} m²")
        parts.append(" | ".join(dims))
    if details.get("address"):
        parts.append(escape_html(details["address"]))
    parts.append(f"<a href='{escape_html(details['url'])}'>Zur Anzeige</a>")
    return "\n".join(parts)


def tg_send_message(token: str, chat_id: str, text: str, disable_web_page_preview: bool = False) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": disable_web_page_preview,
    }
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()



def run(html_file: Optional[str] = None) -> int:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("WARN: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set. Dry-run mode: messages will not be sent.")
    state_path = STATE_PATH_DEFAULT
    seen_ids = load_seen_ids(state_path)

    print(f"Loaded {len(seen_ids)} seen listing IDs from {state_path}")

    if html_file:
        text = read_file_text(html_file)
    else:
        print(f"Fetching search page: {WG_URL}")
        text = http_get(WG_URL)

    pairs = extract_listing_ids_and_links(text)
    print(f"Found {len(pairs)} listing links on page")
    if len(pairs) == 0 and DEBUG_DUMP:
        try:
            ensure_dir("data")
            with open("data/last_search.html", "w", encoding="utf-8") as f:
                f.write(text)
            print("DEBUG: wrote fetched HTML to data/last_search.html")
        except Exception:
            pass

    new_pairs = [(lid, url) for lid, url in pairs if lid not in seen_ids]
    if not new_pairs:
        print("No new listings detected.")
        return 0

    print(f"Detected {len(new_pairs)} new listing(s): {[lid for lid, _ in new_pairs]}")

    failures = 0
    for listing_id, link in new_pairs:
        details = fetch_listing_details(link)
        caption = build_caption(details)
        print(f"Prepared message for {listing_id}: {caption}")
        try:
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                tg_send_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, caption, disable_web_page_preview=False)
                time.sleep(0.8)  # mild pacing
        except Exception as e:
            print(f"ERROR sending to Telegram for {listing_id}: {e}")
            failures += 1
            continue
        # Mark as seen only after attempted send
        seen_ids.add(listing_id)

    save_seen_ids(state_path, seen_ids)
    print(f"Saved {len(seen_ids)} total seen listing IDs to {state_path}")

    return 1 if failures else 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WG-Gesucht scraper and Telegram notifier")
    parser.add_argument("--html-file", help="Parse listings from local HTML file (for testing)")
    args = parser.parse_args()
    exit_code = run(html_file=args.html_file)
    raise SystemExit(exit_code)
