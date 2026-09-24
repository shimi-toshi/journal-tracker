"""Journal Tracker - メインエントリーポイント"""

import argparse
import json
import logging
import shutil
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
from .parser import is_excluded_title
from .utils import (
    ensure_data_dir,
    load_config,
    load_journals_from_excel,
    load_title_exclusions,
    resolve_path,
    validate_journal_excel,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# logs/ に残す実行レポートの件数（古いものから削除）
RUN_REPORT_KEEP = 30


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
        # 実DB（gitで管理）を書き換えないよう、一時コピーに対して初期化・移行を検証する
        with tempfile.TemporaryDirectory() as td:
            probe_path = Path(td) / "papers.db"
            if db_path.exists():
                shutil.copy2(db_path, probe_path)
            PaperStorage(probe_path)
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

    # ジャーナル設定の論理チェック（取得元の取り違え・取得手段なしを早期検知）
    if excel_path:
        try:
            journals = load_journals_from_excel(excel_path)
        except Exception:
            journals = []
        issn_owners: dict[str, list[str]] = {}
        for journal in journals:
            if not journal.issns:
                issues.append(f"取得手段がありません（ISSNがありません）: {journal.name}")
            # Online/Print 双方を取得に併用するため、両ISSNを取り違え検査の対象にする
            for issn in journal.issns:
                issn_owners.setdefault(issn, []).append(journal.name)
        for issn, names in issn_owners.items():
            unique_names = sorted(set(names))
            if len(unique_names) > 1:
                issues.append(
                    f"ISSN重複（取得元ジャーナルの取り違えの恐れ）: {issn} -> {', '.join(unique_names)}"
                )

    return issues


def _write_run_report(config: dict, report: dict, last_run_path: Path | None = None) -> Path:
    """実行サマリをJSONとして保存（logs/ には最新 RUN_REPORT_KEEP 件だけ残す）。

    last_run_path を指定すると同じ内容をそこにも書く。Actions はこれを data/last_run.json として
    DBと一緒にコミットし、新しくクローンしたエージェントでも直近の運用結果を確認できるようにする。
    """
    logs_dir = resolve_path(config.get("logs", {}).get("output_dir", "logs"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = logs_dir / f"run_report_{ts}.json"
    content = json.dumps(report, ensure_ascii=False, indent=2)
    report_path.write_text(content, encoding="utf-8")
    for old in sorted(logs_dir.glob("run_report_*.json"))[:-RUN_REPORT_KEEP]:
        old.unlink(missing_ok=True)
    if last_run_path is not None:
        last_run_path.write_text(content + "\n", encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="会計・ファイナンス ジャーナル新着論文トラッカー")
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

        # self-check は DB初期化の失敗も自身で報告するため、PaperStorage 生成より前に分岐する
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

        db_path = ensure_data_dir(config)

        if args.stats:
            storage = PaperStorage(db_path)
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
                source = "CrossRef" if j.issns else "取得不可"
                issns = ",".join(j.issns) or "-"
                print(f"  [{source:9}] {issns:19} {j.abbreviation:8} - {j.name}")
            return 0

        storage = PaperStorage(db_path)

        exit_code = 0
        title_exclusions = load_title_exclusions(config)

        # 最後の取得成功から days_back 以上空いた誌は、その期間まで遡って取得する（キャッチアップ）
        fetcher = PaperFetcher(config)
        fetched = list(fetcher.fetch_all(journals, last_success=storage.get_last_success_map()))
        # Editorial Board / Issue Information 等の論文以外の項目はDBにも保存しない
        papers = [p for p in fetched if not is_excluded_title(p.title, title_exclusions)]
        excluded_count = len(fetched) - len(papers)
        logger.info(f"Fetched {len(fetched)} papers ({excluded_count} non-research items excluded)")

        # dry-runではDBに保存しない（保存すると新着が消費され、次回本番実行の出力から漏れる）
        if args.dry_run:
            new_papers = [p for p in papers if storage.is_new(p)]
        else:
            new_papers = storage.save_batch(papers)
        logger.info(f"Found {len(new_papers)} new papers")

        # Excel出力の失敗でHTML更新・取得成否の記録まで止めない（終了コードで失敗を知らせる）
        if new_papers:
            exporter = ExcelExporter(config)
            output_path = exporter.export(new_papers, dry_run=args.dry_run)
            if output_path:
                if not args.dry_run:
                    storage.mark_notified(new_papers)
            else:
                logger.error("Failed to export to Excel")
                exit_code = 1
        else:
            print("新着論文はありませんでした。")

        # ジャーナル別の取得成否を記録（長期エラー検知用）。dry-runでは状態を汚さない。
        attempted_journals = [j.name for j in journals if j.issns]
        if not args.dry_run:
            storage.update_journal_status(attempted_journals, fetcher.last_run_stats.failed_journals)

        html_exporter = HtmlExporter(config)
        recent_papers = storage.get_recent_papers(
            days=html_exporter.max_days,
            max_publication_lag_days=html_exporter.max_publication_lag_days,
            exclude_title_patterns=title_exclusions,
        )
        # Excelリストから外した誌の journal_status は残るため、現在の対象誌に限定する
        current_names = {j.name for j in journals}
        failing_journals = {
            name: status
            for name, status in storage.get_failing_journals(threshold=html_exporter.failure_threshold).items()
            if name in current_names
        }
        if failing_journals:
            logger.warning(f"Long-term failing journals: {len(failing_journals)} -> {', '.join(failing_journals)}")
        html_path = html_exporter.export(
            recent_papers, dry_run=args.dry_run, journals=journals, failing_journals=failing_journals
        )
        if html_path is None:
            logger.error("Failed to export HTML")
            exit_code = 1

        duration_sec = round(time.perf_counter() - start_time, 3)
        report = {
            "started_at": run_started_at.isoformat(),
            "duration_sec": duration_sec,
            "journals_total": len(journals),
            "fetched_count": len(fetched),
            "excluded_non_research_count": excluded_count,
            "inserted_count": len(new_papers),
            "failed_journals": fetcher.last_run_stats.failed_journals,
            "failed_journals_count": len(fetcher.last_run_stats.failed_journals),
            "skipped_journals": fetcher.last_run_stats.skipped_journals,
            "skipped_journals_count": len(fetcher.last_run_stats.skipped_journals),
            "long_term_failing_journals": list(failing_journals),
            "long_term_failing_journals_count": len(failing_journals),
            "catchup_journals": fetcher.last_run_stats.catchup_journals,
            "dry_run": args.dry_run,
            "exit_code": exit_code,
        }
        last_run_path = None if args.dry_run else db_path.parent / "last_run.json"
        report_path = _write_run_report(config, report, last_run_path=last_run_path)
        logger.info(f"Run report saved: {report_path}")

        return exit_code

    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
