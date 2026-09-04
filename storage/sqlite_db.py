"""
SQLite Database Layer (Turso / LibSQL Compatible)
Database file: data/hindi_asian.db
"""

import sqlite3
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "hindi_asian.db"

try:
    from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, IS_TURSO_ENABLED
    from storage.turso_client import TursoClient
except ImportError:
    TURSO_DATABASE_URL = ""
    TURSO_AUTH_TOKEN = ""
    IS_TURSO_ENABLED = False
    TursoClient = None


class SqliteDatabase:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.turso = TursoClient(TURSO_DATABASE_URL, TURSO_AUTH_TOKEN) if (IS_TURSO_ENABLED and TursoClient) else None
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def init_db(self):
        """Initialize Turso-compatible tables and indexes."""
        with self.get_connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS dramas (
                tmdb_id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                media_type TEXT DEFAULT 'tv',
                category TEXT DEFAULT 'hi-asian',
                audio TEXT,
                quality TEXT DEFAULT '1080p',
                overview TEXT,
                poster TEXT,
                rating REAL,
                release_year TEXT,
                total_seasons INTEGER DEFAULT 1,
                total_episodes INTEGER,
                genres TEXT,
                tmdb_url TEXT,
                kdramalover_url TEXT,
                metadata_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                season_number INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                title TEXT,
                host_vidara TEXT,
                host_savefiles TEXT,
                host_playmate TEXT,
                host_byse TEXT,
                direct_vidara TEXT,
                direct_savefiles TEXT,
                direct_playmate TEXT,
                direct_byse TEXT,
                sources_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (tmdb_id) REFERENCES dramas(tmdb_id) ON DELETE CASCADE,
                UNIQUE(tmdb_id, season_number, episode_number)
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_drama 
            ON episodes(tmdb_id, season_number, episode_number);

            CREATE TABLE IF NOT EXISTS crawler_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kdramalover_url TEXT UNIQUE NOT NULL,
                raw_title TEXT NOT NULL,
                clean_title TEXT NOT NULL,
                category TEXT NOT NULL,
                poster TEXT,
                update_tag TEXT,
                tmdb_id INTEGER,
                status TEXT DEFAULT 'pending',
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_crawler_status ON crawler_queue(status);
            CREATE INDEX IF NOT EXISTS idx_crawler_category ON crawler_queue(category);

            CREATE TABLE IF NOT EXISTS ingest_quarantine (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tmdb_id INTEGER NOT NULL,
                drama_title TEXT,
                season_number INTEGER NOT NULL,
                episode_number INTEGER NOT NULL,
                provider_missing TEXT NOT NULL,
                failure_code TEXT NOT NULL,
                failure_detail TEXT,
                raw_links_json TEXT,
                status TEXT DEFAULT 'pending_retry',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tmdb_id, season_number, episode_number, provider_missing)
            );

            CREATE INDEX IF NOT EXISTS idx_quarantine_status ON ingest_quarantine(status);
            CREATE INDEX IF NOT EXISTS idx_quarantine_drama ON ingest_quarantine(tmdb_id, episode_number);
            """)

            # Automatic Schema Migration for Existing Databases
            cursor = conn.execute("PRAGMA table_info(episodes);")
            existing_cols = {r["name"] for r in cursor.fetchall()}
            if "host_savefiles" not in existing_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN host_savefiles TEXT;")
            if "direct_savefiles" not in existing_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN direct_savefiles TEXT;")
            if "host_playmate" not in existing_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN host_playmate TEXT;")
            if "direct_playmate" not in existing_cols:
                conn.execute("ALTER TABLE episodes ADD COLUMN direct_playmate TEXT;")

    def upsert_drama(self, drama: Dict[str, Any]):
        """Insert or update a drama record."""
        tmdb_id = drama["tmdb_id"]
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO dramas (
                tmdb_id, title, clean_title, media_type, category, audio,
                quality, overview, poster, rating, release_year,
                total_seasons, total_episodes, genres, tmdb_url,
                kdramalover_url, metadata_json, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
            )
            ON CONFLICT(tmdb_id) DO UPDATE SET
                title = excluded.title,
                clean_title = excluded.clean_title,
                media_type = excluded.media_type,
                category = excluded.category,
                audio = excluded.audio,
                quality = excluded.quality,
                overview = excluded.overview,
                poster = excluded.poster,
                rating = excluded.rating,
                release_year = excluded.release_year,
                total_seasons = excluded.total_seasons,
                total_episodes = excluded.total_episodes,
                genres = excluded.genres,
                tmdb_url = excluded.tmdb_url,
                kdramalover_url = excluded.kdramalover_url,
                metadata_json = excluded.metadata_json,
                updated_at = CURRENT_TIMESTAMP;
            """, (
                tmdb_id,
                drama.get("title", ""),
                drama.get("clean_title", ""),
                drama.get("media_type", "tv"),
                drama.get("category", "hi-asian"),
                json.dumps(drama.get("audio", ["Hindi", "Korean"])),
                drama.get("quality", "1080p"),
                drama.get("overview", ""),
                drama.get("poster", ""),
                drama.get("rating", 0.0),
                drama.get("release_year", ""),
                drama.get("total_seasons", 1),
                drama.get("total_episodes", 0),
                json.dumps(drama.get("genres", [])),
                drama.get("tmdb_url", ""),
                drama.get("kdramalover_url", ""),
                json.dumps(drama, ensure_ascii=False)
            ))

    def upsert_episode(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        title: str,
        host_vidara: Optional[str] = None,
        host_savefiles: Optional[str] = None,
        host_playmate: Optional[str] = None,
        host_byse: Optional[str] = None,
        direct_vidara: Optional[Dict[str, Any]] = None,
        direct_savefiles: Optional[Dict[str, Any]] = None,
        direct_playmate: Optional[Dict[str, Any]] = None,
        direct_byse: Optional[Dict[str, Any]] = None,
        sources_used: Optional[Dict[str, Any]] = None
    ):
        """Insert or update an episode record with Vidara, SaveFiles, and Playmate support."""
        default_direct_vidara = direct_vidara or {
            "m3u8": None,
            "origin": "https://vidara.so",
            "referer": "https://vidara.so/",
            "status": "pending_m3u8_resolver"
        }
        default_direct_savefiles = direct_savefiles or {
            "m3u8": None,
            "origin": "https://savefiles.com",
            "referer": "https://savefiles.com/",
            "status": "pending_m3u8_resolver"
        }
        default_direct_playmate = direct_playmate or {
            "m3u8": None,
            "origin": "https://playmate.to",
            "referer": "https://playmate.to/",
            "status": "pending_m3u8_resolver"
        }
        default_direct_byse = direct_byse or {
            "m3u8": None,
            "origin": "https://byse.sx",
            "referer": "https://byse.sx/",
            "status": "deprecated"
        }

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO episodes (
                tmdb_id, season_number, episode_number, title,
                host_vidara, host_savefiles, host_playmate, host_byse,
                direct_vidara, direct_savefiles, direct_playmate, direct_byse,
                sources_used, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tmdb_id, season_number, episode_number) DO UPDATE SET
                title = excluded.title,
                host_vidara = COALESCE(excluded.host_vidara, episodes.host_vidara),
                host_savefiles = COALESCE(excluded.host_savefiles, episodes.host_savefiles),
                host_playmate = COALESCE(excluded.host_playmate, episodes.host_playmate),
                host_byse = COALESCE(excluded.host_byse, episodes.host_byse),
                direct_vidara = COALESCE(excluded.direct_vidara, episodes.direct_vidara),
                direct_savefiles = COALESCE(excluded.direct_savefiles, episodes.direct_savefiles),
                direct_playmate = COALESCE(excluded.direct_playmate, episodes.direct_playmate),
                direct_byse = COALESCE(excluded.direct_byse, episodes.direct_byse),
                sources_used = COALESCE(excluded.sources_used, episodes.sources_used),
                updated_at = CURRENT_TIMESTAMP;
            """, (
                tmdb_id,
                season_number,
                episode_number,
                title,
                host_vidara,
                host_savefiles,
                host_playmate,
                host_byse,
                json.dumps(default_direct_vidara),
                json.dumps(default_direct_savefiles),
                json.dumps(default_direct_playmate),
                json.dumps(default_direct_byse),
                json.dumps(sources_used or {})
            ))

    def update_episode_playmate(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        host_playmate: str,
        direct_playmate: Optional[Dict[str, Any]] = None
    ):
        """Update or set Playmate link for an existing episode."""
        payload = json.dumps(direct_playmate or {
            "type": "hls",
            "origin": "https://playmate.to",
            "status": "ready_m3u8_resolver"
        })
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE episodes
            SET host_playmate = ?, direct_playmate = ?, updated_at = CURRENT_TIMESTAMP
            WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
            """, (host_playmate, payload, tmdb_id, season_number, episode_number))

    def update_episode_savefiles(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        host_savefiles: str,
        direct_savefiles: Optional[Dict[str, Any]] = None
    ):
        """Update or set SaveFiles link for an existing episode."""
        payload = json.dumps(direct_savefiles or {
            "type": "hls",
            "origin": "https://savefiles.com",
            "status": "ready_m3u8_resolver"
        })
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE episodes
            SET host_savefiles = ?, direct_savefiles = ?, updated_at = CURRENT_TIMESTAMP
            WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
            """, (host_savefiles, payload, tmdb_id, season_number, episode_number))

    def get_episodes_needing_savefiles(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Query episodes that do not yet have a SaveFiles host link."""
        with self.get_connection() as conn:
            query = """
            SELECT e.id, e.tmdb_id, e.season_number, e.episode_number, e.title,
                   e.host_vidara, e.host_savefiles, e.host_byse, e.sources_used,
                   d.title as drama_title, d.kdramalover_url
            FROM episodes e
            JOIN dramas d ON e.tmdb_id = d.tmdb_id
            WHERE e.host_savefiles IS NULL OR e.host_savefiles = ''
            ORDER BY e.tmdb_id, e.season_number, e.episode_number
            """
            if limit:
                query += f" LIMIT {int(limit)}"
            rows = conn.execute(query).fetchall()
            return [dict(r) for r in rows]

    def is_episode_processed(self, tmdb_id: int, season_number: int, episode_number: int) -> bool:
        """Check if an episode has at least one valid host link (Vidara or SaveFiles) in the DB."""
        with self.get_connection() as conn:
            row = conn.execute("""
            SELECT host_vidara, host_savefiles, host_byse FROM episodes 
            WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
            """, (tmdb_id, season_number, episode_number)).fetchone()
            if row and (row["host_vidara"] or row["host_savefiles"] or row["host_byse"]):
                return True
            return False

    def get_drama(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve full drama JSON record by TMDB ID, enriched with all stored episodes."""
        drama = None
        ep_rows = []

        # 1. Try local SQLite query
        try:
            with self.get_connection() as conn:
                row = conn.execute("SELECT * FROM dramas WHERE tmdb_id = ?;", (tmdb_id,)).fetchone()
                if row:
                    drama = json.loads(row["metadata_json"]) if row["metadata_json"] else dict(row)
                    ep_rows = conn.execute("""
                    SELECT season_number, episode_number, title, host_vidara, host_savefiles, host_playmate, host_byse,
                           direct_vidara, direct_savefiles, direct_playmate, direct_byse, sources_used
                    FROM episodes WHERE tmdb_id = ? ORDER BY season_number, episode_number;
                    """, (tmdb_id,)).fetchall()
        except Exception:
            pass

        # 2. Fallback to Turso Cloud if local record missing or running on serverless
        if not drama and self.turso:
            try:
                t_rows = self.turso.execute("SELECT * FROM dramas WHERE tmdb_id = ?;", (tmdb_id,))
                if t_rows:
                    row = t_rows[0]
                    drama = json.loads(row["metadata_json"]) if row.get("metadata_json") else row
                    ep_rows = self.turso.execute("""
                    SELECT season_number, episode_number, title, host_vidara, host_savefiles, host_playmate, host_byse,
                           direct_vidara, direct_savefiles, direct_playmate, direct_byse, sources_used
                    FROM episodes WHERE tmdb_id = ? ORDER BY season_number, episode_number;
                    """, (tmdb_id,))
            except Exception:
                pass

        if not drama:
            return None

        if ep_rows:
            seasons_map = {}
            for r in ep_rows:
                rd = dict(r) if not isinstance(r, dict) else r
                s_num = rd["season_number"]
                if s_num not in seasons_map:
                    seasons_map[s_num] = {
                        "season_number": s_num,
                        "name": f"Season {s_num}",
                        "episodes": []
                    }

                direct_vid = json.loads(rd["direct_vidara"]) if rd.get("direct_vidara") else {}
                direct_sf = json.loads(rd["direct_savefiles"]) if rd.get("direct_savefiles") else {}
                direct_pm = json.loads(rd["direct_playmate"]) if rd.get("direct_playmate") else {}
                direct_by = json.loads(rd["direct_byse"]) if rd.get("direct_byse") else {}
                src_used = json.loads(rd["sources_used"]) if rd.get("sources_used") else {}

                seasons_map[s_num]["episodes"].append({
                    "episode_number": rd["episode_number"],
                    "title": rd.get("title") or f"Episode {rd['episode_number']}",
                    "hosts": {
                        "vidara": rd.get("host_vidara"),
                        "savefiles": rd.get("host_savefiles"),
                        "playmate": rd.get("host_playmate"),
                        "byse": rd.get("host_byse")
                    },
                    "direct": {
                        "vidara": direct_vid,
                        "savefiles": direct_sf,
                        "playmate": direct_pm,
                        "byse": direct_by
                    },
                    "sources_used": src_used
                })

            drama["seasons"] = list(seasons_map.values())

        return drama

    def list_dramas(self) -> List[Dict[str, Any]]:
        """List all drama JSON records enriched with episodes."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT tmdb_id FROM dramas ORDER BY updated_at DESC;").fetchall()
            dramas = []
            for r in rows:
                d = self.get_drama(r["tmdb_id"])
                if d:
                    dramas.append(d)
            return dramas

    def upsert_crawler_item(
        self,
        kdramalover_url: Optional[str] = None,
        raw_title: str = "",
        clean_title: str = "",
        category: str = "",
        poster: Optional[str] = None,
        update_tag: Optional[str] = None,
        tmdb_id: Optional[int] = None,
        status: Optional[str] = None,
        url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Insert or update a tracked KDramaLover item."""
        target_url = kdramalover_url or url
        if not target_url:
            raise ValueError("kdramalover_url or url must be provided")

        with self.get_connection() as conn:
            # Check existing status
            existing = conn.execute(
                "SELECT id, status, update_tag, tmdb_id FROM crawler_queue WHERE kdramalover_url = ?;",
                (target_url,)
            ).fetchone()

            # Also check if already in dramas table
            already_ingested = conn.execute(
                "SELECT tmdb_id FROM dramas WHERE kdramalover_url = ?;",
                (target_url,)
            ).fetchone()

            final_status = status
            final_tmdb = tmdb_id or (already_ingested["tmdb_id"] if already_ingested else None)

            if not final_status:
                if already_ingested:
                    if existing and update_tag and existing["update_tag"] != update_tag:
                        final_status = "update_available"
                    else:
                        final_status = "ingested"
                elif existing and existing["status"] in ("archive_unavailable", "skipped_non_hindi", "quarantined", "episodes_unavailable"):
                    final_status = existing["status"]
                else:
                    final_status = "pending"

            conn.execute("""
            INSERT INTO crawler_queue (
                kdramalover_url, raw_title, clean_title, category,
                poster, update_tag, tmdb_id, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(kdramalover_url) DO UPDATE SET
                raw_title = excluded.raw_title,
                clean_title = excluded.clean_title,
                category = excluded.category,
                poster = COALESCE(excluded.poster, crawler_queue.poster),
                update_tag = excluded.update_tag,
                tmdb_id = COALESCE(excluded.tmdb_id, crawler_queue.tmdb_id),
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP;
            """, (
                target_url, raw_title, clean_title, category,
                poster, update_tag, final_tmdb, final_status
            ))

            return {
                "url": target_url,
                "clean_title": clean_title,
                "category": category,
                "update_tag": update_tag,
                "status": final_status,
                "tmdb_id": final_tmdb
            }

    def list_crawler_items(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """List tracked crawler items with optional filtering."""
        with self.get_connection() as conn:
            query = "SELECT * FROM crawler_queue WHERE 1=1"
            params = []
            if category:
                query += " AND category = ?"
                params.append(category)
            if status:
                query += " AND status = ?"
                params.append(status)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def set_crawler_status(
        self,
        kdramalover_url: Optional[str] = None,
        status: str = "ingested",
        tmdb_id: Optional[int] = None,
        url: Optional[str] = None
    ):
        """Update tracker item status (e.g. after ingest)."""
        target_url = kdramalover_url or url
        if not target_url:
            raise ValueError("kdramalover_url or url must be provided")
        with self.get_connection() as conn:
            conn.execute("""
            UPDATE crawler_queue
            SET status = ?, tmdb_id = COALESCE(?, tmdb_id), updated_at = CURRENT_TIMESTAMP
            WHERE kdramalover_url = ?;
            """, (status, tmdb_id, target_url))

    def upsert_quarantine_item(
        self,
        tmdb_id: int,
        drama_title: str,
        season_number: int,
        episode_number: int,
        provider_missing: str,
        failure_code: str,
        failure_detail: str,
        raw_links: Optional[Dict[str, Any]] = None,
        status: str = "pending_retry"
    ):
        """Record or update a failed/incomplete episode task in quarantine."""
        links_json = json.dumps(raw_links or {}, ensure_ascii=False)
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO ingest_quarantine (
                tmdb_id, drama_title, season_number, episode_number,
                provider_missing, failure_code, failure_detail,
                raw_links_json, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tmdb_id, season_number, episode_number, provider_missing) DO UPDATE SET
                failure_code = excluded.failure_code,
                failure_detail = excluded.failure_detail,
                raw_links_json = excluded.raw_links_json,
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP;
            """, (
                tmdb_id, drama_title, season_number, episode_number,
                provider_missing, failure_code, failure_detail,
                links_json, status
            ))

    def add_quarantine(self, *args, **kwargs):
        """Flexible backward-compatible alias for upsert_quarantine_item."""
        tmdb_id = kwargs.get("tmdb_id") or (args[0] if len(args) > 0 else 0)
        drama_title = kwargs.get("drama_title") or (args[1] if len(args) > 1 else "")
        season_number = kwargs.get("season_number", 1)
        episode_number = kwargs.get("episode_number") or (args[2] if len(args) > 2 else 0)
        provider_missing = kwargs.get("provider_missing", "archive")
        failure_code = kwargs.get("failure_code", "ERROR")
        failure_detail = kwargs.get("failure_detail") or kwargs.get("direct_url_attempted") or ""
        raw_links = kwargs.get("raw_links") or {}
        status = kwargs.get("status", "pending_retry")
        return self.upsert_quarantine_item(
            tmdb_id=tmdb_id,
            drama_title=drama_title,
            season_number=season_number,
            episode_number=episode_number,
            provider_missing=provider_missing,
            failure_code=failure_code,
            failure_detail=str(failure_detail),
            raw_links=raw_links,
            status=status
        )

    def list_quarantine_items(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """List quarantined episode failures with raw links."""
        with self.get_connection() as conn:
            query = "SELECT * FROM ingest_quarantine"
            params = []
            if status:
                query += " WHERE status = ?"
                params.append(status)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            items = []
            for r in rows:
                it = dict(r)
                if it.get("raw_links_json"):
                    try:
                        it["raw_links"] = json.loads(it["raw_links_json"])
                    except Exception:
                        it["raw_links"] = {}
                items.append(it)
            return items

    def resolve_quarantine_item(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        provider_missing: Optional[str] = None
    ):
        """Mark quarantine item as resolved."""
        with self.get_connection() as conn:
            if provider_missing:
                conn.execute("""
                UPDATE ingest_quarantine
                SET status = 'resolved', updated_at = CURRENT_TIMESTAMP
                WHERE tmdb_id = ? AND season_number = ? AND episode_number = ? AND provider_missing = ?;
                """, (tmdb_id, season_number, episode_number, provider_missing))
            else:
                conn.execute("""
                UPDATE ingest_quarantine
                SET status = 'resolved', updated_at = CURRENT_TIMESTAMP
                WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
                """, (tmdb_id, season_number, episode_number))

    def manual_override_episode(
        self,
        tmdb_id: int,
        season_number: int,
        episode_number: int,
        host_vidara: Optional[str] = None,
        host_byse: Optional[str] = None
    ) -> Dict[str, Any]:
        """Manually override or supply links for an episode, clearing quarantine."""
        with self.get_connection() as conn:
            # Format embeds if raw codes were supplied
            v_embed = host_vidara
            if v_embed and not v_embed.startswith("http"):
                v_embed = f"https://vidara.so/v/{v_embed}"

            b_embed = host_byse
            if b_embed and not b_embed.startswith("http"):
                b_embed = f"https://byse.sx/e/{b_embed}"

            # Check existing episode
            existing = conn.execute("""
            SELECT * FROM episodes WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
            """, (tmdb_id, season_number, episode_number)).fetchone()

            if existing:
                conn.execute("""
                UPDATE episodes
                SET host_vidara = COALESCE(?, host_vidara),
                    host_byse = COALESCE(?, host_byse),
                    updated_at = CURRENT_TIMESTAMP
                WHERE tmdb_id = ? AND season_number = ? AND episode_number = ?;
                """, (v_embed, b_embed, tmdb_id, season_number, episode_number))
            else:
                conn.execute("""
                INSERT INTO episodes (
                    tmdb_id, season_number, episode_number, title,
                    host_vidara, host_byse, direct_vidara, direct_byse,
                    sources_used, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    '{"type":"hls","origin":"https://vidarae.live","referer":"https://vidarae.live/","status":"on_the_fly_resolver"}',
                    '{"type":"hls","origin":"https://byse.sx","referer":"https://byse.sx/","status":"pending_m3u8_resolver"}',
                    '{"manual_override": true}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                );
                """, (tmdb_id, season_number, episode_number, f"Episode {episode_number}", v_embed, b_embed))

        # Clear from quarantine
        self.resolve_quarantine_item(tmdb_id, season_number, episode_number)
        return {
            "success": True,
            "tmdb_id": tmdb_id,
            "season": season_number,
            "episode": episode_number,
            "host_vidara": v_embed,
            "host_byse": b_embed
        }

    def sync_local_to_turso(self, batch_size: int = 50) -> Dict[str, Any]:
        """
        Synchronize local SQLite records to Turso Cloud database.
        Uploads schemas, dramas, episodes, and queues in atomic batches.
        """
        if not self.turso:
            raise RuntimeError("Turso is not configured. Please set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env.")

        # 1. Initialize remote schemas on Turso
        self.turso.execute("""
        CREATE TABLE IF NOT EXISTS dramas (
            tmdb_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            clean_title TEXT NOT NULL,
            media_type TEXT DEFAULT 'tv',
            category TEXT DEFAULT 'hi-asian',
            audio TEXT,
            quality TEXT DEFAULT '1080p',
            overview TEXT,
            poster TEXT,
            rating REAL,
            release_year TEXT,
            total_seasons INTEGER DEFAULT 1,
            total_episodes INTEGER,
            genres TEXT,
            tmdb_url TEXT,
            kdramalover_url TEXT,
            metadata_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        self.turso.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER NOT NULL,
            season_number INTEGER NOT NULL,
            episode_number INTEGER NOT NULL,
            title TEXT,
            host_vidara TEXT,
            host_savefiles TEXT,
            host_playmate TEXT,
            host_byse TEXT,
            direct_vidara TEXT,
            direct_savefiles TEXT,
            direct_playmate TEXT,
            direct_byse TEXT,
            sources_used TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tmdb_id, season_number, episode_number)
        );
        """)

        # 2. Sync Dramas
        with self.get_connection() as conn:
            d_rows = conn.execute("SELECT * FROM dramas").fetchall()
            e_rows = conn.execute("SELECT * FROM episodes").fetchall()

        d_count = len(d_rows)
        e_count = len(e_rows)

        # Batch upload dramas
        for i in range(0, d_count, batch_size):
            chunk = d_rows[i:i + batch_size]
            stmts = []
            for r in chunk:
                stmts.append((
                    """
                    INSERT INTO dramas (
                        tmdb_id, title, clean_title, media_type, category, audio,
                        quality, overview, poster, rating, release_year,
                        total_seasons, total_episodes, genres, tmdb_url,
                        kdramalover_url, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tmdb_id) DO UPDATE SET
                        title = excluded.title,
                        overview = excluded.overview,
                        poster = excluded.poster,
                        total_episodes = excluded.total_episodes,
                        metadata_json = excluded.metadata_json,
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        r["tmdb_id"], r["title"], r["clean_title"], r["media_type"], r["category"],
                        r["audio"], r["quality"], r["overview"], r["poster"], r["rating"],
                        r["release_year"], r["total_seasons"], r["total_episodes"], r["genres"],
                        r["tmdb_url"], r["kdramalover_url"], r["metadata_json"],
                        r["created_at"], r["updated_at"]
                    )
                ))
            self.turso.execute_batch(stmts)

        # Batch upload episodes
        for i in range(0, e_count, batch_size):
            chunk = e_rows[i:i + batch_size]
            stmts = []
            for r in chunk:
                stmts.append((
                    """
                    INSERT INTO episodes (
                        tmdb_id, season_number, episode_number, title,
                        host_vidara, host_savefiles, host_playmate, host_byse,
                        direct_vidara, direct_savefiles, direct_playmate, direct_byse,
                        sources_used, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tmdb_id, season_number, episode_number) DO UPDATE SET
                        title = excluded.title,
                        host_vidara = COALESCE(excluded.host_vidara, episodes.host_vidara),
                        host_savefiles = COALESCE(excluded.host_savefiles, episodes.host_savefiles),
                        host_playmate = COALESCE(excluded.host_playmate, episodes.host_playmate),
                        host_byse = COALESCE(excluded.host_byse, episodes.host_byse),
                        direct_vidara = COALESCE(excluded.direct_vidara, episodes.direct_vidara),
                        direct_savefiles = COALESCE(excluded.direct_savefiles, episodes.direct_savefiles),
                        direct_playmate = COALESCE(excluded.direct_playmate, episodes.direct_playmate),
                        direct_byse = COALESCE(excluded.direct_byse, episodes.direct_byse),
                        sources_used = COALESCE(excluded.sources_used, episodes.sources_used),
                        updated_at = CURRENT_TIMESTAMP;
                    """,
                    (
                        r["tmdb_id"], r["season_number"], r["episode_number"], r["title"],
                        r["host_vidara"], r["host_savefiles"] if "host_savefiles" in r.keys() else None,
                        r["host_playmate"] if "host_playmate" in r.keys() else None,
                        r["host_byse"], r["direct_vidara"],
                        r["direct_savefiles"] if "direct_savefiles" in r.keys() else None,
                        r["direct_playmate"] if "direct_playmate" in r.keys() else None,
                        r["direct_byse"], r["sources_used"],
                        r["created_at"], r["updated_at"]
                    )
                ))
            self.turso.execute_batch(stmts)

        return {
            "success": True,
            "dramas_synced": d_count,
            "episodes_synced": e_count
        }

