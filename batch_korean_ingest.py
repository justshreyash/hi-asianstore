#!/usr/bin/env python3
"""
Batch Korean Drama Ingest & Archive Upload Service
==================================================
Ultra-Fast, Observable & Resilient Ingestion Engine.
- Multi-threaded parallel episode resolution (default 6 workers).
- Adaptive token-bucket rate-limiting on video providers.
- Granular failure diagnostics & automatic quarantine logging in SQLite.
- Resumable, idempotent, and supports instant manual link overrides.

Usage:
  python batch_korean_ingest.py
  python batch_korean_ingest.py --workers 6
  python batch_korean_ingest.py --pages 5 --workers 6
  python batch_korean_ingest.py --quarantine
  python batch_korean_ingest.py --retry-quarantine
  python batch_korean_ingest.py --override --tmdb 76114 --ep 9 --vidara <code_or_url>
"""

import os
import sys
import time
import math
import json
import argparse
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# UTF-8 support for Windows CMD
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.sqlite_db import SqliteDatabase
from storage.repository import DramaRepository
from services.tmdb_resolver import clean_title, resolve_tmdb
from services.crawler import parse_category_page
from resolve_ep1 import LinkResolver
from providers.vidara import VidaraProvider
from providers.savefiles import SaveFilesProvider
from providers.playmate import PlaymateProvider

CATEGORY_URLS = {
    "korean-drama": "https://kdramalover.com/category/korean-drama-hindi-dubbed/",
    "chinese-drama": "https://kdramalover.com/category/chinese-drama-hindi-dubbed/"
}
KOREAN_CAT_URL = CATEGORY_URLS["korean-drama"]
DEFAULT_FOLDER = "hindi-asian"

# Thread-safe console printing lock
print_lock = threading.Lock()


class TokenBucketLimiter:
    """Thread-safe rate limiter implementing a token bucket."""
    def __init__(self, rate_per_second: float = 1.0):
        self.rate = rate_per_second
        self.tokens = rate_per_second
        self.last_update = time.time()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            if self.tokens < 1.0:
                sleep_time = (1.0 - self.tokens) / self.rate
                time.sleep(sleep_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class AsciiProgress:
    """ASCII spinner and progress bar helper."""
    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    FALLBACK_FRAMES = ["|", "/", "-", "\\"]

    def __init__(self):
        self.frame_idx = 0
        self.use_fallback = (sys.platform == "win32" and sys.stdout.encoding.lower() != 'utf-8')

    def next_frame(self) -> str:
        frames = self.FALLBACK_FRAMES if self.use_fallback else self.SPINNER_FRAMES
        char = frames[self.frame_idx % len(frames)]
        self.frame_idx += 1
        return char

    @staticmethod
    def bar(current: int, total: int, width: int = 25) -> str:
        if total <= 0:
            return f"[{' ' * width}] 0.0%"
        pct = min(1.0, max(0.0, current / total))
        filled = int(round(width * pct))
        empty = width - filled
        bar_str = "=" * filled + (">" if empty > 0 else "") + " " * max(0, empty - (1 if empty > 0 else 0))
        return f"[{bar_str}] {pct * 100:.1f}% ({current}/{total})"


def safe_print(msg: str = ""):
    with print_lock:
        print(msg, flush=True)


def print_banner():
    safe_print("=" * 80)
    safe_print("   _  ______  ____  _________   _   __   _____  ______  ______  ______")
    safe_print("  / |/ / __ \\/ __ \\/ ____/   | / | / /  / ___/ /_  __/ / __ \\/ ____/")
    safe_print(" /    / / / / /_/ / __/ / /| |/  |/ /   \\__ \\   / /   / / / / /_    ")
    safe_print("/ /| / /_/ / _, _/ /___/ ___ / /|  /   ___/ /  / /   / /_/ / __/    ")
    safe_print("/_/ |_/\\____/_/ |_/_____/_/  |_/_/ |_/  /____/  /_/    \\____/_/       ")
    safe_print("=" * 80)
    safe_print(" KDramaLover Korean Drama Hindi Dubbed Auto-Ingestion & Cloud Storage")
    safe_print(" Target Category : 🇰🇷 Korean Drama Hindi Dubbed")
    safe_print(" Storage         : SQLite (data/hindi_asian.db) + JSON Cache")
    safe_print(" Video Providers : Vidara (Primary HLS) + SaveFiles (Fallback HLS)")
    safe_print(" Resilience      : Adaptive Rate Limiter & Quarantine Recovery Queue")
    safe_print(" Remote Folder   : 'hindi-asian'")
    safe_print("=" * 80)


class KoreanDramaBatchIngestor:
    def __init__(self, workers: int = 6, force: bool = False, limit_eps: Optional[int] = None):
        self.workers = workers
        self.force = force
        self.limit_eps = limit_eps
        self.db = SqliteDatabase()
        self.json_repo = DramaRepository()
        self.resolver = LinkResolver()
        self.vidara = VidaraProvider()
        self.savefiles = SaveFilesProvider()
        self.playmate = PlaymateProvider()
        self.vidara_fld = None
        self.savefiles_fld = None
        self.playmate_fld = None
        self.spinner = AsciiProgress()

        # Adaptive Rate Limiters
        self.vidara_limiter = TokenBucketLimiter(1.0)       # max 1.0 upload/sec to Vidara
        self.savefiles_limiter = TokenBucketLimiter(2.0)    # max 2.0 upload/sec to SaveFiles
        self.playmate_limiter = TokenBucketLimiter(2.0)     # max 2.0 upload/sec to Playmate
        self.resolver_limiter = TokenBucketLimiter(3.0)     # max 3.0 scraper requests/sec

        # Stats
        self.stats = {
            "dramas_scanned": 0,
            "dramas_processed": 0,
            "dramas_skipped": 0,
            "dramas_failed": 0,
            "episodes_uploaded": 0,
            "episodes_cached": 0,
            "episodes_failed": 0,
            "episodes_quarantined": 0,
            "start_time": time.time()
        }

    def init_folders(self):
        """Create or locate target remote folder 'hindi-asian' on both hosts."""
        safe_print("\n[*] Initializing cloud storage folders on providers...")
        try:
            self.vidara_fld = self.vidara.get_or_create_folder(DEFAULT_FOLDER)
            safe_print(f"    [+] Vidara folder '{DEFAULT_FOLDER}'    -> ID: {self.vidara_fld}")
        except Exception as e:
            safe_print(f"    [!] Vidara folder warning: {e}")

        try:
            self.savefiles_fld = self.savefiles.get_or_create_folder(DEFAULT_FOLDER)
            safe_print(f"    [+] SaveFiles folder '{DEFAULT_FOLDER}' -> ID: {self.savefiles_fld}")
        except Exception as e:
            safe_print(f"    [!] SaveFiles folder warning: {e}")

        try:
            self.playmate_fld = self.playmate.get_or_create_folder(DEFAULT_FOLDER)
            safe_print(f"    [+] Playmate folder '{DEFAULT_FOLDER}'  -> ID: {self.playmate_fld}")
        except Exception as e:
            safe_print(f"    [!] Playmate folder warning: {e}")

    def discover_dramas(self, category: str = "korean-drama", max_pages: int = 5) -> List[Dict[str, Any]]:
        """Crawl pages of Korean/Chinese Drama category and sync to crawler queue."""
        cat_url = CATEGORY_URLS.get(category, KOREAN_CAT_URL)
        label = "Korean" if "korean" in category else "Chinese"
        safe_print(f"\n[*] Crawling KDramaLover {label} Drama category (Scanning up to {max_pages} pages)...")
        discovered = []
        seen_urls = set()

        for page in range(1, max_pages + 1):
            frame = self.spinner.next_frame()
            safe_print(f"    {frame} Scanning Page {page}...")
            try:
                items = parse_category_page(cat_url, page_num=page)
                if not items:
                    safe_print(f"    [=] No more items found on page {page}.")
                    break

                for it in items:
                    url = it["kdramalover_url"]
                    raw_title = it["raw_title"]

                    is_english = "english" in url.lower() or "english" in raw_title.lower()
                    is_hindi = "hindi" in url.lower() or "hindi" in raw_title.lower()

                    if is_english or not is_hindi:
                        self.db.upsert_crawler_item(
                            kdramalover_url=url,
                            raw_title=raw_title,
                            clean_title=it["clean_title"],
                            category=category,
                            poster=it.get("poster"),
                            update_tag=it.get("update_tag"),
                            status="skipped_non_hindi"
                        )
                        continue

                    if url not in seen_urls:
                        seen_urls.add(url)
                        rec = self.db.upsert_crawler_item(
                            kdramalover_url=url,
                            raw_title=raw_title,
                            clean_title=it["clean_title"],
                            category=category,
                            poster=it.get("poster"),
                            update_tag=it.get("update_tag")
                        )
                        if rec.get("status") in ("pending", "update_available"):
                            discovered.append(it)
            except Exception as e:
                safe_print(f"    [!] Error crawling page {page}: {e}")
                break

        safe_print(f"[+] Total Hindi-Dubbed {label} Dramas pending/available: {len(discovered)}")
        return discovered

    def discover_korean_dramas(self, max_pages: int = 5) -> List[Dict[str, Any]]:
        """Backward compatibility wrapper."""
        return self.discover_dramas(category="korean-drama", max_pages=max_pages)

    def process_single_episode(
        self,
        ep_data: Dict[str, Any],
        tmdb_id: int,
        drama_title: str,
        season_num: int,
        total_eps: int
    ) -> Dict[str, Any]:
        """Resolves download links, uploads with rate limits, and logs quarantine if needed."""
        ep_num = ep_data["episode_number"]
        ep_title = ep_data["title"]
        ep_links = ep_data["links"]
        t0 = time.time()

        # Step 1: Check existing in SQLite
        existing_ep = None
        if not self.force:
            existing = self.db.get_drama(tmdb_id)
            if existing:
                for s in existing.get("seasons", []):
                    for ep in s.get("episodes", []):
                        if ep.get("episode_number") == ep_num:
                            existing_ep = ep
                            break

        has_vid = bool(existing_ep and existing_ep.get("hosts", {}).get("vidara"))
        has_sf = bool(existing_ep and (existing_ep.get("hosts", {}).get("savefiles") or existing_ep.get("hosts", {}).get("byse")))
        has_pm = bool(existing_ep and existing_ep.get("hosts", {}).get("playmate"))

        if (has_vid or has_sf or has_pm) and not self.force:
            self.stats["episodes_cached"] += 1
            v_tag = existing_ep['hosts']['vidara'][-12:] if has_vid else "N/A"
            sf_val = existing_ep['hosts'].get('savefiles') or existing_ep['hosts'].get('byse')
            sf_tag = sf_val[-12:] if sf_val else "N/A"
            pm_val = existing_ep['hosts'].get('playmate')
            pm_tag = pm_val[-12:] if pm_val else "N/A"
            safe_print(f"  ├─ Ep {ep_num:02d}: [✓ CACHED] (Vidara: {v_tag} | SaveFiles: {sf_tag} | Playmate: {pm_tag})")
            return existing_ep

        # Step 2: Resolve download links with resolver limiter
        self.resolver_limiter.acquire()
        safe_print(f"  ├─ Ep {ep_num:02d}: [⏳ RESOLVING] Scraping HubCloud & GDFlix...")
        direct_urls = self.resolver.resolve_episode_direct_urls(ep_links)
        r2_url = direct_urls.get("r2")
        google_url = direct_urls.get("google_cdn")

        # Failure Case: No links found at all
        if not r2_url and not google_url:
            self.stats["episodes_failed"] += 1
            self.stats["episodes_quarantined"] += 1
            safe_print(f"  ├─ Ep {ep_num:02d}: [✗ QUARANTINE] No downloadable mirrors found in HubCloud or GDFlix.")
            self.db.upsert_quarantine_item(
                tmdb_id=tmdb_id,
                drama_title=drama_title,
                season_number=season_num,
                episode_number=ep_num,
                provider_missing="both",
                failure_code="ERR_NO_MIRRORS_FOUND",
                failure_detail="Both HubCloud and GDFlix returned 0 direct downloadable mirrors.",
                raw_links=ep_links,
                status="manual_required"
            )
            return None

        vidara_embed = existing_ep.get("hosts", {}).get("vidara") if existing_ep else None
        savefiles_embed = (existing_ep.get("hosts", {}).get("savefiles") or existing_ep.get("hosts", {}).get("byse")) if existing_ep else None

        # Step 3: Vidara Upload (Primary - Cloudflare R2 / PixelDrain)
        if not vidara_embed:
            if r2_url and "googleusercontent.com" not in r2_url:
                self.vidara_limiter.acquire()
                try:
                    vres = self.vidara.upload_url(r2_url, folder_id=self.vidara_fld)
                    vidara_embed = vres.get("embed_url")
                except Exception as e:
                    code = "ERR_PROVIDER_RATE_LIMIT_429" if "429" in str(e) else "ERR_PROVIDER_SERVER_5XX"
                    safe_print(f"  │   [!] Vidara upload err Ep {ep_num}: {code} ({e})")
            elif not r2_url and google_url:
                # Mirror constraint: Google CDN link not supported by Vidara, will be handled by SaveFiles
                pass

        # Step 4: SaveFiles Upload (Secondary & Fallback - Supports R2, GDFlix, Google CDN)
        if not savefiles_embed:
            sf_target_url = r2_url or google_url
            if sf_target_url:
                self.savefiles_limiter.acquire()
                try:
                    sres = self.savefiles.upload_url(sf_target_url, folder_id=self.savefiles_fld)
                    savefiles_embed = sres.get("url")
                except Exception as e:
                    code = "ERR_PROVIDER_RATE_LIMIT_429" if "429" in str(e) else "ERR_PROVIDER_SERVER_5XX"
                    safe_print(f"  │   [!] SaveFiles upload err Ep {ep_num}: {code} ({e})")

        playmate_embed = existing_ep.get("hosts", {}).get("playmate") if existing_ep else None

        # Step 5: Playmate Upload (Tertiary & Fallback - Ultra-fast HLS resolution)
        if not playmate_embed and (not vidara_embed or not savefiles_embed):
            pm_target_url = r2_url or google_url
            if pm_target_url:
                self.playmate_limiter.acquire()
                try:
                    pm_res = self.playmate.upload_url(pm_target_url, folder_id=self.playmate_fld)
                    playmate_embed = pm_res.get("embed_url")
                except Exception as e:
                    code = "ERR_PROVIDER_RATE_LIMIT_429" if "429" in str(e) else "ERR_PROVIDER_SERVER_5XX"
                    safe_print(f"  │   [!] Playmate upload err Ep {ep_num}: {code} ({e})")

        # Evaluate Success Condition: At least one host MUST succeed
        if not vidara_embed and not savefiles_embed and not playmate_embed:
            self.stats["episodes_failed"] += 1
            self.stats["episodes_quarantined"] += 1
            safe_print(f"  ├─ Ep {ep_num:02d}: [✗ QUARANTINE] All remote uploads (Vidara, SaveFiles, Playmate) failed.")
            self.db.upsert_quarantine_item(
                tmdb_id=tmdb_id,
                drama_title=drama_title,
                season_number=season_num,
                episode_number=ep_num,
                provider_missing="all",
                failure_code="ERR_ALL_HOSTS_FAILED",
                failure_detail="Vidara, SaveFiles, and Playmate remote uploads all failed.",
                raw_links=ep_links,
                status="manual_required"
            )
            return None

        # Resolve quarantine if at least one succeeded
        self.db.resolve_quarantine_item(tmdb_id, season_num, ep_num)

        elapsed = round(time.time() - t0, 1)
        v_code = (vidara_embed or "").split("/")[-1] if vidara_embed else "N/A"
        s_code = (savefiles_embed or "").split("/")[-1] if savefiles_embed else "N/A"
        p_code = (playmate_embed or "").split("/")[-1] if playmate_embed else "N/A"

        ep_record = {
            "episode_number": ep_num,
            "title": ep_title,
            "hosts": {
                "vidara": vidara_embed,
                "savefiles": savefiles_embed,
                "playmate": playmate_embed
            },
            "direct": {
                "vidara": {
                    "type": "hls",
                    "origin": "https://vidarae.live",
                    "referer": "https://vidarae.live/",
                    "status": "on_the_fly_resolver"
                },
                "savefiles": {
                    "type": "hls",
                    "origin": "https://savefiles.com",
                    "referer": "https://savefiles.com/",
                    "status": "on_the_fly_resolver"
                },
                "playmate": {
                    "type": "hls",
                    "origin": "https://playmate.to",
                    "referer": "https://playmate.to/",
                    "status": "on_the_fly_resolver"
                }
            },
            "sources_used": {
                "vidara": "r2" if r2_url else None,
                "savefiles": "r2" if r2_url else "google_cdn",
                "playmate": "r2" if r2_url else "google_cdn"
            }
        }

        # Save to SQLite
        self.db.upsert_episode(
            tmdb_id=tmdb_id,
            season_number=season_num,
            episode_number=ep_num,
            title=f"Episode {ep_num}",
            host_vidara=vidara_embed,
            host_savefiles=savefiles_embed,
            host_playmate=playmate_embed,
            direct_vidara=ep_record["direct"]["vidara"],
            direct_savefiles=ep_record["direct"]["savefiles"],
            direct_playmate=ep_record["direct"]["playmate"],
            sources_used=ep_record["sources_used"]
        )

        self.stats["episodes_uploaded"] += 1
        safe_print(f"  ├─ Ep {ep_num:02d}: [✓ UPLOADED] (Vidara: {v_code} | SaveFiles: {s_code} | Playmate: {p_code}) [{elapsed}s]")
        return ep_record

    def process_drama_archive(self, drama_item: Dict[str, Any], current_idx: int, total_dramas: int) -> bool:
        """Processes a single drama archive and all its single episodes."""
        url = drama_item["kdramalover_url"]
        clean_name = drama_item.get("clean_title") or clean_title(drama_item.get("raw_title", ""))
        progress_bar = AsciiProgress.bar(current_idx, total_dramas, width=25)

        safe_print("\n" + "=" * 80)
        safe_print(f"🎬 DRAMA [{current_idx}/{total_dramas}] {progress_bar}")
        safe_print(f"📌 Title : {clean_name}")
        safe_print(f"🔗 URL   : {url}")
        safe_print("=" * 80)

        t_start = time.time()

        # Step 1: TMDB Metadata
        safe_print("  [*] Resolving TMDB metadata...")
        try:
            tmdb_meta = resolve_tmdb(clean_name)
            tmdb_id = tmdb_meta["tmdb_id"]
            safe_print(f"  [+] TMDB ID: {tmdb_id} | Title: {tmdb_meta['title']} | Rating: {tmdb_meta['rating']} | Total Eps: {tmdb_meta['total_episodes']}")
        except Exception as e:
            safe_print(f"  [!] TMDB lookup failed: {e}")
            return False

        # Register initial drama row in SQLite
        initial_drama = {
            "tmdb_id": tmdb_id,
            "title": tmdb_meta["title"],
            "clean_title": clean_name,
            "media_type": "tv",
            "category": "hi-asian",
            "audio": ["Hindi", "Korean"],
            "quality": "1080p",
            "overview": tmdb_meta["overview"],
            "poster": tmdb_meta["poster"],
            "rating": tmdb_meta["rating"],
            "release_year": tmdb_meta["release_year"],
            "total_seasons": 1,
            "total_episodes": tmdb_meta["total_episodes"],
            "genres": tmdb_meta["genres"],
            "tmdb_url": tmdb_meta["tmdb_url"],
            "kdramalover_url": url,
            "seasons": [{"season_number": 1, "name": "Season 1", "episodes": []}]
        }
        self.db.upsert_drama(initial_drama)

        # Step 2: Extract Single Episode Archive Link
        safe_print("  [*] Finding target archive link (1080p -> 720p -> 480p)...")
        try:
            label, archive_url = self.resolver.get_target_archive_url(url, quality="1080p")
            safe_print(f"  [+] Archive: [{label}] -> {archive_url}")
            if "720p" in label.lower():
                initial_drama["quality"] = "720p"
            elif "480p" in label.lower():
                initial_drama["quality"] = "480p"
            else:
                initial_drama["quality"] = "1080p"
            self.db.upsert_drama(initial_drama)
        except Exception as e:
            safe_print(f"  [!] Failed to extract archive URL: {e}")
            self.db.set_crawler_status(url, "archive_unavailable", tmdb_id=tmdb_id)
            self.db.add_quarantine(
                tmdb_id=tmdb_id,
                drama_title=clean_name,
                episode_number=0,
                provider_missing="archive",
                failure_code="NO_ARCHIVE_URL",
                direct_url_attempted=url
            )
            self.stats["dramas_failed"] = self.stats.get("dramas_failed", 0) + 1
            return False

        # Step 3: Extract Episode List
        safe_print("  [*] Extracting episode download links from archive...")
        try:
            episodes_raw = self.resolver.get_all_episodes(archive_url)
            total_found = len(episodes_raw)
            safe_print(f"  [+] Episodes found in archive: {total_found}")
            if total_found == 0:
                raise ValueError("Zero episodes found in archive HTML")
        except Exception as e:
            safe_print(f"  [!] Failed to parse archive episodes: {e}")
            self.db.set_crawler_status(url, "episodes_unavailable", tmdb_id=tmdb_id)
            self.db.add_quarantine(
                tmdb_id=tmdb_id,
                drama_title=clean_name,
                episode_number=0,
                provider_missing="archive",
                failure_code="NO_EPISODES_FOUND",
                direct_url_attempted=archive_url
            )
            self.stats["dramas_failed"] = self.stats.get("dramas_failed", 0) + 1
            return False

        if not episodes_raw:
            safe_print("  [!] No episodes extracted. Skipping.")
            return False

        if self.limit_eps and self.limit_eps > 0:
            episodes_raw = episodes_raw[:self.limit_eps]
            safe_print(f"  [*] Processing limited to first {len(episodes_raw)} episode(s).")

        # Step 4: Parallel Episode Processing Pool
        curated_episodes = []
        safe_print(f"\n  --- Uploading {len(episodes_raw)} Episode(s) (Concurrency: {self.workers}) ---")

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = {
                executor.submit(self.process_single_episode, ep, tmdb_id, clean_name, 1, len(episodes_raw)): ep
                for ep in episodes_raw
            }
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res:
                        curated_episodes.append(res)
                except Exception as e:
                    safe_print(f"  [!] Episode worker error: {e}")

        # Step 5: Update Full Drama Record
        curated_episodes.sort(key=lambda x: x.get("episode_number", 0))
        duration = round(time.time() - t_start, 1)

        final_drama = {
            **initial_drama,
            "total_episodes": len(curated_episodes),
            "metrics": {
                "total_duration_sec": duration,
                "episodes_processed": len(curated_episodes)
            },
            "seasons": [{
                "season_number": 1,
                "name": "Season 1",
                "episodes": curated_episodes
            }]
        }
        self.db.upsert_drama(final_drama)
        self.json_repo.save_drama(final_drama)
        self.db.set_crawler_status(url, "ingested", tmdb_id=tmdb_id)

        safe_print(f"  └─ [✓ COMPLETED] {clean_name} ({len(curated_episodes)} eps) in {duration}s")
        self.stats["dramas_processed"] += 1
        return True

    def run(
        self,
        max_pages: int = 5,
        limit_dramas: Optional[int] = None,
        single_url: Optional[str] = None,
        scan_all: bool = False,
        category: str = "korean-drama"
    ):
        """Main batch execution loop."""
        print_banner()
        self.init_folders()

        drama_list = []
        if single_url:
            raw = single_url.strip().rstrip("/").split("/")[-1].replace("-", " ")
            drama_list = [{
                "kdramalover_url": single_url,
                "raw_title": raw.title(),
                "clean_title": clean_title(raw)
            }]
        else:
            # 1. Fetch pending items already in SQLite
            queue_items = self.db.list_crawler_items(category=category, limit=500)
            pending_items = [
                it for it in queue_items
                if it.get("status") in ("pending", "update_available")
                and "english" not in it.get("kdramalover_url", "").lower()
                and "english" not in it.get("raw_title", "").lower()
                and ("hindi" in it.get("kdramalover_url", "").lower() or "hindi" in it.get("raw_title", "").lower())
            ]

            # 2. If scan_all or not enough pending items, crawl the requested pages!
            pages_to_scan = 38 if (scan_all and category == "korean-drama") else (16 if (scan_all and category == "chinese-drama") else max_pages)
            if scan_all or not pending_items or (limit_dramas and len(pending_items) < limit_dramas) or max_pages > 1:
                label = "Korean" if "korean" in category else "Chinese"
                safe_print(f"\n[*] Scanning KDramaLover {label} pages (1 to {pages_to_scan}) for fresh Hindi-dubbed dramas...")
                self.discover_dramas(category=category, max_pages=pages_to_scan)
                # Re-query all pending items after discovery
                queue_items = self.db.list_crawler_items(category=category, limit=500)
                pending_items = [
                    it for it in queue_items
                    if it.get("status") in ("pending", "update_available")
                    and "english" not in it.get("kdramalover_url", "").lower()
                    and "english" not in it.get("raw_title", "").lower()
                    and ("hindi" in it.get("kdramalover_url", "").lower() or "hindi" in it.get("raw_title", "").lower())
                ]

            safe_print(f"\n[*] Loaded {len(pending_items)} pending Hindi-dubbed Drama(s) from queue.")
            drama_list = pending_items

        # Deduplicate and filter: Only Hindi Dubbed
        final_list = []
        seen_urls = set()
        for d in drama_list:
            url = d.get("kdramalover_url", "")
            raw_title = d.get("raw_title", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            if "english" in url.lower() or "english" in raw_title.lower():
                continue
            if "hindi" not in url.lower() and "hindi" not in raw_title.lower():
                continue

            status = d.get("status")
            if status == "ingested" and not self.force:
                self.stats["dramas_skipped"] += 1
                continue
            if status in ("archive_unavailable", "skipped_non_hindi") and not self.force:
                continue
            final_list.append(d)

        if limit_dramas and limit_dramas > 0:
            final_list = final_list[:limit_dramas]

        total = len(final_list)
        label = "Korean" if "korean" in category else "Chinese"
        safe_print(f"\n[*] Ready to ingest {total} {label} Drama(s) with {self.workers} worker thread(s)...")

        if total == 0:
            safe_print(f"[=] All discovered {label} dramas are already ingested or processed! Use --all or --pages to scan deeper, or --force to re-process.")
            return

        for idx, item in enumerate(final_list, start=1):
            try:
                self.process_drama_archive(item, idx, total)
            except KeyboardInterrupt:
                safe_print("\n[!] User interrupted batch execution. Exiting safely...")
                break
            except Exception as e:
                safe_print(f"\n[!] Unexpected error processing {item.get('kdramalover_url')}: {e}")
                time.sleep(2)

        self.print_summary()

    def print_summary(self):
        total_time = round(time.time() - self.stats["start_time"], 1)
        safe_print("\n" + "=" * 80)
        safe_print("📊 BATCH DRAMA INGESTION SUMMARY")
        safe_print("=" * 80)
        safe_print(f" • Total Time Elapsed     : {total_time}s ({round(total_time/60, 1)}m)")
        safe_print(f" • Dramas Completed       : {self.stats['dramas_processed']}")
        safe_print(f" • Dramas Skipped         : {self.stats['dramas_skipped']}")
        safe_print(f" • Dramas Failed          : {self.stats['dramas_failed']}")
        safe_print(f" • Episodes Uploaded      : {self.stats['episodes_uploaded']}")
        safe_print(f" • Episodes From Cache    : {self.stats['episodes_cached']}")
        safe_print(f" • Episodes Quarantined   : {self.stats['episodes_quarantined']}")
        safe_print(f" • Episodes Failed        : {self.stats['episodes_failed']}")
        safe_print("=" * 80)
        safe_print("✓ All processed data safely saved to SQLite (data/hindi_asian.db) & Turso-ready.")
        safe_print("✓ Streams are ready for on-the-fly M3U8 resolution via /v1/hi-asian/{tmdb_id}/resolve-m3u8")
        safe_print("=" * 80 + "\n")


def display_quarantine(db: SqliteDatabase):
    """CLI viewer for quarantined / failed episode tasks."""
    items = db.list_quarantine_items(limit=100)
    print("=" * 90)
    print("⚠️  INGESTION QUARANTINE & FAILURE QUEUE")
    print("=" * 90)
    if not items:
        print("✓ All clean! Zero quarantined failures found.")
        print("=" * 90)
        return

    print(f"{'TMDB ID':<8} | {'DRAMA TITLE':<24} | {'EP':<4} | {'MISSING':<8} | {'FAILURE CODE':<30} | {'STATUS'}")
    print("-" * 90)
    for it in items:
        title = (it.get("drama_title") or "Unknown")[:24]
        print(f"{it['tmdb_id']:<8} | {title:<24} | E{it['episode_number']:02d} | {it['provider_missing']:<8} | {it['failure_code']:<30} | {it['status']}")
    print("=" * 90)
    print("Tip: Use --retry-quarantine to automatically re-attempt resolving all quarantined episodes.")
    print("Tip: Use --override --tmdb <ID> --ep <N> --vidara <CODE> to manually fix any quarantined episode.")
    print("=" * 90)


def display_stats(db: SqliteDatabase):
    """Print complete storage, queue, and provider coverage analytics."""
    with db.get_connection() as conn:
        d_count = conn.execute("SELECT COUNT(*) FROM dramas").fetchone()[0]
        ep_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        vid_cnt = conn.execute("SELECT COUNT(*) FROM episodes WHERE host_vidara IS NOT NULL").fetchone()[0]
        sf_cnt = conn.execute("SELECT COUNT(*) FROM episodes WHERE host_savefiles IS NOT NULL").fetchone()[0]
        pm_cnt = conn.execute("SELECT COUNT(*) FROM episodes WHERE host_playmate IS NOT NULL").fetchone()[0]
        valid_cnt = conn.execute("SELECT COUNT(*) FROM episodes WHERE host_vidara IS NOT NULL OR host_savefiles IS NOT NULL OR host_playmate IS NOT NULL").fetchone()[0]
        dual_cnt = conn.execute("""
            SELECT COUNT(*) FROM episodes 
            WHERE (CASE WHEN host_vidara IS NOT NULL THEN 1 ELSE 0 END + 
                   CASE WHEN host_savefiles IS NOT NULL THEN 1 ELSE 0 END + 
                   CASE WHEN host_playmate IS NOT NULL THEN 1 ELSE 0 END) >= 2
        """).fetchone()[0]
        
        q_count = conn.execute("SELECT COUNT(*) FROM ingest_quarantine WHERE status IN ('pending_retry', 'manual_required')").fetchone()[0]
        q_breakdown = conn.execute("SELECT failure_code, COUNT(*) as c FROM ingest_quarantine WHERE status IN ('pending_retry', 'manual_required') GROUP BY failure_code").fetchall()
        
        queue_rows = conn.execute("SELECT category, status, COUNT(*) as c FROM crawler_queue GROUP BY category, status").fetchall()

    print("=" * 80)
    print("📊 HINDI ASIAN DRAMA STORAGE & INGESTION STATS")
    print("=" * 80)
    print(f" • Total Dramas Stored       : {d_count}")
    print(f" • Total Episodes Ingested   : {ep_count}")
    if ep_count > 0:
        print(f" • Episodes with Working HLS : {valid_cnt}/{ep_count} ({valid_cnt * 100 // ep_count}%)")
        print(f" • Dual/Triple Redundancy    : {dual_cnt}/{ep_count} ({dual_cnt * 100 // ep_count}%)")
        print(f"   ├─ Playmate (Primary/HLS) : {pm_cnt}/{ep_count} ({pm_cnt * 100 // ep_count}%)")
        print(f"   ├─ Vidara (Primary HLS)   : {vid_cnt}/{ep_count} ({vid_cnt * 100 // ep_count}%)")
        print(f"   └─ SaveFiles (Backup HLS) : {sf_cnt}/{ep_count} ({sf_cnt * 100 // ep_count}%)")
    print("-" * 80)
    print(f" • Quarantined Episode Tasks : {q_count}")
    for qb in q_breakdown:
        print(f"   └─ {qb['failure_code']}: {qb['c']} episode(s)")
    print("-" * 80)
    print(" • Crawler Queue by Category & Status:")
    for qr in queue_rows:
        print(f"   └─ [{qr['category']}] {qr['status']}: {qr['c']} drama(s)")
    print("=" * 80)


def retry_quarantine(db: SqliteDatabase, workers: int = 6):
    """Re-attempts ingestion for all dramas that have quarantined/failed episodes."""
    print("=" * 80)
    print("🔄 RETRYING INGESTION FOR QUARANTINED EPISODES")
    print("=" * 80)
    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT q.tmdb_id, q.drama_title, 
                   COALESCE(d.kdramalover_url, c.kdramalover_url) as url,
                   COUNT(q.id) as quarantined_count
            FROM ingest_quarantine q
            LEFT JOIN dramas d ON d.tmdb_id = q.tmdb_id
            LEFT JOIN crawler_queue c ON c.tmdb_id = q.tmdb_id
            WHERE q.status IN ('pending_retry', 'manual_required')
            GROUP BY q.tmdb_id, q.drama_title
            ORDER BY quarantined_count DESC
        """).fetchall()

    if not rows:
        print("✓ No pending quarantined episodes found! All clear.")
        return

    print(f"[*] Found {len(rows)} drama(s) with quarantined episodes to retry.")
    ingestor = KoreanDramaBatchIngestor(workers=workers, force=False)
    ingestor.init_folders()

    total_dramas = len(rows)
    for idx, r in enumerate(rows, start=1):
        url = r["url"]
        if not url:
            print(f"[!] Cannot retry TMDB {r['tmdb_id']} ({r['drama_title']}): No KDramaLover URL found.")
            continue
        drama_item = {
            "kdramalover_url": url,
            "clean_title": r["drama_title"],
            "raw_title": r["drama_title"]
        }
        try:
            ingestor.process_drama_archive(drama_item, idx, total_dramas)
        except KeyboardInterrupt:
            print("\n[!] User interrupted quarantine retry.")
            break
        except Exception as e:
            print(f"[!] Error retrying drama {r['drama_title']}: {e}")

    ingestor.print_summary()


def main():
    parser = argparse.ArgumentParser(description="KDramaLover Asian Drama Batch Ingestion Service")
    parser.add_argument("--pages", type=int, default=5, help="Number of category pages to crawl (default: 5)")
    parser.add_argument("--all", action="store_true", help="Crawl all available pages of category (all 38 Korean or 16 Chinese pages)")
    parser.add_argument("--category", type=str, default="korean-drama", choices=["korean-drama", "chinese-drama", "korean", "chinese"], help="Category to ingest (default: korean-drama)")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent worker threads for episode processing (default: 6)")
    parser.add_argument("--limit-dramas", type=int, default=None, help="Limit number of dramas to process")
    parser.add_argument("--limit-eps", type=int, default=None, help="Limit number of episodes per drama")
    parser.add_argument("--drama-url", type=str, default=None, help="Process single specific drama URL")
    parser.add_argument("--force", action="store_true", help="Force re-upload even if already cached in SQLite")
    parser.add_argument("--stats", action="store_true", help="Display overall database statistics and provider coverage")
    parser.add_argument("--quarantine", action="store_true", help="Display list of quarantined/failed episodes")
    parser.add_argument("--retry-quarantine", action="store_true", help="Automatically retry all quarantined episodes with improved resolvers")
    parser.add_argument("--override", action="store_true", help="Manually supply links for an episode")
    parser.add_argument("--tmdb", type=int, default=None, help="TMDB ID for override")
    parser.add_argument("--ep", type=int, default=None, help="Episode number for override")
    parser.add_argument("--vidara", type=str, default=None, help="Vidara filecode or embed URL for override")
    parser.add_argument("--savefiles", type=str, default=None, help="SaveFiles filecode or URL for override")
    parser.add_argument("--playmate", type=str, default=None, help="Playmate filecode or URL for override")
    parser.add_argument("--byse", type=str, default=None, help="Legacy Byse filecode or embed URL for override")
    args = parser.parse_args()

    db = SqliteDatabase()

    if args.stats:
        display_stats(db)
        return

    if args.quarantine:
        display_quarantine(db)
        return

    if args.retry_quarantine:
        retry_quarantine(db, workers=args.workers)
        return

    if args.override:
        if not args.tmdb or not args.ep:
            print("[!] Error: --tmdb and --ep are required when using --override")
            sys.exit(1)
        res = db.manual_override_episode(
            tmdb_id=args.tmdb,
            season_number=1,
            episode_number=args.ep,
            host_vidara=args.vidara,
            host_byse=args.savefiles or args.byse
        )
        if args.savefiles:
            db.update_episode_savefiles(args.tmdb, 1, args.ep, args.savefiles)
        if args.playmate:
            db.update_episode_playmate(args.tmdb, 1, args.ep, args.playmate)
        print(f"[+] Manual Override Successful! Episode {args.ep} of TMDB {args.tmdb} is now resolved.")
        print(json.dumps(res, indent=2))
        return

    cat = "chinese-drama" if "chinese" in args.category else "korean-drama"
    ingestor = KoreanDramaBatchIngestor(
        workers=args.workers,
        force=args.force,
        limit_eps=args.limit_eps
    )
    ingestor.run(
        max_pages=args.pages,
        limit_dramas=args.limit_dramas,
        single_url=args.drama_url,
        scan_all=args.all,
        category=cat
    )


if __name__ == "__main__":
    main()
