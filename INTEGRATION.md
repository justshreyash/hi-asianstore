# 🎬 Hindi-Asian Stream Platform - Complete Integration Guide

This guide details **everything** needed to integrate Hindi-dubbed Korean and Chinese drama streams into any external website or platform (e.g., **Lytekd**, custom streaming portals, mobile apps, or headless frontends).

---

## 🌐 Production Environment

* **Production API Base**: `https://hi-asianstore.vercel.app`
* **Local Dev API Base**: `http://127.0.0.1:8000`
* **CORS Policy**: Enabled for all origins (`*`)
* **Cloud Database**: Turso LibSQL (374+ dramas, 5,540+ episodes pre-indexed)
* **Stream Hosts**: Playmate (Primary HLS), SaveFiles (Dual-Audio HLS), Vidara (Backup)

---

## 🚀 Choose Your Integration Strategy

| Method | Best For | Complexity | CORS / Header Headaches |
| :--- | :--- | :---: | :---: |
| **1. Unbranded Responsive Embed** | Lytekd & self-styled platforms | **Zero-Code** (1 iframe) | **None** (Browser sandbox handles all) |
| **2. Clean JSON Stream API** | Custom Video.js / Plyr / Hls.js players | Moderate | **None** on Playmate/Savefiles (Open CORS) |
| **3. Drop-in Dynamic Widget** | Blogs, review sites, quick integration | Easy (1 script tag) | **None** |
| **4. Metadata & Search APIs** | Building catalog, search, or badges | Simple REST | **None** |

---

## 📺 Method 1: Unbranded Responsive Embed (`<iframe>`) [Recommended for Lytekd]

This is the cleanest and most reliable integration method. Lytekd or third-party developers retain **100% control over page layout, styles, episode drawer, synopsis, and theme**. Inside your player box, drop this clean, ad-free iframe:

### Endpoint
```http
GET https://hi-asianstore.vercel.app/v1/hi-asian/{tmdb_id}/embed?season={season}&ep={episode}
```

### Ready-to-Copy HTML & CSS Snippet

```html
<!-- Container styled by your platform (aspect-ratio, rounded corners, borders) -->
<div class="drama-player-container">
  <iframe 
    id="hindi-player"
    src="https://hi-asianstore.vercel.app/v1/hi-asian/297640/embed?season=1&ep=1" 
    width="100%" 
    height="100%" 
    frameborder="0" 
    allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
    allowfullscreen>
  </iframe>
</div>

<style>
  .drama-player-container {
    width: 100%;
    max-width: 1100px;
    aspect-ratio: 16 / 9;
    background: #000;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
    border: 1px solid #1e293b;
    margin: 0 auto;
  }
</style>
```

### TailWind CSS Example:
```html
<div class="w-full aspect-video rounded-2xl overflow-hidden shadow-2xl border border-slate-800 bg-black">
  <iframe 
    src="https://hi-asianstore.vercel.app/v1/hi-asian/297640/embed?season=1&ep=1" 
    class="w-full h-full border-0" 
    allow="autoplay; fullscreen; encrypted-media" 
    allowfullscreen>
  </iframe>
</div>
```

### Why this solves all playback issues:
1. **Zero Referer / Origin issues**: Video hosts that restrict referrers (e.g. Vidara) are executed safely within their native iframe context.
2. **Invisible Failover**: If direct HLS encounters network blocks, the player invisibly falls back to the native host iframe.
3. **Multi-Audio**: Displays a discreet `🔊 HINDI DUBBED` badge and enables track selection (Hindi/Korean) automatically.

---

## ⚡ Method 2: Direct REST Stream API (For Custom Players)

If you are using your own player instance (**Video.js**, **Plyr**, **ArtPlayer**, or **Hls.js** directly), fetch the active master `.m3u8` stream on the fly.

### Endpoint
```http
GET https://hi-asianstore.vercel.app/v1/hi-asian/{tmdb_id}/stream?season={season}&ep={episode}
```

### Real Sample Response (`200 OK`)
```json
{
  "status": "success",
  "tmdb_id": 297640,
  "title": "Filing for Love",
  "season": 1,
  "episode": 1,
  "episode_title": "Episode 1",
  "resolved": true,
  "active_host": "savefiles",
  "stream_url": "https://s3.savefiles.com/hls2/01/00434/,p87tgt68lzck_n,lang/eng/p87tgt68lzck_eng,.urlset/master.m3u8?t=VEay22vV...&s=1788553063",
  "embed_url": "https://playmate.to/embed/1w5LAUbS08oi",
  "audio_tracks": [
    "Hindi",
    "Korean"
  ],
  "subtitles": [
    "English"
  ],
  "poster": "https://img.savefiles.com/p87tgt68lzck_xt.jpg",
  "headers": {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)..."
  },
  "hosts": {
    "playmate": "https://playmate.to/embed/1w5LAUbS08oi",
    "savefiles": "https://savefiles.com/p87tgt68lzck",
    "vidara": "https://vidara.so/v/921f8f2e78a0",
    "byse": "https://byse.sx/e/2smj8jy21djk"
  }
}
```

### JavaScript / Hls.js Integration with Fallback:

```javascript
async function loadHindiEpisode(tmdbId, season, episode, videoElementId, playerContainerId) {
  const url = `https://hi-asianstore.vercel.app/v1/hi-asian/${tmdbId}/stream?season=${season}&ep=${episode}`;
  const res = await fetch(url);
  const data = await res.json();

  if (!data.resolved && !data.embed_url) {
    alert("Stream unavailable for this episode.");
    return;
  }

  const video = document.getElementById(videoElementId);
  const container = document.getElementById(playerContainerId);

  // Helper fallback to clean iframe if raw HLS fails
  function fallbackToIframe() {
    if (data.embed_url) {
      container.innerHTML = `<iframe src="${data.embed_url}" width="100%" height="100%" frameborder="0" allowfullscreen></iframe>`;
    }
  }

  // 1. If direct HLS is available (Playmate or SaveFiles have open CORS)
  if (data.stream_url && Hls.isSupported()) {
    const hls = new Hls({ enableWorker: true, lowLatencyMode: true });
    hls.loadSource(data.stream_url);
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, function(event, err) {
      if (err.fatal) {
        console.warn("HLS fatal error. Falling back to host iframe...", err);
        hls.destroy();
        fallbackToIframe();
      }
    });
  } 
  // 2. Native Safari HLS
  else if (data.stream_url && video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = data.stream_url;
    video.onerror = fallbackToIframe;
  } 
  // 3. Direct embed fallback
  else {
    fallbackToIframe();
  }
}
```

---

## 🔍 Method 3: Fast Availability Check & Metadata APIs

Use these endpoints to dynamically show a **"🔊 Hindi Dub Available"** tag or dropdown button on your drama details page without loading heavy video streams.

### 1. Fast Availability Check (`< 5ms`)
```http
GET https://hi-asianstore.vercel.app/v1/hi-asian/check?tmdb_id={tmdb_id}
```
**Response if Available (`200 OK`):**
```json
{
  "status": "available",
  "tmdb_id": 297640,
  "title": "Filing for Love",
  "clean_title": "Filing for Love",
  "quality": "1080p",
  "episodes_count": 12,
  "episodes": [
    { "episode_number": 1, "title": "Episode 1" },
    { "episode_number": 2, "title": "Episode 2" },
    ...
  ]
}
```
**Response if NOT Available (`200 OK`):**
```json
{
  "status": "unavailable",
  "tmdb_id": 999999,
  "message": "Hindi Dub not yet available for this drama."
}
```

### 2. Full Drama Details & Episode Mirrors
```http
GET https://hi-asianstore.vercel.app/v1/hi-asian/{tmdb_id}
```
Returns complete metadata, overview, poster URL, rating, genres, and all episode links across Playmate, SaveFiles, and Vidara.

### 3. List All Available Hindi Dramas
```http
GET https://hi-asianstore.vercel.app/v1/hi-asian
```
Returns an array of all 374+ dramas indexed in the database.

---

## 🧩 Method 4: Drop-in Floating / Inline Widget (`widget.js`)

If you want a pre-built interactive UI with episode cards and one-click stream switching without writing custom frontend code:

```html
<!-- 1. Place the widget container anywhere on your page -->
<div 
  id="hindi-dub-widget" 
  data-tmdb="297640" 
  data-title="Filing for Love"
  data-theme="dark">
</div>

<!-- 2. Load the widget script -->
<script src="https://hi-asianstore.vercel.app/widget.js" async></script>
```

The widget automatically queries the API, renders an interactive episode selector, and mounts a player seamlessly.

---

## 📥 Method 5: User On-Demand Ingestion Request

When a user searches for a drama that isn't yet available in Hindi, you can let them click a **"Request Hindi Dub"** button. This notifies your Telegram and places the drama in priority queue:

```http
POST https://hi-asianstore.vercel.app/v1/hi-asian/request-ingest
Content-Type: application/json

{
  "tmdb_id": 93405,
  "title": "Squid Game"
}
```

**Response:**
```json
{
  "status": "queued",
  "tmdb_id": 93405,
  "title": "Squid Game",
  "message": "Ingestion request for 'Squid Game' logged successfully.",
  "estimated_eta_seconds": 180
}
```

---

## 📋 API Endpoints Cheat Sheet

| Endpoint | Method | Params | Description |
| :--- | :---: | :--- | :--- |
| `/v1/hi-asian/check` | `GET` | `tmdb_id` or `title` | Fast check if drama has Hindi dubs available |
| `/v1/hi-asian/{tmdb_id}/stream` | `GET` | `season=1`, `ep=1` | Fresh M3U8 URL, audio tracks, and mirror embeds |
| `/v1/hi-asian/{tmdb_id}/embed` | `GET` | `season=1`, `ep=1` | Responsive unbranded HTML player for iframes |
| `/v1/hi-asian/{tmdb_id}` | `GET` | - | Full metadata, synopsis, and all season/episode mirrors |
| `/v1/hi-asian` | `GET` | - | List all indexed Hindi dramas |
| `/v1/hi-asian/request-ingest` | `POST` | `{ tmdb_id, title }` | Queue missing drama for auto-crawler + Telegram alert |
| `/widget.js` | `GET` | - | Embeddable drop-in client widget script |
| `/` | `GET` | - | Service health status and database connectivity |

---

## 🛡️ Best Practices for Seamless Playback

1. **Always use `/embed` or check `embed_url` fallback**: While Playmate and SaveFiles M3U8 streams have open CORS, third-party network adblockers or browser security policies may occasionally interfere with raw `.m3u8` fetches. Using the embed iframe guarantees 100% video delivery across all browsers and devices.
2. **Cache availability checks**: The `/v1/hi-asian/check` endpoint is ultra-fast (`<5ms`). You can cache the response on your server or in LocalStorage for 1 hour to reduce client network requests.
3. **Responsive iframes**: Always wrap player iframes in a container with `aspect-ratio: 16 / 9` and `width: 100%` so mobile devices scale video seamlessly.
