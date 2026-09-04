"""
KDramaLover Crawler & Change Tracker
Strictly targets Korean Drama and Chinese Drama categories.
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, List, Optional
from services.tmdb_resolver import clean_title
from storage.sqlite_db import SqliteDatabase

CATEGORIES = [
    {
        "id": "korean-drama",
        "name": "Korean Drama",
        "badge": "🇰🇷 Korean",
        "url": "https://kdramalover.com/category/korean-drama-hindi-dubbed/"
    },
    {
        "id": "chinese-drama",
        "name": "Chinese Drama",
        "badge": "🇨🇳 Chinese",
        "url": "https://kdramalover.com/category/chinese-drama-hindi-dubbed/"
    }
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def extract_update_tag(raw_title: str) -> Optional[str]:
    """Extract update tag like [Ep10 Added] or [All Episodes Added]."""
    match = re.search(r"\[(Ep\s*\d+\s*Added|All\s*Episodes?\s*Added|Complete)\]", raw_title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def parse_category_page(base_url: str, page_num: int = 1) -> List[Dict[str, Any]]:
    """Fetch and parse a single pagination page of a category."""
    if page_num == 1:
        page_url = base_url
    else:
        page_url = f"{base_url.rstrip('/')}/page/{page_num}/"

    r = requests.get(page_url, headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return []
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    articles = soup.find_all("article")
    items = []

    for art in articles:
        # Title & URL
        h2 = art.find("h2") or art.find("h1") or art.find("h3")
        a_tag = h2.find("a", href=True) if h2 else art.find("a", href=True)
        if not a_tag:
            continue

        raw_title = a_tag.get_text(strip=True)
        drama_url = a_tag["href"].strip()

        # Poster
        img_tag = art.find("img")
        poster = img_tag.get("src") or img_tag.get("data-src") if img_tag else None

        clean = clean_title(raw_title)
        update_tag = extract_update_tag(raw_title)

        items.append({
            "kdramalover_url": drama_url,
            "raw_title": raw_title,
            "clean_title": clean,
            "poster": poster,
            "update_tag": update_tag
        })

    return items


def run_refresh(max_pages: int = 3) -> Dict[str, Any]:
    """
    Quick daily sync: scans recent pages (default 1 to 3) of Korean & Chinese dramas.
    Detects new shows, updates to existing shows, and saves to SQLite queue.
    """
    db = SqliteDatabase()
    summary = {
        "categories_checked": len(CATEGORIES),
        "total_scanned": 0,
        "new_items": 0,
        "updated_items": 0,
        "ingested_items": 0,
        "items": []
    }

    for cat in CATEGORIES:
        cat_id = cat["id"]
        base_url = cat["url"]

        for page in range(1, max_pages + 1):
            page_items = parse_category_page(base_url, page_num=page)
            if not page_items:
                break

            for item in page_items:
                summary["total_scanned"] += 1
                record = db.upsert_crawler_item(
                    kdramalover_url=item["kdramalover_url"],
                    raw_title=item["raw_title"],
                    clean_title=item["clean_title"],
                    category=cat_id,
                    poster=item["poster"],
                    update_tag=item["update_tag"]
                )

                if record["status"] == "pending":
                    summary["new_items"] += 1
                elif record["status"] == "update_available":
                    summary["updated_items"] += 1
                elif record["status"] == "ingested":
                    summary["ingested_items"] += 1

                record["raw_title"] = item["raw_title"]
                record["poster"] = item["poster"]
                summary["items"].append(record)

    return summary


def run_full_crawl() -> Dict[str, Any]:
    """Deep crawl across all pages of Korean & Chinese categories."""
    # Korean Drama (~38 pages), Chinese Drama (~16 pages)
    return run_refresh(max_pages=40)
