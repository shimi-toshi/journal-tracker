#!/usr/bin/env bash
# 開発・テスト環境のセットアップ（Claude Code / Codex 等のエージェント用）。
# Claude Code on the web では SessionStart フック（.claude/settings.json）から自動実行される。
# ローカル環境の Python を勝手に書き換えないよう、フック経由ではリモート環境でのみ動く。
set -euo pipefail

if [ "${1:-}" != "--force" ] && [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$(dirname "$0")/.."
python -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
echo "journal-tracker: dev dependencies installed (pytest で tests/ を実行可能)"
