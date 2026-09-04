"""
Vidara API Provider
Documentation: https://vidara.to/api
"""

import time
import requests
from typing import Optional, Dict, Any

try:
    from config import VIDARA_API_KEY
except ImportError:
    VIDARA_API_KEY = "cc6630108e04a26c58513a923b643e1d30e5c6295b9052100ab4e0578d13aa32"
BASE_URL = "https://api.vidara.so/v1"


class VidaraProvider:
    def __init__(self, api_key: str = VIDARA_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def get_account_info(self) -> Dict[str, Any]:
        """Fetch user account details."""
        url = f"{BASE_URL}/user/info"
        r = self.session.get(url, params={"api_key": self.api_key}, timeout=15)
        r.raise_for_status()
        return r.json()

    def list_folders(self) -> list[Dict[str, Any]]:
        """List all folders."""
        url = f"{BASE_URL}/folder/list"
        r = self.session.get(url, params={"api_key": self.api_key}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("result", {}).get("folders", [])

    def create_folder(self, name: str) -> int:
        """Create a new folder and return its folder_id."""
        url = f"{BASE_URL}/folder/create"
        r = self.session.get(url, params={"api_key": self.api_key, "name": name}, timeout=15)
        r.raise_for_status()
        data = r.json()
        res = data.get("result", {})
        folder_id = res.get("folder_id") or res.get("fld_id")
        if not folder_id:
            raise ValueError(f"Vidara: Failed to create folder '{name}'. Response: {data}")
        return int(folder_id)

    def get_or_create_folder(self, folder_name: str = "hindi-asian") -> int:
        """Find folder by name or create it if not found."""
        folders = self.list_folders()
        for f in folders:
            if f.get("name", "").lower() == folder_name.lower():
                return int(f.get("fld_id") or f.get("code"))
        return self.create_folder(folder_name)

    def upload_url(self, video_url: str, folder_id: Optional[int] = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        Submit a direct video URL for remote upload.
        Pre-flight checks source URL and performs exponential backoff on 429/503.
        """
        if not video_url:
            raise ValueError("Vidara: video_url cannot be empty")

        if "video-downloads.googleusercontent.com" in video_url or "googleusercontent.com" in video_url:
            raise ValueError("INCOMPATIBLE_SOURCE: Google Video CDN cannot be remote uploaded to Vidara. Use Byse.")

        url = f"{BASE_URL}/upload/url"
        last_err = None

        for attempt in range(1, max_retries + 1):
            try:
                r = self.session.get(url, params={"api_key": self.api_key, "url": video_url}, timeout=25)

                if r.status_code == 429 or r.status_code == 503:
                    wait_sec = attempt * 3
                    time.sleep(wait_sec)
                    continue

                r.raise_for_status()
                data = r.json()

                # Extract filecode from data or result
                res_info = data.get("data") or data.get("result") or {}
                filecode = res_info.get("filecode")

                if not filecode:
                    raise ValueError(f"Vidara: Remote upload failed. Response: {data}")

                # Move to folder if specified
                if folder_id:
                    try:
                        self.move_to_folder(filecode, folder_id)
                    except Exception:
                        pass

                return {
                    "provider": "vidara",
                    "filecode": filecode,
                    "title": res_info.get("title", ""),
                    "embed_url": f"https://vidara.so/v/{filecode}",
                    "watch_url": f"https://vidara.so/{filecode}",
                    "raw_response": data
                }
            except Exception as e:
                last_err = e
                if attempt < max_retries and "INCOMPATIBLE_SOURCE" not in str(e):
                    time.sleep(2 * attempt)

        raise last_err or RuntimeError(f"Vidara upload failed after {max_retries} attempts.")

    def move_to_folder(self, filecode: str, folder_id: int) -> bool:
        """Move a file to a specific folder."""
        url = f"{BASE_URL}/video/move"
        r = self.session.get(url, params={"api_key": self.api_key, "filecode": filecode, "fld_id": folder_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("status") == 200
