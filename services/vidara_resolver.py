"""
Vidara Encoding Status Tracker & Direct M3U8 Stream Resolver
"""

import requests
import json
from typing import Optional, Dict, Any, List
from storage.sqlite_db import SqliteDatabase
from storage.repository import DramaRepository

VIDARA_API_KEY = "cc6630108e04a26c58513a923b643e1d30e5c6295b9052100ab4e0578d13aa32"
VIDARA_INFO_URL = "https://api.vidara.so/v1/video/info"
VIDARAE_STREAM_URL = "https://vidarae.live/api/stream"


def extract_filecode(vidara_url: str) -> Optional[str]:
    """Extract filecode from a Vidara link (e.g. https://vidara.so/v/921f8f2e78a0 -> 921f8f2e78a0)."""
    if not vidara_url:
        return None
    clean = vidara_url.strip().rstrip("/")
    return clean.split("/")[-1]


def check_encoding_status(filecode: str, api_key: str = VIDARA_API_KEY) -> Dict[str, Any]:
    """
    Query Vidara API for video status.
    Returns:
      {
        "filecode": str,
        "status": "active" | "pending" | "error" | "not_found",
        "duration": "01:04:00" | None,
        "thumbnail": str | None,
        "file_active": 1 | 0
      }
    """
    try:
        r = requests.get(
            VIDARA_INFO_URL,
            params={"api_key": api_key, "filecode": filecode},
            timeout=12
        )
        if r.status_code == 200:
            data = r.json()
            result = data.get("result", [{}])
            if result and isinstance(result, list) and len(result) > 0:
                item = result[0]
                status = item.get("status", "pending")
                return {
                    "filecode": filecode,
                    "status": status,
                    "duration": item.get("video_length"),
                    "thumbnail": item.get("player_img"),
                    "file_active": item.get("file_active", 0)
                }
        return {"filecode": filecode, "status": "unknown", "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"filecode": filecode, "status": "error", "error": str(e)}


def resolve_direct_m3u8(filecode: str) -> Optional[Dict[str, Any]]:
    """
    Extract the direct master.m3u8 streaming URL, origin, and referer from Vidara.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Origin": "https://vidarae.live",
        "Referer": f"https://vidarae.live/e/{filecode}",
        "Content-Type": "application/json"
    }
    payload = {
        "filecode": filecode,
        "device": "web"
    }

    try:
        r = requests.post(VIDARAE_STREAM_URL, headers=headers, json=payload, timeout=15)
        if r.status_code == 200:
            data = r.json()
            streaming_url = data.get("streaming_url")
            if streaming_url:
                return {
                    "m3u8": streaming_url,
                    "origin": "https://vidarae.live",
                    "referer": f"https://vidarae.live/e/{filecode}",
                    "subtitles": data.get("subtitles", []),
                    "thumbnail": data.get("thumbnail"),
                    "status": "ready"
                }
    except Exception as e:
        print(f"[!] Error resolving m3u8 for {filecode}: {e}")
    return None


def resolve_drama_vidara_m3u8(tmdb_id: int) -> Dict[str, Any]:
    """
    For a given drama, checks all episodes in SQLite.
    For each episode where Vidara is encoded (status='active'), resolves the direct m3u8
    and persists it into both SQLite and JSON cache.
    """
    db = SqliteDatabase()
    json_repo = DramaRepository()
    drama = db.get_drama(tmdb_id)
    if not drama:
        raise ValueError(f"Drama with TMDB ID {tmdb_id} not found in database.")

    report = {
        "tmdb_id": tmdb_id,
        "title": drama.get("title"),
        "total_episodes": len(drama.get("seasons", [{}])[0].get("episodes", [])),
        "active_and_resolved": 0,
        "pending_encoding": 0,
        "episodes": []
    }

    seasons = drama.get("seasons", [])
    for season in seasons:
        season_num = season.get("season_number", 1)
        for ep in season.get("episodes", []):
            ep_num = ep.get("episode_number")
            vidara_host = ep.get("hosts", {}).get("vidara", "")
            filecode = extract_filecode(vidara_host)

            if not filecode:
                continue

            existing_m3u8 = ep.get("direct", {}).get("vidara", {}).get("m3u8")
            if existing_m3u8:
                report["active_and_resolved"] += 1
                report["episodes"].append({
                    "episode_number": ep_num,
                    "filecode": filecode,
                    "vidara_status": "active",
                    "duration": ep.get("direct", {}).get("vidara", {}).get("duration"),
                    "m3u8_resolved": True,
                    "m3u8_url": existing_m3u8
                })
                continue

            # Check status on Vidara
            stat = check_encoding_status(filecode)
            is_active = (stat.get("status") == "active")

            ep_summary = {
                "episode_number": ep_num,
                "filecode": filecode,
                "vidara_status": stat.get("status"),
                "duration": stat.get("duration"),
                "m3u8_resolved": False
            }

            if is_active:
                m3u8_data = resolve_direct_m3u8(filecode)
                if m3u8_data:
                    m3u8_data["duration"] = stat.get("duration")
                    ep["direct"]["vidara"] = m3u8_data
                    ep_summary["m3u8_resolved"] = True
                    ep_summary["m3u8_url"] = m3u8_data["m3u8"]
                    report["active_and_resolved"] += 1

                    # Update database
                    db.upsert_episode(
                        tmdb_id=tmdb_id,
                        season_number=season_num,
                        episode_number=ep_num,
                        title=ep.get("title", f"Episode {ep_num}"),
                        host_vidara=vidara_host,
                        host_byse=ep.get("hosts", {}).get("byse"),
                        direct_vidara=m3u8_data,
                        direct_byse=ep.get("direct", {}).get("byse"),
                        sources_used=ep.get("sources_used")
                    )
            else:
                report["pending_encoding"] += 1

            report["episodes"].append(ep_summary)

    # Re-save complete drama with enriched episodes
    db.upsert_drama(drama)
    json_repo.save_drama(drama)

    return report
