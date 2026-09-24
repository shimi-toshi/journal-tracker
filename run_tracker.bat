@echo off
chcp 65001 > nul
cd /d "%~dp0"

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
