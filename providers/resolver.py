"""
Unified 3-Host Stream Resolver (SaveFiles, Playmate, Vidara)
============================================================
Provides unified, high-speed on-the-fly M3U8 stream resolution with automatic
failover across SaveFiles, Playmate, and Vidara.

Usage:
    from providers.resolver import (
        resolve_stream,
        resolve_savefiles_m3u8,
        resolve_playmate_m3u8,
        resolve_vidara_m3u8,
        resolve_drama_streams
    )
"""

import re
import requests
from typing import Optional, Dict, Any, List

from providers.playmate import PlaymateProvider
from providers.savefiles import SaveFilesProvider
from providers.vidara import VIDARA_API_KEY

VIDARA_STREAM_URL = "https://vidarae.live/api/stream"
VIDARA_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def extract_filecode(url_or_code: str) -> Optional[str]:
    """Cleanly extract filecode identifier from a URL or raw string."""
    if not url_or_code:
        return None
    cleaned = str(url_or_code).strip().rstrip("/")
    code = cleaned.split("/")[-1].split("?")[0].split(".")[0]
    return code if len(code) >= 4 else None


def resolve_playmate_m3u8(filecode_or_url: str, timeout: int = 8) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master M3U8 on the fly via Playmate (/api/s).
    Ultra-fast (~150ms), open CORS, zero browser emulation.
    """
    code = extract_filecode(filecode_or_url)
    if not code:
        return None
    return PlaymateProvider.resolve_m3u8(code, timeout=timeout)


def resolve_savefiles_m3u8(filecode_or_url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master M3U8 on the fly via SaveFiles.
    Open CORS, preserves Hindi + Korean multi-audio and subtitles.
    """
    code = extract_filecode(filecode_or_url)
    if not code:
        return None
    return SaveFilesProvider.resolve_m3u8(code, timeout=timeout)


def resolve_vidara_m3u8(filecode_or_url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
    """
    Dynamically resolve fresh master M3U8 on the fly via Vidara stream API.
    """
    code = extract_filecode(filecode_or_url)
    if not code:
        return None

    headers = {
        "Origin": "https://vidarae.live",
        "Referer": f"https://vidarae.live/e/{code}",
        "User-Agent": VIDARA_USER_AGENT,
        "Content-Type": "application/json"
    }
    payload = {
        "filecode": code,
        "device": "web"
    }

    try:
        r = requests.post(VIDARA_STREAM_URL, json=payload, headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None

        data = r.json()
        streaming_url = data.get("streaming_url")
        if not streaming_url:
            return None

        return {
            "filecode": code,
            "provider": "vidara",
            "type": "hls",
            "stream_url": streaming_url,
            "canonical_url": f"https://vidara.so/v/{code}",
            "audio_tracks": ["Hindi", "Korean"],
            "subtitles": data.get("subtitles", []),
            "poster": data.get("thumbnail"),
            "title": data.get("title"),
            "headers": {
                "Origin": "https://vidarae.live",
                "Referer": f"https://vidarae.live/e/{code}"
            }
        }
    except Exception:
        return None


def resolve_stream(
    hosts: Dict[str, Any],
    priority: List[str] = None,
    timeout: int = 8
) -> Optional[Dict[str, Any]]:
    """
    Resolve playable stream with instant failover across the 3 supported hosts.

    Default priority:
      1. 'savefiles' - Native multi-audio, high bandwidth, open CORS.
      2. 'playmate'  - Ultra-fast ~150ms resolution, 1080p verified, open CORS.
      3. 'vidara'    - Proven fallback provider.

    Args:
        hosts: dict mapping provider name to code/url, e.g.
               {"savefiles": "p87tgt...", "playmate": "1w5LAU...", "vidara": "921f8f..."}
        priority: ordered list of provider names to try.
        timeout: max wait per host attempt.

    Returns:
        Dict with active stream metadata, or None if all providers fail.
    """
    if priority is None:
        priority = ["savefiles", "playmate", "vidara"]

    resolvers = {
        "savefiles": resolve_savefiles_m3u8,
        "playmate": resolve_playmate_m3u8,
        "vidara": resolve_vidara_m3u8,
    }

    for prov in priority:
        val = hosts.get(prov) or hosts.get(f"host_{prov}")
        if not val or val in ("N/A", "None", ""):
            continue

        resolver_fn = resolvers.get(prov)
        if not resolver_fn:
            continue

        try:
            res = resolver_fn(val, timeout=timeout)
            if res and res.get("stream_url"):
                return res
        except Exception:
            continue

    return None


def resolve_drama_streams(tmdb_id: int, episode_filter: Optional[int] = None) -> Dict[str, Any]:
    """
    Full resolution for a drama from SQLite database.
    Queries episodes and returns dynamic stream URLs for each episode.
    """
    from storage.sqlite_db import SqliteDatabase
    db = SqliteDatabase()
    drama = db.get_drama(tmdb_id)
    if not drama:
        raise ValueError(f"Drama with TMDB ID {tmdb_id} not found.")

    episodes = []
    seasons = drama.get("seasons", [])
    for s in seasons:
        s_num = s.get("season_number", 1)
        for ep in s.get("episodes", []):
            ep_num = ep.get("episode_number")
            if episode_filter is not None and ep_num != episode_filter:
                continue

            hosts = ep.get("hosts", {})
            stream_info = resolve_stream(hosts)

            episodes.append({
                "season": s_num,
                "episode": ep_num,
                "title": ep.get("title", f"Episode {ep_num}"),
                "resolved": stream_info is not None,
                "active_host": stream_info.get("provider") if stream_info else None,
                "stream_url": stream_info.get("stream_url") if stream_info else None,
                "audio_tracks": stream_info.get("audio_tracks", ["Hindi"]) if stream_info else ["Hindi"],
                "subtitles": stream_info.get("subtitles", []) if stream_info else [],
                "poster": stream_info.get("poster") if stream_info else None,
                "headers": stream_info.get("headers", {}) if stream_info else {},
                "available_hosts": {k: v for k, v in hosts.items() if v and v != "N/A"}
            })

    return {
        "tmdb_id": tmdb_id,
        "title": drama.get("title"),
        "total_episodes": len(episodes),
        "resolved_count": sum(1 for e in episodes if e["resolved"]),
        "episodes": episodes
    }
