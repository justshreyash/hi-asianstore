"""
Standalone Hindi Stream Service
===============================
Directly queries the database (SQLite / Turso compatible) to check if Hindi dub
is available for a given TMDB ID and episode, and dynamically resolves the fresh
on-the-fly Master M3U8 streaming URL via Vidara.

Can be imported into any backend or run standalone.
"""

import os
import re
import json
import sqlite3
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

# Locate the database file (supports local relative path, parent dir, or env var)
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "hindi_asian.db"
DB_PATH = Path(os.getenv("HINDI_DB_PATH", str(DEFAULT_DB_PATH)))

VIDARA_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def get_db_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    """Connect to SQLite database in WAL mode."""
    if not db_path.exists():
        # Also check current directory
        local_fallback = Path(__file__).resolve().parent / "hindi_asian.db"
        if local_fallback.exists():
            db_path = local_fallback
        else:
            raise FileNotFoundError(f"Hindi Asian database not found at: {db_path}")

    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    return conn


def extract_filecode(url_or_code: str) -> Optional[str]:
    """Extract alphanumeric filecode from Vidara / Byse URL or raw string."""
    if not url_or_code:
        return None
    url_or_code = str(url_or_code).strip().rstrip("/")
    code = url_or_code.split("/")[-1].split("?")[0].split(".")[0]
    return code if len(code) >= 6 else None


def resolve_savefiles_m3u8(filecode: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master.m3u8 stream on the fly via SaveFiles.
    Returns: dict with m3u8 url, audio tracks (Hindi/Korean), subtitles, and poster.
    """
    clean_code = extract_filecode(filecode)
    if not clean_code:
        return None

    page_url = f"https://savefiles.com/{clean_code}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        r = requests.get(page_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None

        match = re.search(r'["\'](https?://[^\s"\']+\.m3u8[^\s"\']*)["\']', r.text)
        if not match:
            return None

        m3u8_url = match.group(1)
        return {
            "filecode": clean_code,
            "active_host": "savefiles",
            "type": "hls",
            "m3u8": m3u8_url,
            "canonical_url": page_url,
            "headers": {
                "User-Agent": headers["User-Agent"]
            },
            "audio_tracks": ["Hindi", "Korean"],
            "subtitles": ["English"],
            "poster": f"https://img.savefiles.com/{clean_code}_xt.jpg",
            "title": f"SaveFiles Stream ({clean_code})"
        }
    except Exception as e:
        print(f"[!] SaveFiles resolution error for {clean_code}: {e}")
        return None


def resolve_playmate_m3u8(filecode: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master M3U8 on the fly via Playmate internal API (/api/s).
    Ultra-fast (~150ms), open CORS, zero scraping, zero browser emulation.
    """
    clean_code = extract_filecode(filecode)
    if not clean_code:
        return None

    try:
        from providers.playmate import PlaymateProvider
        res = PlaymateProvider.resolve_m3u8(clean_code)
        if not res or not res.get("stream_url"):
            return None

        return {
            "filecode": clean_code,
            "active_host": "playmate",
            "type": "hls",
            "m3u8": res["stream_url"],
            "canonical_url": res.get("canonical_url", f"https://playmate.to/embed/{clean_code}"),
            "headers": res.get("headers", {}),
            "audio_tracks": res.get("audio_tracks", ["Hindi", "Korean"]),
            "subtitles": res.get("subtitles", []),
            "poster": res.get("poster"),
            "title": res.get("title") or f"Playmate Stream ({clean_code})"
        }
    except Exception as e:
        print(f"[!] Playmate resolution error for {clean_code}: {e}")
        return None


def resolve_byse_stream(filecode: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve Byse playback stream on the fly.
    Provides verified dynamic embed URL with title and poster.
    """
    clean_code = extract_filecode(filecode)
    if not clean_code:
        return None

    embed_domain = "bysefujedu.com"
    try:
        from curl_cffi import requests as cureq
        s = cureq.Session(impersonate="chrome124")
        r = s.get("https://api.byse.sx/get/domain?key=48397uaa9vk8w0su5yrjw", timeout=5)
        if r.status_code == 200:
            dom = r.json().get("embed_domain")
            if dom:
                embed_domain = dom
    except Exception:
        pass

    embed_url = f"https://{embed_domain}/e/{clean_code}"
    canonical_embed = f"https://byse.sx/e/{clean_code}"

    return {
        "filecode": clean_code,
        "active_host": "byse",
        "type": "iframe",
        "embed_url": embed_url,
        "canonical_embed_url": canonical_embed,
        "m3u8": None,
        "headers": {
            "Origin": f"https://{embed_domain}",
            "Referer": embed_url
        },
        "audio_tracks": ["Hindi", "Korean"],
        "poster": f"https://img-place.com/{clean_code}.jpg"
    }


def resolve_vidara_m3u8(filecode: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master.m3u8 stream on the fly via Vidara stream API.
    Returns: dict with m3u8 url, active tokens, origin, referer, audio tracks, and subs.
    """
    clean_code = extract_filecode(filecode)
    if not clean_code:
        return None

    api_url = "https://vidarae.live/api/stream"
    headers = {
        "Origin": "https://vidarae.live",
        "Referer": f"https://vidarae.live/e/{clean_code}",
        "User-Agent": VIDARA_USER_AGENT,
        "Content-Type": "application/json"
    }
    payload = {
        "filecode": clean_code,
        "device": "web"
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=12)
        if resp.status_code != 200:
            return None

        data = resp.json()
        streaming_url = data.get("streaming_url")
        if not streaming_url:
            return None

        return {
            "filecode": clean_code,
            "active_host": "vidara",
            "type": "hls",
            "m3u8": streaming_url,
            "headers": {
                "Origin": "https://vidarae.live",
                "Referer": f"https://vidarae.live/e/{clean_code}"
            },
            "audio_tracks": ["Hindi", "Korean"],
            "subtitles": data.get("subtitles", []),
            "thumbnail": data.get("thumbnail"),
            "title": data.get("title")
        }
    except Exception as e:
        print(f"[!] Resolution error for {clean_code}: {e}")
        return None


class HindiStreamService:
    """Standalone service to check availability and get on-the-fly M3U8 streams."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH

    def list_dramas(self) -> List[Dict[str, Any]]:
        """List all dramas currently available with Hindi Dubbing."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("""
                SELECT tmdb_id, title, clean_title, media_type, category, audio,
                       poster, rating, release_year, total_seasons, total_episodes
                FROM dramas
                ORDER BY updated_at DESC;
            """).fetchall()
            return [dict(r) for r in rows]

    def check_availability(self, tmdb_id: int, season: int = 1, episode: int = 1) -> Dict[str, Any]:
        """
        Fast lookup: checks if Hindi dubbed version is available for TMDB ID & episode.
        """
        with get_db_connection(self.db_path) as conn:
            # 1. Check drama exists
            drama = conn.execute(
                "SELECT tmdb_id, title, clean_title, poster, audio FROM dramas WHERE tmdb_id = ?;",
                (tmdb_id,)
            ).fetchone()

            if not drama:
                return {
                    "available": False,
                    "tmdb_id": tmdb_id,
                    "reason": f"Drama (TMDB ID: {tmdb_id}) is not in the Hindi-Asian database."
                }

            # 2. Check episode exists
            ep = conn.execute(
                """
                SELECT id, season_number, episode_number, title, host_vidara, host_savefiles, host_playmate, host_byse
                FROM episodes
                WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?
                """,
                (tmdb_id, season, episode)
            ).fetchone()

            if not ep:
                return {
                    "available": False,
                    "tmdb_id": tmdb_id,
                    "drama_title": drama["clean_title"] or drama["title"],
                    "season": season,
                    "episode": episode,
                    "reason": f"Episode {episode} (Season {season}) has not been added yet."
                }

            v_host = ep["host_vidara"]
            s_host = ep["host_savefiles"] if "host_savefiles" in ep.keys() else None
            p_host = ep["host_playmate"] if "host_playmate" in ep.keys() else None
            b_host = ep["host_byse"]

            v_code = extract_filecode(v_host) if (v_host and "n/a" not in v_host.lower()) else None
            s_code = extract_filecode(s_host) if (s_host and "n/a" not in s_host.lower()) else None
            p_code = extract_filecode(p_host) if (p_host and "n/a" not in p_host.lower()) else None
            b_code = extract_filecode(b_host) if (b_host and "n/a" not in b_host.lower()) else None

            if not (v_code or s_code or p_code or b_code):
                return {
                    "available": False,
                    "tmdb_id": tmdb_id,
                    "drama_title": drama["clean_title"] or drama["title"],
                    "season": season,
                    "episode": episode,
                    "reason": f"Episode {episode} is indexed but video links are not uploaded yet."
                }

            active_host = "savefiles" if s_code else ("playmate" if p_code else ("vidara" if v_code else "byse"))

            return {
                "available": True,
                "tmdb_id": tmdb_id,
                "drama_title": drama["clean_title"] or drama["title"],
                "poster": drama["poster"],
                "audio": drama["audio"] or "Hindi / Korean",
                "season": season,
                "episode": episode,
                "episode_title": ep["title"] or f"Episode {episode}",
                "active_host": active_host,
                "host_vidara": ep["host_vidara"],
                "host_savefiles": s_host,
                "host_playmate": p_host,
                "host_byse": ep["host_byse"],
                "filecode": s_code or p_code or v_code or b_code,
                "status": "ready_to_resolve"
            }

    def resolve_stream(self, tmdb_id: int, season: int = 1, episode: int = 1) -> Dict[str, Any]:
        """
        Check availability and immediately resolve active stream (Vidara HLS M3U8 or SaveFiles HLS M3U8).
        """
        check = self.check_availability(tmdb_id, season, episode)
        if not check.get("available"):
            return check

        v_host = check.get("host_vidara")
        s_host = check.get("host_savefiles")
        p_host = check.get("host_playmate")
        b_host = check.get("host_byse")

        v_code = extract_filecode(v_host) if (v_host and "n/a" not in v_host.lower()) else None
        s_code = extract_filecode(s_host) if (s_host and "n/a" not in s_host.lower()) else None
        p_code = extract_filecode(p_host) if (p_host and "n/a" not in p_host.lower()) else None
        b_code = extract_filecode(b_host) if (b_host and "n/a" not in b_host.lower()) else None

        # 1. Try SaveFiles first (Native Multi-Audio HLS direct M3U8 with CORS *)
        if s_code:
            s_stream = resolve_savefiles_m3u8(s_code)
            if s_stream and s_stream.get("m3u8"):
                return {
                    "success": True,
                    "available": True,
                    "active_host": "savefiles",
                    "type": "hls",
                    "tmdb_id": tmdb_id,
                    "drama_title": check["drama_title"],
                    "poster": check.get("poster"),
                    "season": season,
                    "episode": episode,
                    "episode_title": check.get("episode_title"),
                    "m3u8_url": s_stream["m3u8"],
                    "headers": s_stream["headers"],
                    "audio_tracks": s_stream["audio_tracks"],
                    "subtitles": s_stream.get("subtitles", []),
                    "thumbnail": s_stream.get("poster"),
                    "filecode": s_code,
                    "embed_url": s_stream.get("canonical_url")
                }

        # 2. Try Playmate (Ultra-fast ~150ms resolution, open CORS *)
        if p_code:
            p_stream = resolve_playmate_m3u8(p_code)
            if p_stream and p_stream.get("m3u8"):
                return {
                    "success": True,
                    "available": True,
                    "active_host": "playmate",
                    "type": "hls",
                    "tmdb_id": tmdb_id,
                    "drama_title": check["drama_title"],
                    "poster": check.get("poster"),
                    "season": season,
                    "episode": episode,
                    "episode_title": check.get("episode_title"),
                    "m3u8_url": p_stream["m3u8"],
                    "headers": p_stream["headers"],
                    "audio_tracks": p_stream["audio_tracks"],
                    "subtitles": p_stream.get("subtitles", []),
                    "thumbnail": p_stream.get("poster"),
                    "filecode": p_code,
                    "embed_url": p_stream.get("canonical_url")
                }

        # 3. Try Vidara (HLS direct M3U8 fallback)
        if v_code:
            v_stream = resolve_vidara_m3u8(v_code)
            if v_stream and v_stream.get("m3u8"):
                return {
                    "success": True,
                    "available": True,
                    "active_host": "vidara",
                    "type": "hls",
                    "tmdb_id": tmdb_id,
                    "drama_title": check["drama_title"],
                    "poster": check.get("poster"),
                    "season": season,
                    "episode": episode,
                    "episode_title": check.get("episode_title"),
                    "m3u8_url": v_stream["m3u8"],
                    "headers": v_stream["headers"],
                    "audio_tracks": v_stream["audio_tracks"],
                    "subtitles": v_stream.get("subtitles", []),
                    "thumbnail": v_stream.get("thumbnail"),
                    "filecode": v_code,
                    "embed_url": check.get("host_vidara")
                }

        # 3. Fallback to Byse only if neither Vidara nor SaveFiles resolved
        if b_code:
            b_stream = resolve_byse_stream(b_code)
            if b_stream:
                return {
                    "success": True,
                    "available": True,
                    "active_host": "byse",
                    "type": "iframe",
                    "tmdb_id": tmdb_id,
                    "drama_title": check["drama_title"],
                    "poster": check.get("poster"),
                    "season": season,
                    "episode": episode,
                    "episode_title": check.get("episode_title"),
                    "m3u8_url": None,
                    "embed_url": b_stream["embed_url"],
                    "canonical_embed_url": b_stream.get("canonical_embed_url"),
                    "headers": b_stream["headers"],
                    "audio_tracks": b_stream["audio_tracks"],
                    "filecode": b_code
                }

        return {
            "available": True,
            "status": "encoding_in_progress",
            "message": "Hindi episode is still encoding on video hosts. Please retry in a few moments.",
            **check
        }


# Quick CLI test
if __name__ == "__main__":
    import sys
    tmdb = int(sys.argv[1]) if len(sys.argv) > 1 else 297640
    ep = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    svc = HindiStreamService()
    print(f"[*] Checking TMDB {tmdb} Ep {ep}...")
    res = svc.resolve_stream(tmdb, season=1, episode=ep)
    print(json.dumps(res, indent=2))
