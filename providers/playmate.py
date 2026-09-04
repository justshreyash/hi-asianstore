"""
Playmate API Provider
Documentation: https://playmate.to/api-docs
Base API: https://api.playmate.to
"""

import time
import requests
from typing import Optional, Dict, Any, List

try:
    from config import PLAYMATE_API_KEY
except ImportError:
    PLAYMATE_API_KEY = "deaf804d60034a3e2a42ccf4a0cfd2b8f6ce1f892f00cea2cba52e57dba7d052"
BASE_URL = "https://api.playmate.to"
STREAM_API_URL = "https://playmate.to/api/s"


class PlaymateProvider:
    def __init__(self, api_key: str = PLAYMATE_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        })

    def get_account_info(self) -> Dict[str, Any]:
        """Fetch Playmate account info (username, email, balance, video count)."""
        url = f"{BASE_URL}/account/info"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        return r.json()

    def list_folders(self) -> List[Dict[str, Any]]:
        """List all user folders."""
        url = f"{BASE_URL}/folder/list"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("result", [])

    def create_folder(self, name: str, parent_id: int = 0) -> int:
        """Create a new folder and return its fld_id."""
        url = f"{BASE_URL}/folder/create"
        r = self.session.post(url, params={"key": self.api_key, "name": name, "parent_id": parent_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
        fld_id = data.get("result", {}).get("fld_id")
        if not fld_id:
            raise ValueError(f"Playmate: Failed to create folder '{name}'. Response: {data}")
        return int(fld_id)

    def get_or_create_folder(self, folder_name: str = "hindi-asian") -> int:
        """Find folder by name or create it if not found."""
        try:
            folders = self.list_folders()
            for f in folders:
                if f.get("name", "").lower() == folder_name.lower():
                    return int(f.get("fld_id"))
        except Exception:
            pass
        return self.create_folder(folder_name)

    def upload_url(self, video_url: str, folder_id: Optional[int] = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        Submit a direct video URL for remote upload.
        Returns dict with 'filecode', 'url', 'embed_url', and 'raw_response'.
        """
        if not video_url:
            raise ValueError("Playmate: video_url cannot be empty")

        url = f"{BASE_URL}/upload/url"
        params = {
            "key": self.api_key,
            "url": video_url
        }
        if folder_id:
            params["fld_id"] = folder_id

        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                r = self.session.post(url, params=params, timeout=25)
                if r.status_code in (429, 503):
                    time.sleep(2 * attempt)
                    continue

                r.raise_for_status()
                data = r.json()

                if data.get("status") != 200:
                    raise ValueError(f"Playmate error: {data.get('msg', 'Unknown error')}")

                res = data.get("result", {})
                raw_code = res.get("filecode", "")
                # Extract clean code if embed url was returned
                clean_code = raw_code.rstrip("/").split("/")[-1]

                if not clean_code:
                    raise ValueError(f"Playmate: No filecode in response: {data}")

                return {
                    "provider": "playmate",
                    "filecode": clean_code,
                    "url": f"https://playmate.to/{clean_code}",
                    "embed_url": f"https://playmate.to/embed/{clean_code}",
                    "raw_response": data
                }
            except Exception as e:
                last_err = e
                time.sleep(1.5 * attempt)

        raise RuntimeError(f"Playmate: upload_url failed after {max_retries} attempts: {last_err}")

    def get_file_info(self, file_code: str) -> Dict[str, Any]:
        """Fetch file metadata, encoding status, and canplay flag."""
        clean_code = file_code.rstrip("/").split("/")[-1]
        url = f"{BASE_URL}/file/info"
        r = self.session.get(url, params={"key": self.api_key, "file_code": clean_code}, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_remote_status(self) -> Dict[str, Any]:
        """Get counts of pending, processing, and completed remote uploads."""
        url = f"{BASE_URL}/remote/status"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        return r.json().get("result", {})

    @staticmethod
    def resolve_m3u8(file_code_or_url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """
        Dynamically resolve fresh master M3U8 on the fly via Playmate internal /api/s.
        Ultra-fast (~150ms), zero scraping, zero ads, open CORS.
        Returns:
            dict with HLS stream_url, audio_tracks, subtitles, poster, and headers.
        """
        code = str(file_code_or_url).strip().rstrip("/").split("/")[-1].split("?")[0]
        if not code:
            return None

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": f"https://playmate.to/embed/{code}",
            "Origin": "https://playmate.to",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*"
        }
        payload = {
            "c": code,
            "d": "desktop"
        }

        try:
            r = requests.post(STREAM_API_URL, json=payload, headers=headers, timeout=timeout)
            if r.status_code != 200:
                return None

            data = r.json()
            streaming_url = data.get("sx")
            if not streaming_url:
                return None

            thumbnail = data.get("ix")
            title = data.get("tx", "")
            raw_subs = data.get("kx") or []
            subtitles = []
            if isinstance(raw_subs, list):
                for s in raw_subs:
                    if isinstance(s, dict) and s.get("sf"):
                        subtitles.append({
                            "language": s.get("sl", "English"),
                            "file": s.get("sf")
                        })

            return {
                "filecode": code,
                "provider": "playmate",
                "type": "hls",
                "stream_url": streaming_url,
                "canonical_url": f"https://playmate.to/embed/{code}",
                "audio_tracks": ["Hindi", "Korean"],
                "subtitles": subtitles,
                "poster": thumbnail,
                "title": title,
                "headers": {
                    "Referer": f"https://playmate.to/embed/{code}",
                    "Origin": "https://playmate.to"
                }
            }
        except Exception as e:
            return None
