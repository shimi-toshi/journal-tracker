"""Journal Tracker - メインエントリーポイント"""

import argparse
import json
import logging
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

from .exporter import ExcelExporter
from .fetcher import PaperFetcher
from .html_exporter import HtmlExporter
from .storage import PaperStorage
from .utils import ensure_data_dir, load_config, load_journals_from_excel, resolve_path, validate_journal_excel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)




def _check_directory_writable(path: Path, label: str) -> str | None:
    """ディレクトリ作成と書き込み可否を検証"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix=".write_check_", delete=True):
            pass
    except Exception as exc:
        return f"{label} の書き込み確認に失敗: {path} ({exc})"
    return None

def run_self_check(config: dict) -> list[str]:
    """設定・依存ファイルの自己診断を実施し、問題一覧を返す"""
    issues: list[str] = []

    excel_path = config.get("journals", {}).get("excel_path", "")
    if not excel_path:
        issues.append("journals.excel_path が設定されていません")
    else:
        try:
            validate_journal_excel(excel_path)
        except Exception as exc:
            issues.append(f"ジャーナルExcelの検証に失敗: {exc}")

    try:
        db_path = ensure_data_dir(config)
        PaperStorage(db_path)
    except Exception as exc:
        issues.append(f"DB初期化/移行に失敗: {exc}")

    export_dir = resolve_path(config.get("export", {}).get("output_dir", "output"))
    export_issue = _check_directory_writable(export_dir, "Excel出力ディレクトリ")
    if export_issue:
        issues.append(export_issue)

    logs_dir = resolve_path(config.get("logs", {}).get("output_dir", "logs"))
    logs_issue = _check_directory_writable(logs_dir, "ログ出力ディレクトリ")
    if logs_issue:
        issues.append(logs_issue)

    try:
        html_config = config.get("html_export", {})
        template_dir = resolve_path(html_config.get("template_dir", "templates"))
        template_file = Path(template_dir) / "index.html"
        if not template_file.exists():
            issues.append(f"HTMLテンプレートが見つかりません: {template_file}")
        else:
            Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True).get_template("index.html")

        html_output_dir = resolve_path(html_config.get("output_dir", "docs"))
        html_output_issue = _check_directory_writable(html_output_dir, "HTML出力ディレクトリ")
        if html_output_issue:
            issues.append(html_output_issue)
    except Exception as exc:
        issues.append(f"HTMLテンプレート検証に失敗: {exc}")

    return issues


def _write_run_report(config: dict, report: dict) -> Path:
    """実行サマリをJSONとして保存"""
    logs_dir = resolve_path(config.get("logs", {}).get("output_dir", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = logs_dir / f"run_report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="会計学ジャーナル新着論文トラッカー")
    parser.add_argument("--config", "-c", help="設定ファイルパス", default=None)
    parser.add_argument("--dry-run", "-n", action="store_true", help="Excel出力せずテスト実行")
    parser.add_argument("--stats", action="store_true", help="統計情報を表示")
    parser.add_argument("--list-journals", action="store_true", help="ジャーナル一覧を表示")
    parser.add_argument("--self-check", action="store_true", help="設定・DB・入力ファイルの自己診断を実施")

    args = parser.parse_args()

    try:
        run_started_at = datetime.now()
        start_time = time.perf_counter()

        config = load_config(args.config)
        logger.info("Config loaded")

        db_path = ensure_data_dir(config)
        storage = PaperStorage(db_path)

        if args.self_check:
            issues = run_self_check(config)
            if issues:
                print("\n=== Self Check: NG ===")
                for issue in issues:
                    print(f"- {issue}")
                return 1

            print("\n=== Self Check: OK ===")
            print("設定・Excel列構造・DB初期化・テンプレート確認を通過しました。")
            return 0

        if args.stats:
            stats = storage.get_stats()
            print(f"\n=== 論文統計 ===")
            print(f"総論文数: {stats['total']}")
            print(f"通知済み: {stats['notified']}")
            print(f"未通知: {stats['unnotified']}")
            print(f"\nジャーナル別:")
            for journal, count in sorted(stats["by_journal"].items()):
                print(f"  {journal}: {count}")
            return 0

        excel_path = config.get("journals", {}).get("excel_path", "")
        if not excel_path:
            logger.error("journals.excel_path not configured in config.yaml")
            return 1

        journals = load_journals_from_excel(excel_path)
        logger.info(f"Loaded {len(journals)} journals")

        if args.list_journals:
            print(f"\n=== ジャーナル一覧 ({len(journals)}件) ===")
            for j in journals:
                rss_status = "RSS" if j.has_rss else "CrossRef/Other"
                print(f"  [{rss_status:12}] {j.abbreviation:8} - {j.name}")
            return 0

        fetcher = PaperFetcher(config)
        papers = list(fetcher.fetch_all(journals))
        logger.info(f"Fetched {len(papers)} papers")

        new_papers = storage.save_batch(papers)
        logger.info(f"Found {len(new_papers)} new papers")

        if new_papers:
            exporter = ExcelExporter(config)
            output_path = exporter.export(new_papers, dry_run=args.dry_run)
            if output_path:
                if not args.dry_run:
                    storage.mark_notified(new_papers)
            else:
                logger.error("Failed to export to Excel")
                return 1
        else:
            print("新着論文はありませんでした。")

        html_exporter = HtmlExporter(config)
        recent_papers = storage.get_recent_papers(days=html_exporter.max_days)
        html_exporter.export(recent_papers, dry_run=args.dry_run, journals=journals)

        duration_sec = round(time.perf_counter() - start_time, 3)
        report = {
            "started_at": run_started_at.isoformat(),
            "duration_sec": duration_sec,
            "journals_total": len(journals),
            "fetched_count": len(papers),
            "inserted_count": len(new_papers),
            "failed_journals": fetcher.last_run_stats.failed_journals,
            "failed_journals_count": len(fetcher.last_run_stats.failed_journals),
            "skipped_journals": fetcher.last_run_stats.skipped_journals,
            "skipped_journals_count": len(fetcher.last_run_stats.skipped_journals),
            "crossref_retry_total": fetcher.crossref_fetcher.session.get_adapter("https://api.crossref.org").max_retries.total,
            "dry_run": args.dry_run,
        }
        report_path = _write_run_report(config, report)
        logger.info(f"Run report saved: {report_path}")

        return 0

    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
