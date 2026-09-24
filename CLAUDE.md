# CLAUDE.md

このリポジトリのエージェント向け情報は **AGENTS.md に一本化**している（Codex 等と共通の正本）。
内容の二重管理を避けるため、ここには書き足さず AGENTS.md を更新すること。

@AGENTS.md

## Claude Code 固有の補足
- Claude Code on the web では SessionStart フック（`.claude/settings.json` → `scripts/setup_dev.sh`）が依存を自動インストールする。
- 改善作業を始めるときは AGENTS.md §3「現状把握」→ §4「改善サイクル」の順に進める。
