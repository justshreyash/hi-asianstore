"""
Title Sanitizer & TMDB Metadata Resolver
"""

import re
import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def clean_title(raw_title: str) -> str:
    """
    Sanitize raw page title or drama name.
    Example:
      'Filing for Love [Korean Drama] Hindi Dubbed' -> 'Filing for Love'
      'Filing for Love (Season 1) [Hindi – Korean] 1080p' -> 'Filing for Love'
    """
    # Remove bracketed content like [Korean Drama], [Dual Audio], etc.
    title = re.sub(r"\[.*?\]", "", raw_title)
    # Remove parenthesized content like (Season 1), (2026), etc.
    title = re.sub(r"\(.*?\)", "", title)
    # Remove common tags
    remove_words = [
        r"\bkorean drama\b",
        r"\bchinese drama\b",
        r"\bk-drama\b",
        r"\bc-drama\b",
        r"\bkorean\b",
        r"\bchinese\b",
        r"\bhindi dubbed\b",
        r"\bhindi dub\b",
        r"\benglish dubbed\b",
        r"\benglish subbed\b",
        r"\beng sub\b",
        r"\bdual audio\b",
        r"\bseason\s*\d+\b",
        r"\b\d{3,4}p\b",
        r"\bweb-dl\b",
        r"\bcomplete\b",
        r"\ball episodes\b",
        r"\bepisodes?\b",
        r"\bdrama\b",
    ]
    for word_pattern in remove_words:
        title = re.sub(word_pattern, "", title, flags=re.IGNORECASE)

    # Clean punctuation and extra whitespace
    title = re.sub(r"[-–—:|]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def resolve_tmdb(title: str, year: Optional[str] = None) -> Dict[str, Any]:
    """
    Search TMDB for a TV series matching title and extract its metadata.
    """
    search_query = clean_title(title)
    search_url = f"https://www.themoviedb.org/search?query={requests.utils.quote(search_query)}"

    r = requests.get(search_url, headers=HEADERS, timeout=15)
    r.raise_for_status()

    # Find the best matching /tv/{id} link
    tv_ids = re.findall(r"/tv/(\d+)", r.text)
    if not tv_ids:
        # Default fallback if search didn't match immediately
        raise ValueError(f"No TMDB TV series found for query: '{search_query}'")

    tmdb_id = int(tv_ids[0])
    return get_tmdb_details(tmdb_id, fallback_title=search_query)


def get_tmdb_details(tmdb_id: int, fallback_title: str = "") -> Dict[str, Any]:
    """
    Fetch comprehensive TMDB details for a TV series by ID.
    """
    url = f"https://www.themoviedb.org/tv/{tmdb_id}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # Try extracting JSON-LD structured data first
    json_ld_tag = soup.find("script", type="application/ld+json")
    ld_data = {}
    if json_ld_tag and json_ld_tag.string:
        try:
            import json
            # Remove any CDATA wrappers
            clean_json = re.sub(r"/\*\s*<!\[CDATA\[\s*\*/|/\*\s*\]\]>\s*\*/", "", json_ld_tag.string).strip()
            ld_data = json.loads(clean_json)
        except Exception:
            pass

    # Extract Title
    title = ld_data.get("name")
    if not title:
        h2 = soup.find("h2")
        title = re.sub(r"\(\d{4}\)", "", h2.get_text(strip=True)).strip() if h2 else fallback_title

    # Extract Overview
    overview = ld_data.get("description")
    if not overview:
        ov_div = soup.find("div", class_="overview")
        overview = ov_div.get_text(" ", strip=True) if ov_div else ""

    # Extract Poster
    poster = ld_data.get("image")
    if not poster:
        img_tag = soup.find("img", class_="poster") or soup.find("img", alt=re.compile(r"poster", re.I))
        if img_tag and img_tag.get("src"):
            poster = img_tag["src"]

    # Extract Rating & Episodes
    rating = None
    if "aggregateRating" in ld_data:
        rating = float(ld_data["aggregateRating"].get("ratingValue", 0.0))

    total_episodes = ld_data.get("numberOfEpisodes", 12)
    start_date = ld_data.get("startDate", "")
    release_year = start_date[:4] if start_date else "2026"

    # Extract Original Title / Genres
    genres = ld_data.get("genre", ["Comedy", "Drama"])

    return {
        "tmdb_id": tmdb_id,
        "title": title,
        "overview": overview,
        "poster": poster,
        "rating": rating or 8.0,
        "release_year": release_year,
        "total_episodes": total_episodes,
        "total_seasons": 1,
        "genres": genres if isinstance(genres, list) else [genres],
        "tmdb_url": url
    }
