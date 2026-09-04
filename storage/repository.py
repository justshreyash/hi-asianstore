"""
Metadata Storage Repository
Stores and manages drama metadata keyed by TMDB ID.
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "dramas"


class DramaRepository:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, tmdb_id: int) -> Path:
        return self.data_dir / f"{tmdb_id}.json"

    def save_drama(self, drama: Dict[str, Any]) -> Path:
        """Save or overwrite drama metadata."""
        tmdb_id = drama.get("tmdb_id")
        if not tmdb_id:
            raise ValueError("Drama metadata must contain a valid 'tmdb_id'")
        file_path = self._file_path(tmdb_id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(drama, f, indent=2, ensure_ascii=False)
        return file_path

    def get_drama(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve drama metadata by TMDB ID."""
        file_path = self._file_path(tmdb_id)
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_all(self) -> List[Dict[str, Any]]:
        """List all stored dramas."""
        items = []
        for file in self.data_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    items.append(json.load(f))
            except Exception:
                continue
        return items

    def update_episode(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        host_vidara: Optional[str] = None,
        host_savefiles: Optional[str] = None,
        host_byse: Optional[str] = None,
        episode_title: Optional[str] = None
    ) -> Dict[str, Any]:
        """Update or insert episode hosting links within a drama."""
        drama = self.get_drama(tmdb_id)
        if not drama:
            raise ValueError(f"Drama with tmdb_id {tmdb_id} not found in repository.")

        seasons = drama.setdefault("seasons", [])
        season = next((s for s in seasons if s.get("season_number") == season_number), None)
        if not season:
            season = {
                "season_number": season_number,
                "name": f"Season {season_number}",
                "episodes": []
            }
            seasons.append(season)

        episodes = season.setdefault("episodes", [])
        ep = next((e for e in episodes if e.get("episode_number") == episode_number), None)
        if not ep:
            ep = {
                "episode_number": episode_number,
                "title": episode_title or f"Episode {episode_number}",
                "hosts": {},
                "direct": {
                    "vidara": {
                        "m3u8": None,
                        "origin": "https://vidara.so",
                        "referer": "https://vidara.so/",
                        "status": "pending_m3u8_resolver"
                    },
                    "savefiles": {
                        "m3u8": None,
                        "origin": "https://savefiles.com",
                        "referer": "https://savefiles.com/",
                        "status": "pending_m3u8_resolver"
                    },
                    "byse": {
                        "m3u8": None,
                        "origin": "https://byse.sx",
                        "referer": "https://byse.sx/",
                        "status": "deprecated"
                    }
                }
            }
            episodes.append(ep)

        if host_vidara:
            ep["hosts"]["vidara"] = host_vidara
        if host_savefiles:
            ep["hosts"]["savefiles"] = host_savefiles
        if host_byse:
            ep["hosts"]["byse"] = host_byse

        self.save_drama(drama)
        return drama
