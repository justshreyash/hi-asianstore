"""
Telegram Bot Webhook & Reporting Module
Sends automated Markdown notifications for cron syncs, quarantine alerts, and on-demand user requests.
"""

import requests
from typing import Optional, Dict, Any

try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, IS_TELEGRAM_ENABLED
except ImportError:
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""
    IS_TELEGRAM_ENABLED = False


def send_message(text: str) -> bool:
    """Send a Markdown-formatted message to the configured private Telegram chat."""
    if not IS_TELEGRAM_ENABLED or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[!] Telegram notification error: {e}")
        return False


def send_sync_report(stats: Dict[str, Any], category: str = "Asian Drama") -> bool:
    """Format and dispatch a cron synchronization summary."""
    duration_min = round(stats.get("duration_sec", 0) / 60, 1)
    msg = (
        f"🟢 *[CRON SYNC COMPLETED]*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📂 *Category*   : `{category}`\n"
        f"⏱️ *Duration*   : `{duration_min} min`\n"
        f"✨ *Completed*  : *{stats.get('dramas_processed', 0)}* drama(s)\n"
        f"⏭️ *Skipped*    : *{stats.get('dramas_skipped', 0)}* cached\n"
        f"📹 *Episodes*   : *{stats.get('episodes_uploaded', 0)}* uploaded\n"
        f"⚠️ *Quarantined*: *{stats.get('episodes_quarantined', 0)}* task(s)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✓ _Streams available immediately via M3U8 API & Lytekd Widget_"
    )
    return send_message(msg)


def send_quarantine_alert(tmdb_id: int, drama_title: str, episode_number: int, failure_code: str, detail: str = "") -> bool:
    """Alert on a specific failed episode with a copy-paste CLI fix command."""
    msg = (
        f"🔴 *[INGESTION QUARANTINE ALERT]*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 *Drama*   : `{drama_title}` (TMDB `{tmdb_id}`)\n"
        f"📍 *Episode* : `Episode {episode_number}`\n"
        f"❌ *Code*    : `{failure_code}`\n"
        f"📝 *Detail*  : _{detail[:100]}_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ *Quick Fix Command*:\n"
        f"`python manage.py override --tmdb {tmdb_id} --ep {episode_number} --playmate <CODE>`"
    )
    return send_message(msg)


def send_user_request_alert(tmdb_id: int, title: str) -> bool:
    """Notify when a user clicks 'Request Instant Ingest' on lytekd."""
    msg = (
        f"⚡ *[USER ON-DEMAND REQUEST]*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"A user requested Hindi Dub on Lytekd:\n"
        f"🎬 *Title*   : *{title}*\n"
        f"🆔 *TMDB ID* : `{tmdb_id}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Task added to priority crawler queue."
    )
    return send_message(msg)
