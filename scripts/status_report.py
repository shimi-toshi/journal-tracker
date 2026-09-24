"""運用状態の現状把握レポート（エージェント／保守担当向け・読み取り専用）。

改善サイクルの最初に実行し、「どの誌が取れていないか」「データ品質に問題はないか」
「直近の実行は成功したか」を一目で把握するためのスクリプト。DBは読み取り専用で開くため、
実行しても data/papers.db に差分は出ない（git を汚さない）。

使い方（リポジトリルートから）:
    python -m scripts.status_report            # 人間/エージェント向けテキスト（要確認事項を先頭に表示）
    python -m scripts.status_report --json     # 機械可読JSON（全項目）
    python -m scripts.status_report --config path/to/config.yaml
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from src.parser import clean_markup, is_excluded_title
from src.storage import PaperStorage
from src.utils import load_config, load_journals_from_excel, load_title_exclusions, resolve_path

# この日数以上、新着が1件も無い誌は「ISSN誤り・取得不全の兆候」として要確認に挙げる
STALE_DAYS = 30


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def build_report(config: dict, now: datetime | None = None) -> dict:
    """現状レポートを辞書で構築する"""
    now = now or datetime.now()
    db_path = resolve_path(config.get("database", {}).get("path", "data/papers.db"))
    html_config = config.get("html_export", {})
    threshold = html_config.get("failure_threshold", 7)
    lag_days = html_config.get("max_publication_lag_days", 60)
    exclusions = load_title_exclusions(config)

    excel_path = config.get("journals", {}).get("excel_path", "")
    journals = load_journals_from_excel(excel_path) if excel_path else []
    journal_names = {j.name for j in journals}

    report: dict = {
        "generated_at": now.isoformat(timespec="seconds"),
        "db_path": str(db_path),
        "journals_in_list": len(journals),
        "problems": [],
    }

    last_run_path = db_path.parent / "last_run.json"
    if last_run_path.exists():
        try:
            report["last_run"] = json.loads(last_run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report["last_run"] = {"error": f"last_run.json を読めません: {exc}"}
    else:
        report["last_run"] = None

    if not db_path.exists():
        report["problems"].append(f"DBがありません: {db_path}")
        return report

    conn = _connect_readonly(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cutoff_7 = (now - timedelta(days=7)).isoformat()
        cutoff_30 = (now - timedelta(days=30)).isoformat()
        rows = conn.execute("SELECT title, journal_name, published_date, fetched_at FROM papers").fetchall()

        total = len(rows)
        recent_7 = recent_30 = markup_titles = missing_published = 0
        excluded_in_db = excluded_recent = lag_excluded_recent = 0
        per_journal: dict[str, dict] = {}
        for row in rows:
            name = row["journal_name"]
            info = per_journal.setdefault(name, {"total": 0, "papers_30d": 0, "last_fetched": None})
            info["total"] += 1
            fetched = row["fetched_at"] or ""
            if not info["last_fetched"] or fetched > info["last_fetched"]:
                info["last_fetched"] = fetched
            excluded = is_excluded_title(row["title"], exclusions)
            excluded_in_db += excluded
            if clean_markup(row["title"]) != (row["title"] or "").strip():
                markup_titles += 1
            if not row["published_date"]:
                missing_published += 1
            if fetched >= cutoff_30:
                recent_30 += 1
                recent_7 += fetched >= cutoff_7
                if excluded:
                    excluded_recent += 1
                elif row["published_date"]:
                    try:
                        lag = (datetime.fromisoformat(fetched) - datetime.fromisoformat(row["published_date"])).days
                        if lag > lag_days:
                            lag_excluded_recent += 1
                    except ValueError:
                        pass
                if not excluded:
                    info["papers_30d"] += 1

        failing = PaperStorage.failing_journals_from_conn(conn, threshold, now=now)
        status_rows = {
            r["journal_name"]: dict(r) for r in conn.execute("SELECT * FROM journal_status").fetchall()
        }
        schema_version = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    report["database"] = {
        "schema_version": int(schema_version[0]) if schema_version else None,
        "journal_mode": journal_mode,
        "papers_total": total,
        "fetched_last_7d": recent_7,
        "fetched_last_30d": recent_30,
        "hidden_last_30d_non_research": excluded_recent,
        "hidden_last_30d_publication_lag": lag_excluded_recent,
        "non_research_rows_in_db": excluded_in_db,
        "titles_with_markup": markup_titles,
        "published_date_missing_pct": round(100 * missing_published / total, 1) if total else 0.0,
    }

    journal_rows = []
    for j in journals:
        info = per_journal.get(j.name, {"total": 0, "papers_30d": 0, "last_fetched": None})
        status = status_rows.get(j.name, {})
        flags = []
        if not j.issns:
            flags.append("no_issn")
        if j.name in failing:
            flags.append("long_term_failing")
        elif (status.get("consecutive_failures") or 0) > 0:
            flags.append("recent_failure")
        if info["total"] == 0:
            flags.append("no_papers_ever")
        elif info["papers_30d"] == 0:
            flags.append(f"no_new_{STALE_DAYS}d")
        journal_rows.append({
            "name": j.name,
            "abbrev": j.abbreviation,
            "issns": j.issns,
            "papers_total": info["total"],
            "papers_30d": info["papers_30d"],
            "last_fetched": info["last_fetched"],
            "last_success_at": status.get("last_success_at"),
            "consecutive_failures": status.get("consecutive_failures", 0),
            "last_error_type": status.get("last_error_type"),
            "flags": flags,
        })
    report["journals"] = journal_rows
    report["orphan_journals_in_db"] = sorted(set(per_journal) - journal_names)

    problems = report["problems"]
    for r in journal_rows:
        if "long_term_failing" in r["flags"]:
            problems.append(f"長期取得エラー: {r['name']}（連続{r['consecutive_failures']}回, {r['last_error_type']}）")
        if "no_issn" in r["flags"]:
            problems.append(f"ISSN未設定で取得不能: {r['name']}")
        if "no_papers_ever" in r["flags"]:
            problems.append(f"DBに論文が1件もない（ISSN誤りの可能性）: {r['name']}")
    if report["database"]["journal_mode"] != "delete":
        problems.append(f"DBのjournal_modeが{journal_mode}（-wal未反映の変更がコミットされない恐れ）")
    last_run = report.get("last_run") or {}
    if last_run.get("started_at"):
        try:
            age = now - datetime.fromisoformat(last_run["started_at"])
            if age > timedelta(days=2):
                problems.append(f"最終実行が{age.days}日前（Actionsの停止を確認）")
        except ValueError:
            pass
        if last_run.get("exit_code"):
            problems.append(f"直近の実行が終了コード{last_run['exit_code']}で失敗")
    return report


def _print_text(report: dict) -> None:
    print(f"=== Journal Tracker 現状レポート ({report['generated_at']}) ===\n")
    problems = report["problems"]
    print(f"要確認: {len(problems)} 件")
    for p in problems:
        print(f"  - {p}")

    last_run = report.get("last_run")
    print("\n[直近の実行 (data/last_run.json)]")
    if last_run:
        keys = ("started_at", "duration_sec", "fetched_count", "inserted_count",
                "excluded_non_research_count", "failed_journals_count", "catchup_journals", "exit_code")
        for k in keys:
            if k in last_run:
                print(f"  {k}: {last_run[k]}")
    else:
        print("  （記録なし）")

    db = report.get("database")
    if db:
        print("\n[データベース]")
        for k, v in db.items():
            print(f"  {k}: {v}")

    rows = report.get("journals", [])
    flagged = [r for r in rows if r["flags"]]
    print(f"\n[フラグ付きの誌] {len(flagged)} / {len(rows)} 誌"
          f"（no_new_{STALE_DAYS}d は刊行頻度が低い誌では正常なこともある）")
    for r in flagged:
        print(f"  {r['name'][:55]:55} 30d={r['papers_30d']:3} total={r['papers_total']:4} "
              f"last={(r['last_fetched'] or '-')[:10]}  {','.join(r['flags'])}")
    if report.get("orphan_journals_in_db"):
        print(f"\n[リスト外の誌名でDBに残る論文] {', '.join(report['orphan_journals_in_db'])}")


def main() -> int:
    parser = argparse.ArgumentParser(description="運用状態の現状把握レポート（読み取り専用）")
    parser.add_argument("--config", "-c", default=None, help="設定ファイルパス")
    parser.add_argument("--json", action="store_true", help="JSONで出力")
    args = parser.parse_args()

    report = build_report(load_config(args.config))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
