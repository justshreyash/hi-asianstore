# 🎬 Hindi-Asian Drama Auto-Ingestion & Streaming Platform

A production-grade, highly observable, and resilient automation engine for ingesting, cataloging, and streaming **Hindi-Dubbed Korean & Chinese Dramas**. 

Features an automated scraping pipeline, multi-host remote cloud storage across **SaveFiles**, **Playmate**, and **Vidara**, with instant zero-lag **on-the-fly HLS M3U8 stream resolution**, dual-audio support (Hindi + Korean), Turso/SQLite database persistence, and an **embeddable streaming widget** for websites like `lytekd`.

---

## ⚡ Architecture: The 3-Host Trio & Instant Failover

Every episode is preserved across three video hosting providers with automatic failover:

| Host | Remote URL Upload | M3U8 Extraction Method | Resolution Latency | CORS Policy | Multi-Audio |
|---|---|---|---|---|---|
| **Playmate** | `/upload/url` | **Direct JSON POST `/api/s`** | **~150ms** | `*` (Open) | ✅ Hindi + Korean |
| **Vidara** | `/v1/upload/url` | Stream API `/api/stream` | ~0.8s | `*` (Open) | ✅ Hindi + Korean |
| **SaveFiles** | `/api/upload/url` | Regex on Embed HTML | ~1.2s | `*` (Open) | ✅ Hindi + Korean |

---

## 🔑 Environment Configuration (`.env`)

All credentials and options are centralized in `.env` (copied from `.env.example`).

### Serial Index of Environment Variables:
1. `VIDARA_API_KEY`: Remote upload API key for Vidara.so (Pre-configured)
2. `SAVEFILES_API_KEY`: Remote upload API key for SaveFiles.com (Pre-configured)
3. `PLAYMATE_API_KEY`: Remote upload API key for Playmate.to (Pre-configured)
4. `BYSE_API_KEY`: Remote upload API key for Byse.sx (Pre-configured legacy fallback)
5. `TURSO_DATABASE_URL`: Cloud SQLite connection URL (e.g. `libsql://hindi-asian-...turso.io`)
6. `TURSO_AUTH_TOKEN`: Cloud SQLite Auth Token from Turso
7. `TELEGRAM_BOT_TOKEN`: Telegram Bot token from @BotFather for webhook alerts
8. `TELEGRAM_CHAT_ID`: Telegram Chat / Channel ID for alert delivery
9. `API_BASE_URL`: Base URL of the deployed API (e.g. `https://your-api.vercel.app` or `http://127.0.0.1:8000`)
10. `ALLOWED_ORIGINS`: Comma-separated CORS allowed domains (e.g. `https://lytekd.com,*`)
11. `DEFAULT_CONCURRENCY`: Worker thread count for batch uploads (default: `6`)

---

## 🛠️ Unified CLI (`manage.py`)

All manual, maintenance, and admin operations are handled through `manage.py`:

```bash
# 1. View storage metrics, provider coverage & crawler queue
python manage.py stats

# 2. Batch ingest Korean Dramas (All 38 pages or specific page count)
python manage.py ingest --category korean-drama --all --workers 6
python manage.py ingest --category korean-drama --pages 5 --workers 6

# 3. Batch ingest Chinese Dramas (All 16 pages or specific page count)
python manage.py ingest --category chinese-drama --all --workers 6
python manage.py ingest --category chinese-drama --pages 5 --workers 6

# 4. Automatically retry all quarantined/failed episodes
python manage.py retry-quarantine --workers 6

# 5. Synchronize local SQLite records to Turso Cloud Database
python manage.py db-push

# 6. Test Telegram Bot Webhook Notification
python manage.py test-telegram

# 7. Start local FastAPI Server on Port 8000
python manage.py run-api --port 8000

# 8. Manually override or supply links for an episode
python manage.py override --tmdb 93405 --ep 1 --playmate "1w5LAUbS08oi"
```

---

## 🌐 Embeddable Streaming Widget for `lytekd`

Embed the zero-dependency player widget on any website or drama details page:

```html
<!-- Place inside your drama details page container -->
<div id="hindi-dub-widget" data-tmdb="93405" data-title="Squid Game"></div>

<!-- Include the widget script from your API -->
<script src="https://your-api.vercel.app/widget.js" async></script>
```

### The 3 UX States Handled by the Widget:
1. **Available (Instant Stream)**:
   - Displays `🔊 Hindi Dubbed • 1080p FHD`.
   - Responsive HLS video player with episode selector.
   - Provider mirror switcher (Auto Fast / Playmate / Vidara / SaveFiles).
2. **In-Queue (On-Demand Request)**:
   - Displays `⚡ Hindi Dub Available on Source • [Request Instant Upload]`.
   - Clicking dispatches an on-demand ingest request to your Telegram bot and displays an animated progress bar (`ETA: ~2-3 mins`).
   - Polls every 10 seconds and automatically switches to the player once ready.
3. **Unavailable**:
   - Subtle banner: `ℹ️ Hindi Dub not yet released. Streaming in Original Audio.`

---

## 🚀 Vercel Deployment Guide

1. Push your repository to GitHub.
2. Go to [vercel.com](https://vercel.com) and click **Add New Project**.
3. Import this repository.
4. Under **Settings > Environment Variables**, add:
   - `TURSO_DATABASE_URL`: `libsql://hindi-asian-...turso.io`
   - `TURSO_AUTH_TOKEN`: `<your-turso-token>`
   - `VIDARA_API_KEY`: `cc6630108e04a26c58513a923b643e1d30e5c6295b9052100ab4e0578d13aa32`
   - `PLAYMATE_API_KEY`: `deaf804d60034a3e2a42ccf4a0cfd2b8f6ce1f892f00cea2cba52e57dba7d052`
   - `SAVEFILES_API_KEY`: `12788yw4xeco1sk20glq0`
   - `TELEGRAM_BOT_TOKEN`: `<your-bot-token>` (Optional)
   - `TELEGRAM_CHAT_ID`: `<your-chat-id>` (Optional)
5. Click **Deploy**. Vercel will instantly build and serve:
   - `https://your-app.vercel.app/` (API root)
   - `https://your-app.vercel.app/widget.js` (Embeddable Widget)
   - `https://your-app.vercel.app/demo/widget` (Interactive Widget Demo)
   - `https://your-app.vercel.app/v1/hi-asian/{tmdb_id}` (Metadata)
   - `https://your-app.vercel.app/v1/hi-asian/{tmdb_id}/resolve-m3u8` (M3U8 Resolver)

---

## ⏰ Automated Scheduled Cron (GitHub Actions)

A pre-configured GitHub Actions workflow (`.github/workflows/cron_sync.yml`) runs every 4 hours automatically:
- Crawls pages 1–3 of Korean and Chinese dramas for new releases.
- Transcodes & uploads new episodes to Vidara + Playmate.
- Pushes new records to Turso Cloud SQLite.
- Sends a structured Markdown report to your private Telegram Bot.

To configure, add the same secrets under your GitHub repository's **Settings > Secrets and variables > Actions**.

---

## 📁 Directory Structure

```
hi-kr-auto-store/
├── api/
│   ├── app.py                      # FastAPI server routes
│   ├── index.py                    # Vercel serverless entrypoint
│   └── __init__.py
├── bot/
│   ├── telegram_notifier.py        # Telegram webhook & Markdown alert generator
│   └── __init__.py
├── data/
│   ├── hindi_asian.db              # Local SQLite Database (Turso-compatible)
│   └── dramas/                     # JSON cache per TMDB ID
├── public/
│   └── widget.js                   # Embeddable streaming player widget for lytekd
├── integration/
│   └── test_widget.html            # Test demo page simulating lytekd integration
├── providers/
│   ├── playmate.py                 # Playmate API client
│   ├── vidara.py                   # Vidara API client
│   ├── savefiles.py                # SaveFiles API client
│   └── resolver.py                 # Unified on-the-fly M3U8 resolver
├── storage/
│   ├── sqlite_db.py                # Dual SQLite + Turso sync layer
│   ├── turso_client.py             # Pure-Python Turso HTTP pipeline client
│   └── repository.py               # JSON file repository
├── .github/workflows/
│   └── cron_sync.yml               # Automated scheduled sync cron
├── .env.example                    # Environment template with serial index
├── .env                            # Active environment configuration
├── config.py                       # Centralized configuration loader
├── manage.py                       # Unified CLI management tool
├── vercel.json                     # Vercel serverless deployment config
├── requirements.txt                # Python dependencies
└── README.md                       # Documentation
```
