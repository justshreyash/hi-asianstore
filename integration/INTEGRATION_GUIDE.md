# Hindi Dubbed Stream Integration Guide
========================================

This `/integration` directory contains standalone, production-ready files designed to integrate Hindi-dubbed streams into your drama streaming website.

---

## 📁 Files Included

| File | Purpose |
| :--- | :--- |
| [`hindi_stream_service.py`](hindi_stream_service.py) | **Core Python Service**: Directly queries SQLite/Turso database to verify Hindi availability and dynamically resolves active master `.m3u8` stream URLs on the fly via Vidara. |
| [`api_server.py`](api_server.py) | **Standalone Micro-API Server**: Zero-dependency HTTP server with CORS enabled. Serves `/api/hindi/check` and `/api/hindi/stream`. |
| [`hindi_stream.js`](hindi_stream.js) | **Plug-and-Play Frontend Widget**: Client library with one-line button mounting (`HindiStream.mountButton`), auto loading state, and HLS.js player binding. |
| [`demo_stream_player.html`](demo_stream_player.html) | **Complete Standalone Player Page**: Ready-to-run demo showing drama selection, episode selection, "Check Hindi Available & Stream" button, and embedded video player. |

---

## 🚀 Quick Start (Running the Standalone Micro-API & Demo)

1. Start the integration API server:
   ```bash
   python integration/api_server.py --port 8080
   ```

2. Open the demo player in your browser:
   ```
   http://127.0.0.1:8080/demo
   ```
   - Select a drama (e.g. *Filing for Love*, TMDB: `297640`).
   - Select an episode (e.g. Episode 1).
   - Click **"⚡ Check Hindi Available & Stream"**.
   - It checks the database, resolves the fresh active `.m3u8` token on the fly, provides the direct URL, and immediately starts playback in the player!

---

## 🛠 Integration Options for Your Website

### Option 1: Drop-In Frontend Widget (`hindi_stream.js`)

Add this snippet to your streaming website's episode page:

```html
<!-- 1. Include Hls.js and HindiStream SDK -->
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script src="path/to/hindi_stream.js"></script>

<!-- 2. Container for the Hindi button -->
<div id="hindi-button-container"></div>

<!-- 3. Your website's existing HTML5 video element -->
<video id="main-player" controls playsinline width="100%"></video>

<!-- 4. Mount the button -->
<script>
  HindiStream.mountButton({
    container: "#hindi-button-container",
    apiBase: "http://your-backend-domain:8080",
    tmdbId: 297640,       // Pass current drama TMDB ID
    season: 1,            // Current season
    episode: 1,           // Current episode
    videoElement: "#main-player",  // Auto-play when resolved
    onStreamReady: function(streamData) {
      console.log("Fresh Master M3U8:", streamData.m3u8_url);
      console.log("Audio Tracks:", streamData.audio_tracks);
    },
    onNotAvailable: function(info) {
      alert("Hindi dub not available: " + info.reason);
    }
  });
</script>
```

---

### Option 2: REST API Endpoints (For React, Vue, Next.js, or PHP)

If your website already has its own UI and you just need the data:

#### 1. Fast Database Availability Check
```http
GET /api/hindi/check?tmdb_id=297640&season=1&episode=1
```
**Response if available:**
```json
{
  "available": true,
  "tmdb_id": 297640,
  "drama_title": "Filing for Love",
  "season": 1,
  "episode": 1,
  "filecode": "921f8f2e78a0",
  "status": "ready_to_resolve"
}
```
**Response if NOT available:**
```json
{
  "available": false,
  "tmdb_id": 999999,
  "reason": "Drama (TMDB ID: 999999) is not in the Hindi-Asian database."
}
```

#### 2. On-The-Fly M3U8 Stream Resolver
```http
GET /api/hindi/stream?tmdb_id=297640&season=1&episode=1
```
**Response:**
```json
{
  "success": true,
  "available": true,
  "tmdb_id": 297640,
  "drama_title": "Filing for Love",
  "season": 1,
  "episode": 1,
  "m3u8_url": "https://p1-s100-d5.s1q2105.com/hls/.../master.m3u8?token=...",
  "headers": {
    "Origin": "https://vidarae.live",
    "Referer": "https://vidarae.live/e/921f8f2e78a0"
  },
  "audio_tracks": ["Hindi", "Korean"],
  "subtitles": [
    {
      "language": "English",
      "file_path": "https://...subtitle.vtt"
    }
  ],
  "thumbnail": "https://...thumbnail.jpg"
}
```

---

### Option 3: Python Backend Integration (FastAPI / Django / Flask)

If your streaming platform is written in Python, you don't even need the HTTP API server. You can import `HindiStreamService` directly:

```python
from integration.hindi_stream_service import HindiStreamService

service = HindiStreamService()

# 1. Check availability
check = service.check_availability(tmdb_id=297640, season=1, episode=1)
if check["available"]:
    print(f"Hindi is available for {check['drama_title']}")

# 2. Get fresh on-the-fly M3U8 directly
stream = service.resolve_stream(tmdb_id=297640, season=1, episode=1)
if stream.get("success"):
    m3u8_url = stream["m3u8_url"]
    print(f"Direct stream URL: {m3u8_url}")
```

---

## ⚙ Database Configuration

By default, the service connects to `data/hindi_asian.db`.
You can customize the location using the `HINDI_DB_PATH` environment variable:

```bash
export HINDI_DB_PATH="/path/to/your/hindi_asian.db"
python api_server.py --port 8080
```
