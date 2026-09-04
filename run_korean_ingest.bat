@echo off
chcp 65001 >nul
title KDramaLover Korean Drama Auto-Ingest Service

echo ==============================================================================
echo   KDramaLover Korean Drama Hindi Dubbed Auto Ingest & Cloud Storage
echo ==============================================================================
echo.
echo Starting batch Korean drama ingestion service...
echo You can pass optional arguments (e.g. --pages 5, --workers 3, --limit-eps 2)
echo.

python "%~dp0batch_korean_ingest.py" %*

echo.
echo ==============================================================================
echo Batch process complete or paused.
echo ==============================================================================
pause
