"""
SaveFiles API Provider
Documentation: https://savefiles.com/api.html
"""

import re
import time
import requests
from typing import Optional, Dict, Any, List

try:
    from config import SAVEFILES_API_KEY
except ImportError:
    SAVEFILES_API_KEY = "12788yw4xeco1sk20glq0"
BASE_URL = "https://savefiles.com/api"


class SaveFilesProvider:
    def __init__(self, api_key: str = SAVEFILES_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def get_account_info(self) -> Dict[str, Any]:
        """Fetch SaveFiles account info, balance, storage remaining."""
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
        return data.get("result", {}).get("folders", [])

    def create_folder(self, name: str, parent_id: int = 0) -> str:
        """Create a new folder and return its fld_id."""
        url = f"{BASE_URL}/folder/create"
        r = self.session.get(url, params={"key": self.api_key, "name": name, "parent_id": parent_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
        fld_id = data.get("result", {}).get("fld_id")
        if not fld_id:
            raise ValueError(f"SaveFiles: Failed to create folder '{name}'. Response: {data}")
        return str(fld_id)

    def get_or_create_folder(self, folder_name: str = "hindi-asian") -> str:
        """Find folder by name or create it if not found."""
        try:
            folders = self.list_folders()
            for f in folders:
                if f.get("name", "").lower() == folder_name.lower():
                    return str(f.get("fld_id"))
        except Exception:
            pass
        return self.create_folder(folder_name)

    def get_queue_count(self) -> int:
        """Return the number of active items in the remote download queue."""
        try:
            uploads = self.get_url_uploads()
            return len(uploads)
        except Exception:
            return 0

    def purge_errors(self) -> bool:
        """Purge any failed/error downloads to immediately free up queue slots."""
        try:
            url = f"{BASE_URL}/file/url_actions"
            r = self.session.get(url, params={"key": self.api_key, "delete_errors": 1}, timeout=15)
            return r.status_code == 200
        except Exception:
            return False

    def wait_for_available_slot(self, max_queue: int = 14, poll_interval: int = 15, timeout: int = 600) -> bool:
        """
        Wait until active queue drops below max_queue (default 14, leaving at least 1 slot free).
        Purges errors on first check.
        """
        self.purge_errors()
        start = time.time()
        while time.time() - start < timeout:
            count = self.get_queue_count()
            if count < max_queue:
                return True
            print(f"  [⏳ SAVEFILES QUEUE FULL: {count}/15] Waiting {poll_interval}s for downloads to finish...", flush=True)
            time.sleep(poll_interval)
            self.purge_errors()
        return False

    def upload_url(
        self,
        video_url: str,
        folder_id: Optional[str] = None,
        max_retries: int = 3,
        wait_if_full: bool = False,
        wait_timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Submit a direct video URL for remote upload.
        If wait_if_full is False and queue has reached 15/15, fails fast with RuntimeError
        so fallback hosts (like Playmate) can immediately take over without stalling workers.
        """
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
                r = self.session.get(url, params=params, timeout=20)
                if r.status_code in (429, 503):
                    wait = 2 ** attempt
                    time.sleep(wait)
                    continue

                data = r.json()
                msg = str(data.get("msg", "")).lower()

                # Handle Queue Limit: 15
                if "max urls limit" in msg or "limit: 15" in msg:
                    if not wait_if_full:
                        raise RuntimeError("SaveFiles queue is full (15/15). Passing to fallback host.")
                    print(f"  [!] SaveFiles queue is at capacity (15/15). Waiting for a slot...", flush=True)
                    has_slot = self.wait_for_available_slot(max_queue=14, poll_interval=10, timeout=wait_timeout)
                    if not has_slot:
                        raise RuntimeError(f"SaveFiles: queue full timeout ({wait_timeout}s). Passing to fallback host.")
                    continue

                if data.get("status") != 200:
                    raise ValueError(f"SaveFiles error: {data.get('msg', 'Unknown error')}")

                res = data.get("result", {})
                filecode = None
                if isinstance(res, dict):
                    filecode = res.get("filecode")
                elif isinstance(res, list) and len(res) > 0:
                    filecode = res[0].get("file_code")

                if not filecode:
                    raise ValueError(f"SaveFiles: No filecode in response: {data}")

                return {
                    "filecode": filecode,
                    "url": f"https://savefiles.com/{filecode}",
                    "raw_response": data
                }
            except Exception as e:
                last_err = e
                # Fail fast on queue capacity so Playmate takes over in milliseconds
                if "queue is full" in str(e).lower():
                    raise e
                time.sleep(2.0 * attempt)

        raise RuntimeError(f"SaveFiles: upload_url failed after {max_retries} attempts: {last_err}")

    def get_file_info(self, file_code: str) -> Dict[str, Any]:
        """Fetch file metadata, encoding status, and canplay flag."""
        url = f"{BASE_URL}/file/info"
        r = self.session.get(url, params={"key": self.api_key, "file_code": file_code}, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_url_uploads(self) -> List[Dict[str, Any]]:
        """Get list of active remote upload tasks and their progress."""
        url = f"{BASE_URL}/file/url_uploads"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("result", [])

    @staticmethod
    def resolve_m3u8(file_code_or_url: str, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """
        Dynamically resolve fresh master M3U8 on the fly.
        Extracts playlist with multi-audio (Hindi + Korean) and subtitles.
        Runs in ~1.5s with zero ads, zero iframes.
        """
        code = str(file_code_or_url).strip().rstrip("/").split("/")[-1].split("?")[0]
        page_url = f"https://savefiles.com/{code}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            r = requests.get(page_url, headers=headers, timeout=timeout)
            if r.status_code != 200:
                return None

            match = re.search(r'["\'](https?://[^\s"\']+\.m3u8[^\s"\']*)["\']', r.text)
            if not match:
                return None

            m3u8_url = match.group(1)
            return {
                "filecode": code,
                "provider": "savefiles",
                "type": "hls",
                "stream_url": m3u8_url,
                "canonical_url": page_url,
                "audio_tracks": ["Hindi", "Korean"],
                "subtitles": ["English"],
                "poster": f"https://img.savefiles.com/{code}_xt.jpg",
                "headers": {
                    "User-Agent": headers["User-Agent"]
                }
            }
        except Exception:
            return None
