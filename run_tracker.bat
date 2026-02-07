@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM logsディレクトリがなければ作成
if not exist logs mkdir logs

REM 日本語Windows用の日付取得 (YYYY/MM/DD形式対応)
for /f "tokens=1-3 delims=/" %%a in ("%date%") do (
    set YYYY=%%a
    set MM=%%b
    set DD=%%c
)

echo ========================================
echo Journal Tracker 実行開始: %date% %time%
echo ========================================

python -m src.main

echo.
echo ========================================
echo 実行完了: %date% %time%
echo ========================================
echo.
pause
