#!/usr/bin/env python3
"""
Unified CLI Manager for Hindi-Asian Drama Platform
Commands:
  python manage.py stats
  python manage.py ingest --category korean-drama|chinese-drama [--all] [--pages N] [--workers 6]
  python manage.py retry-quarantine [--workers 6]
  python manage.py db-push
  python manage.py test-telegram
  python manage.py cron-sync [--workers 6]
  python manage.py run-api [--port 8000]
  python manage.py override --tmdb <ID> --ep <N> [--playmate <CODE>] [--vidara <CODE>] [--savefiles <CODE>]
"""

import sys
import time
import argparse
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows UTF-8 support
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from storage.sqlite_db import SqliteDatabase
from batch_korean_ingest import KoreanDramaBatchIngestor, retry_quarantine, display_stats


def cmd_stats(args, db):
    display_stats(db)


def cmd_ingest(args, db):
    cat = "chinese-drama" if "chinese" in args.category else "korean-drama"
    ingestor = KoreanDramaBatchIngestor(
        workers=args.workers,
        force=args.force,
        limit_eps=args.limit_eps
    )
    ingestor.run(
        max_pages=args.pages,
        limit_dramas=args.limit_dramas,
        single_url=args.url,
        scan_all=args.all,
        category=cat
    )


def cmd_retry_quarantine(args, db):
    retry_quarantine(db, workers=args.workers)


def cmd_db_push(args, db):
    print("=" * 80)
    print("☁️  SYNCHRONIZING LOCAL SQLITE TO TURSO CLOUD")
    print("=" * 80)
    try:
        res = db.sync_local_to_turso()
        print(f"[✓] Synchronization Complete!")
        print(f" • Dramas Uploaded   : {res['dramas_synced']}")
        print(f" • Episodes Uploaded : {res['episodes_synced']}")
        print("=" * 80)
    except Exception as e:
        print(f"[!] Sync failed: {e}")
        print("Tip: Ensure TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are set in your .env file.")


def cmd_test_telegram(args, db):
    print("=" * 80)
    print("🤖 TESTING TELEGRAM NOTIFICATION WEBHOOK")
    print("=" * 80)
    try:
        from bot.telegram_notifier import send_message, IS_TELEGRAM_ENABLED
        if not IS_TELEGRAM_ENABLED:
            print("[!] Telegram is not enabled. Please set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
            return

        ok = send_message("🟢 *[TEST]* Hindi-Asian Streaming Notifier connection successful!")
        if ok:
            print("[✓] Success! Test alert delivered to your Telegram chat.")
        else:
            print("[!] Telegram returned an error. Check your bot token and chat ID.")
    except Exception as e:
        print(f"[!] Telegram test failed: {e}")


def cmd_cron_sync(args, db):
    """Automated cron sync for scheduled runners (GitHub Actions / background daemons)."""
    t0 = time.time()
    print("=" * 80)
    print("⏰ RUNNING AUTOMATED ASIAN DRAMA CRON SYNC")
    print("=" * 80)

    # 1. Sync Korean Dramas (Pages 1-3 for fresh updates)
    k_ingestor = KoreanDramaBatchIngestor(workers=args.workers, force=False)
    k_ingestor.run(max_pages=3, scan_all=False, category="korean-drama")

    # 2. Sync Chinese Dramas (Pages 1-3 for fresh updates)
    c_ingestor = KoreanDramaBatchIngestor(workers=args.workers, force=False)
    c_ingestor.run(max_pages=3, scan_all=False, category="chinese-drama")

    # 3. If Turso is configured, push new records to cloud
    if db.turso:
        try:
            print("\n[*] Synchronizing updates to Turso Cloud...")
            db.sync_local_to_turso()
            print("[✓] Turso Cloud sync completed.")
        except Exception as e:
            print(f"[!] Turso sync warning: {e}")

    # 4. Dispatch Telegram report
    try:
        from bot.telegram_notifier import send_sync_report
        combined_stats = {
            "duration_sec": round(time.time() - t0, 1),
            "dramas_processed": k_ingestor.stats["dramas_processed"] + c_ingestor.stats["dramas_processed"],
            "dramas_skipped": k_ingestor.stats["dramas_skipped"] + c_ingestor.stats["dramas_skipped"],
            "episodes_uploaded": k_ingestor.stats["episodes_uploaded"] + c_ingestor.stats["episodes_uploaded"],
            "episodes_quarantined": k_ingestor.stats["episodes_quarantined"] + c_ingestor.stats["episodes_quarantined"]
        }
        send_sync_report(combined_stats, category="Korean & Chinese Dramas")
    except Exception as e:
        print(f"[!] Telegram report warning: {e}")

    print("=" * 80)
    print(f"✓ Cron sync execution completed in {round(time.time() - t0, 1)}s.")
    print("=" * 80)


def cmd_run_api(args, db):
    import uvicorn
    print("=" * 80)
    print(f"🚀 LAUNCHING HINDI-ASIAN FASTAPI SERVER ON PORT {args.port}")
    print(f" • API Root       : http://127.0.0.1:{args.port}/")
    print(f" • Stream Widget  : http://127.0.0.1:{args.port}/widget.js")
    print(f" • Demo Preview   : http://127.0.0.1:{args.port}/demo/widget")
    print(f" • Ingestion UI   : http://127.0.0.1:{args.port}/web/ingestion")
    print("=" * 80)
    uvicorn.run("api.app:app", host=args.host, port=args.port, reload=args.reload)


def cmd_override(args, db):
    if not args.tmdb or not args.ep:
        print("[!] Error: --tmdb and --ep are required for override.")
        sys.exit(1)
    res = db.manual_override_episode(
        tmdb_id=args.tmdb,
        season_number=1,
        episode_number=args.ep,
        host_vidara=args.vidara,
        host_byse=args.savefiles or args.byse
    )
    if args.savefiles:
        db.update_episode_savefiles(args.tmdb, 1, args.ep, args.savefiles)
    if args.playmate:
        db.update_episode_playmate(args.tmdb, 1, args.ep, args.playmate)
    print(f"[+] Manual override successful for TMDB {args.tmdb} Ep {args.ep}!")


def main():
    parser = argparse.ArgumentParser(description="Hindi-Asian Drama Platform Unified Manager")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # stats
    subparsers.add_parser("stats", help="Display storage, queue, and provider statistics")

    # ingest
    p_ingest = subparsers.add_parser("ingest", help="Batch ingest dramas from KDramaLover")
    p_ingest.add_argument("--category", type=str, default="korean-drama", choices=["korean-drama", "chinese-drama", "korean", "chinese"], help="Category to ingest")
    p_ingest.add_argument("--all", action="store_true", help="Crawl all available category pages")
    p_ingest.add_argument("--pages", type=int, default=5, help="Number of pages to crawl (default: 5)")
    p_ingest.add_argument("--workers", type=int, default=6, help="Concurrent worker threads (default: 6)")
    p_ingest.add_argument("--limit-dramas", type=int, default=None, help="Limit number of dramas")
    p_ingest.add_argument("--limit-eps", type=int, default=None, help="Limit number of episodes per drama")
    p_ingest.add_argument("--url", type=str, default=None, help="Process single specific drama URL")
    p_ingest.add_argument("--force", action="store_true", help="Force re-upload even if cached")

    # retry-quarantine
    p_retry = subparsers.add_parser("retry-quarantine", help="Auto-retry quarantined episodes")
    p_retry.add_argument("--workers", type=int, default=6, help="Concurrent worker threads (default: 6)")

    # db-push
    subparsers.add_parser("db-push", help="Synchronize local SQLite to Turso Cloud database")

    # test-telegram
    subparsers.add_parser("test-telegram", help="Send a test notification to your private Telegram bot")

    # cron-sync
    p_cron = subparsers.add_parser("cron-sync", help="Run automated sync and push reports (for GitHub Actions)")
    p_cron.add_argument("--workers", type=int, default=6, help="Concurrent worker threads (default: 6)")

    # run-api
    p_api = subparsers.add_parser("run-api", help="Launch FastAPI server")
    p_api.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_api.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    p_api.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # override
    p_ov = subparsers.add_parser("override", help="Manually override or supply links for an episode")
    p_ov.add_argument("--tmdb", type=int, required=True, help="TMDB ID")
    p_ov.add_argument("--ep", type=int, required=True, help="Episode number")
    p_ov.add_argument("--playmate", type=str, default=None, help="Playmate filecode or URL")
    p_ov.add_argument("--vidara", type=str, default=None, help="Vidara filecode or URL")
    p_ov.add_argument("--savefiles", type=str, default=None, help="SaveFiles filecode or URL")
    p_ov.add_argument("--byse", type=str, default=None, help="Legacy Byse filecode or URL")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = SqliteDatabase()

    commands = {
        "stats": cmd_stats,
        "ingest": cmd_ingest,
        "retry-quarantine": cmd_retry_quarantine,
        "db-push": cmd_db_push,
        "test-telegram": cmd_test_telegram,
        "cron-sync": cmd_cron_sync,
        "run-api": cmd_run_api,
        "override": cmd_override
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn(args, db)


if __name__ == "__main__":
    main()
