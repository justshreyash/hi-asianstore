"""
FastAPI Server for Hindi-Asian Drama Metadata
Endpoints:
  GET /v1/hi-asian/:tmdbid
  GET /v1/hi-asian
"""

from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel
import subprocess
import sys

from storage.sqlite_db import SqliteDatabase
from storage.repository import DramaRepository
from services.vidara_resolver import resolve_drama_vidara_m3u8, check_encoding_status, extract_filecode

try:
    from config import ALLOWED_ORIGINS
except ImportError:
    ALLOWED_ORIGINS = ["*"]

app = FastAPI(
    title="Hindi-Asian Drama Metadata API",
    version="1.0.0",
    description="Provides curated metadata, TMDB details, hosting links, and direct M3U8 resolution."
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response

db = SqliteDatabase()
json_repo = DramaRepository()
WEB_HTML_PATH = Path(__file__).resolve().parent.parent / "web.html"
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
WIDGET_PATH = PUBLIC_DIR / "widget.js"
DEMO_WIDGET_PATH = Path(__file__).resolve().parent.parent / "integration" / "test_widget.html"

if PUBLIC_DIR.exists():
    app.mount("/public", StaticFiles(directory=str(PUBLIC_DIR)), name="public")


@app.get("/widget.js", tags=["Widget & Integration"])
def get_widget_script():
    """Serves the embeddable JavaScript widget."""
    if not WIDGET_PATH.exists():
        raise HTTPException(status_code=404, detail="widget.js not found.")
    return Response(content=WIDGET_PATH.read_text(encoding="utf-8"), media_type="application/javascript")


@app.get("/demo/widget", response_class=HTMLResponse, tags=["Widget & Integration"])
def get_widget_demo_page():
    """Interactive preview of the embeddable streaming widget."""
    if not DEMO_WIDGET_PATH.exists():
        raise HTTPException(status_code=404, detail="test_widget.html not found.")
    return DEMO_WIDGET_PATH.read_text(encoding="utf-8")


class IngestRequest(BaseModel):
    url: str
    quality: str = "1080p"


@app.get("/", tags=["Health"])
def health():
    return {
        "status": "online",
        "service": "Hindi-Asian Drama Metadata API",
        "database": "SQLite (data/hindi_asian.db)",
        "web_ui": "/web/ingestion",
        "endpoints": [
            "/web/ingestion",
            "/v1/hi-asian/{tmdb_id}",
            "/v1/hi-asian/{tmdb_id}/resolve-m3u8",
            "/v1/hi-asian",
            "/v1/hi-asian/ingest",
            "/v1/crawler/refresh",
            "/v1/crawler/queue"
        ]
    }


@app.get("/web/ingestion", response_class=HTMLResponse, tags=["Web UI"])
def get_web_ingestion_interface():
    """Serves the KDramaLover ingestion & tracker management web console."""
    if not WEB_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="web.html not found.")
    return WEB_HTML_PATH.read_text(encoding="utf-8")


@app.get("/web", response_class=HTMLResponse, tags=["Web UI"])
def get_web_interface_redirect():
    """Redirect /web to /web/ingestion."""
    return get_web_ingestion_interface()


class UserIngestRequest(BaseModel):
    tmdb_id: int
    title: str


@app.get("/v1/hi-asian/check", tags=["Widget & Integration"])
def check_drama_availability(tmdb_id: Optional[int] = None, title: Optional[str] = None):
    """
    Fast lookup for embeddable widgets:
    Returns status:
    - 'available': Drama has uploaded episodes ready to stream
    - 'in_queue': Drama is pending in crawler queue (ready for ingest)
    - 'unavailable': No Hindi dub found on source
    """
    if not tmdb_id and not title:
        raise HTTPException(status_code=400, detail="Either 'tmdb_id' or 'title' must be provided.")

    drama = None
    if tmdb_id:
        drama = db.get_drama(tmdb_id)

    if drama and drama.get("seasons") and drama["seasons"][0].get("episodes"):
        eps = drama["seasons"][0]["episodes"]
        return {
            "status": "available",
            "tmdb_id": drama.get("tmdb_id"),
            "title": drama.get("title"),
            "clean_title": drama.get("clean_title"),
            "quality": drama.get("quality", "1080p"),
            "episodes_count": len(eps),
            "episodes": [{"episode_number": e["episode_number"], "title": e["title"]} for e in eps]
        }

    # Check if in crawler queue
    with db.get_connection() as conn:
        q_item = None
        if tmdb_id:
            q_item = conn.execute("SELECT * FROM crawler_queue WHERE tmdb_id = ? LIMIT 1", (tmdb_id,)).fetchone()
        if not q_item and title:
            q_item = conn.execute("SELECT * FROM crawler_queue WHERE clean_title LIKE ? LIMIT 1", (f"%{title}%",)).fetchone()

    if q_item:
        return {
            "status": "in_queue",
            "tmdb_id": q_item["tmdb_id"],
            "title": q_item["clean_title"],
            "message": "Hindi Dub is discovered on source and queued for ingest.",
            "estimated_eta_seconds": 180
        }

    return {
        "status": "unavailable",
        "tmdb_id": tmdb_id,
        "title": title,
        "message": "Hindi Dub not yet available for this drama."
    }


@app.post("/v1/hi-asian/request-ingest", tags=["Widget & Integration"])
def request_drama_ingest(req: UserIngestRequest):
    """
    Accepts an on-demand request from a user browsing Lytekd.
    Triggers a private Telegram notification and places in priority queue.
    """
    try:
        from bot.telegram_notifier import send_user_request_alert
        send_user_request_alert(req.tmdb_id, req.title)
    except Exception:
        pass

    return {
        "status": "queued",
        "tmdb_id": req.tmdb_id,
        "title": req.title,
        "message": f"Ingestion request for '{req.title}' logged successfully.",
        "estimated_eta_seconds": 180
    }


@app.get("/v1/hi-asian/{tmdb_id}", tags=["Dramas"])
def get_drama_by_tmdb_id(tmdb_id: int) -> Dict[str, Any]:
    """
    Fetch complete curated metadata for a drama by its TMDB ID.
    Reads directly from SQLite database (Turso-ready).
    """
    drama = db.get_drama(tmdb_id) or json_repo.get_drama(tmdb_id)
    if not drama:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Drama with TMDB ID '{tmdb_id}' not found in database."
        )
    return drama


@app.get("/v1/hi-asian/{tmdb_id}/resolve-m3u8", tags=["Dramas"])
def resolve_m3u8_for_drama(tmdb_id: int, ep: Optional[int] = None) -> Dict[str, Any]:
    """
    On-the-fly multi-host M3U8 resolver with instant failover.
    Resolves active master M3U8 URLs across SaveFiles, Playmate, and Vidara.
    """
    from providers.resolver import resolve_drama_streams
    try:
        return resolve_drama_streams(tmdb_id, episode_filter=ep)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/v1/hi-asian/{tmdb_id}/stream", tags=["Streams"])
def get_episode_stream(tmdb_id: int, season: int = 1, ep: int = 1):
    """
    Fast on-the-fly stream & embed metadata for a specific episode.
    Returns:
      - stream_url: Fresh M3U8 for custom players (Hls.js, Plyr, Video.js)
      - embed_url: Direct provider iframe embed URL (zero CORS/Referer headache)
      - active_host: Provider currently serving the stream
      - audio_tracks: Audio tracks available (Hindi, Korean, etc.)
      - subtitles: Subtitle tracks available
      - hosts: Direct links across all available mirrors
    """
    drama = db.get_drama(tmdb_id) or json_repo.get_drama(tmdb_id)
    if not drama:
        raise HTTPException(status_code=404, detail=f"Drama with TMDB ID {tmdb_id} not found.")

    target_season = None
    for s in drama.get("seasons", []):
        if s.get("season_number") == season:
            target_season = s
            break
    if not target_season and drama.get("seasons"):
        target_season = drama["seasons"][0]

    if not target_season:
        raise HTTPException(status_code=404, detail="No seasons found for this drama.")

    target_ep = None
    for e in target_season.get("episodes", []):
        if e.get("episode_number") == ep:
            target_ep = e
            break

    if not target_ep:
        raise HTTPException(status_code=404, detail=f"Episode {ep} not found in season {season}.")

    hosts = target_ep.get("hosts", {})
    from providers.resolver import resolve_stream, extract_filecode
    stream_info = resolve_stream(hosts)

    # Derive primary embed URL
    embed_url = None
    if hosts.get("playmate"):
        pm_code = extract_filecode(hosts["playmate"])
        embed_url = f"https://playmate.to/embed/{pm_code}" if pm_code else hosts["playmate"]
    elif hosts.get("savefiles"):
        sf_code = extract_filecode(hosts["savefiles"])
        embed_url = f"https://savefiles.to/e/{sf_code}" if sf_code else hosts["savefiles"]
    elif hosts.get("vidara"):
        vd_code = extract_filecode(hosts["vidara"])
        embed_url = f"https://vidara.so/v/{vd_code}" if vd_code else hosts["vidara"]
    elif hosts.get("byse"):
        embed_url = hosts.get("byse")

    active_host = None
    if stream_info:
        active_host = stream_info.get("provider")
    elif hosts.get("playmate"):
        active_host = "playmate"
    elif hosts.get("savefiles"):
        active_host = "savefiles"
    elif hosts.get("vidara"):
        active_host = "vidara"

    return {
        "status": "success",
        "tmdb_id": tmdb_id,
        "title": drama.get("title"),
        "season": season,
        "episode": ep,
        "episode_title": target_ep.get("title", f"Episode {ep}"),
        "resolved": stream_info is not None,
        "active_host": active_host,
        "stream_url": stream_info.get("stream_url") if stream_info else None,
        "embed_url": embed_url,
        "audio_tracks": stream_info.get("audio_tracks", ["Hindi"]) if stream_info else ["Hindi"],
        "subtitles": stream_info.get("subtitles", []) if stream_info else [],
        "poster": (stream_info.get("poster") if stream_info else None) or drama.get("poster"),
        "headers": stream_info.get("headers", {}) if stream_info else {},
        "hosts": {k: v for k, v in hosts.items() if v and v != "N/A"}
    }


@app.get("/v1/hi-asian/{tmdb_id}/embed", response_class=HTMLResponse, tags=["Streams"])
def get_episode_embed_player(tmdb_id: int, season: int = 1, ep: int = 1, autoplay: bool = False):
    """
    Zero-config unbranded responsive player for iframe embeds.
    Lytekd or other platforms can simply drop:
      <iframe src="/v1/hi-asian/{tmdb_id}/embed?season=1&ep=1" width="100%" height="100%" frameborder="0" allowfullscreen></iframe>
    Handles Hls.js playback, audio tracks, and automatic invisible fallback if direct HLS blocked.
    """
    drama = db.get_drama(tmdb_id) or json_repo.get_drama(tmdb_id)
    if not drama:
        raise HTTPException(status_code=404, detail="Drama not found.")

    stream_data = get_episode_stream(tmdb_id, season=season, ep=ep)
    stream_url = stream_data.get("stream_url") or ""
    embed_url = stream_data.get("embed_url") or ""
    title = f"{drama.get('title')} - S{season:02d}E{ep:02d}"
    poster = stream_data.get("poster") or ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.7/dist/hls.min.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; background: #000; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    #player-container {{ width: 100%; height: 100%; position: relative; display: flex; align-items: center; justify-content: center; }}
    video {{ width: 100%; height: 100%; object-fit: contain; outline: none; }}
    iframe {{ width: 100%; height: 100%; border: none; }}
    .audio-badge {{
      position: absolute; top: 12px; right: 12px; background: rgba(15, 23, 42, 0.85);
      backdrop-filter: blur(8px); color: #38bdf8; padding: 6px 12px; border-radius: 6px;
      font-size: 12px; font-weight: 600; border: 1px solid rgba(56, 189, 248, 0.3);
      z-index: 10; pointer-events: none; text-transform: uppercase; letter-spacing: 0.5px;
    }}
  </style>
</head>
<body>
  <div id="player-container">
    <div class="audio-badge">🔊 Hindi Dubbed</div>
    <video id="video" controls playsinline poster="{poster}" {'autoplay' if autoplay else ''}></video>
  </div>
  <script>
    const streamUrl = "{stream_url}";
    const fallbackEmbed = "{embed_url}";
    const video = document.getElementById('video');
    const container = document.getElementById('player-container');

    function loadIframeFallback() {{
      if (!fallbackEmbed) return;
      container.innerHTML = '<iframe src="' + fallbackEmbed + '" allow="autoplay; fullscreen; encrypted-media" allowfullscreen></iframe>';
    }}

    if (streamUrl && Hls.isSupported()) {{
      const hls = new Hls({{
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 90
      }});
      hls.loadSource(streamUrl);
      hls.attachMedia(video);
      hls.on(Hls.Events.ERROR, function(event, data) {{
        if (data.fatal) {{
          console.warn("HLS playback fatal error, falling back to host iframe...", data);
          hls.destroy();
          loadIframeFallback();
        }}
      }});
    }} else if (streamUrl && video.canPlayType('application/vnd.apple.mpegurl')) {{
      video.src = streamUrl;
      video.onerror = loadIframeFallback;
    }} else {{
      loadIframeFallback();
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/v1/hi-asian", tags=["Dramas"])
def list_dramas() -> List[Dict[str, Any]]:
    """
    List all stored dramas in the database.
    """
    dramas = db.list_dramas()
    if not dramas:
        dramas = json_repo.list_all()
    return dramas


@app.post("/v1/hi-asian/ingest", tags=["Ingest"])
def trigger_ingest(req: IngestRequest, background_tasks: BackgroundTasks):
    """
    Trigger whole-series drama processing in background.
    """
    def run_process():
        script_path = Path(__file__).resolve().parent.parent / "batch_korean_ingest.py"
        subprocess.run([sys.executable, str(script_path), "--drama-url", req.url])

    background_tasks.add_task(run_process)
    return {
        "status": "queued",
        "message": f"Processing started in background for: {req.url}",
        "url": req.url
    }


@app.post("/v1/crawler/refresh", tags=["Crawler"])
def refresh_crawler_feed(pages: int = 3):
    """
    Quick daily sync: crawls recent pages of Korean & Chinese drama categories.
    Detects newly added dramas or new episode updates.
    """
    from services.crawler import run_refresh
    summary = run_refresh(max_pages=pages)
    return summary


@app.get("/v1/crawler/queue", tags=["Crawler"])
def get_crawler_queue(
    category: str = None,
    status: str = None,
    limit: int = 150
) -> List[Dict[str, Any]]:
    """
    Get all tracked Korean & Chinese dramas in the queue.
    """
    return db.list_crawler_items(category=category, status=status, limit=limit)


@app.post("/v1/crawler/crawl-all", tags=["Crawler"])
def crawl_all_archive(background_tasks: BackgroundTasks):
    """
    Run full historical crawl of all Korean & Chinese drama archive pages.
    """
    from services.crawler import run_full_crawl
    background_tasks.add_task(run_full_crawl)
    return {
        "status": "queued",
        "message": "Full crawl started in background. The queue will populate automatically."
    }


class QuarantineOverrideRequest(BaseModel):
    tmdb_id: int
    season_number: int = 1
    episode_number: int
    host_vidara: Optional[str] = None
    host_byse: Optional[str] = None


@app.get("/v1/ingest/quarantine", tags=["Quarantine"])
def list_quarantine_items(status: Optional[str] = None, limit: int = 100):
    """List quarantined failure tasks with diagnostics."""
    return db.list_quarantine_items(status=status, limit=limit)


@app.post("/v1/ingest/quarantine/override", tags=["Quarantine"])
def override_quarantine(req: QuarantineOverrideRequest):
    """Manually supply or fix links for an episode and clear quarantine."""
    return db.manual_override_episode(
        tmdb_id=req.tmdb_id,
        season_number=req.season_number,
        episode_number=req.episode_number,
        host_vidara=req.host_vidara,
        host_byse=req.host_byse
    )

