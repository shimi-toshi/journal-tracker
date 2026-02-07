"""Journal Tracker - メインエントリーポイント"""

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from .utils import load_config, load_journals_from_excel, ensure_data_dir
from .fetcher import PaperFetcher
from .storage import PaperStorage
from .exporter import ExcelExporter
from .html_exporter import HtmlExporter

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="会計学ジャーナル新着論文トラッカー")
    parser.add_argument("--config", "-c", help="設定ファイルパス", default=None)
    parser.add_argument("--dry-run", "-n", action="store_true", help="Excel出力せずテスト実行")
    parser.add_argument("--stats", action="store_true", help="統計情報を表示")
    parser.add_argument("--list-journals", action="store_true", help="ジャーナル一覧を表示")

    args = parser.parse_args()

    try:
        # 設定読み込み
        config = load_config(args.config)
        logger.info("Config loaded")

        # データベースパス
        db_path = ensure_data_dir(config)
        storage = PaperStorage(db_path)

        # 統計表示モード
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

        # ジャーナルリスト読み込み
        excel_path = config.get("journals", {}).get("excel_path", "")
        if not excel_path:
            logger.error("journals.excel_path not configured in config.yaml")
            return 1

        journals = load_journals_from_excel(excel_path)
        logger.info(f"Loaded {len(journals)} journals")

        # ジャーナル一覧表示モード
        if args.list_journals:
            print(f"\n=== ジャーナル一覧 ({len(journals)}件) ===")
            for j in journals:
                rss_status = "RSS" if j.has_rss else "CrossRef/Other"
                print(f"  [{rss_status:12}] {j.abbreviation:8} - {j.name}")
            return 0

        # 論文取得
        fetcher = PaperFetcher(config)
        papers = list(fetcher.fetch_all(journals))
        logger.info(f"Fetched {len(papers)} papers")

        # 新着論文の保存
        new_papers = storage.save_batch(papers)
        logger.info(f"Found {len(new_papers)} new papers")

        if new_papers:
            # Excel出力
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

        # HTML出力（GitHub Pages用 - 直近N日分の累積データ）
        html_exporter = HtmlExporter(config)
        recent_papers = storage.get_recent_papers(days=html_exporter.max_days)
        html_exporter.export(recent_papers, dry_run=args.dry_run, journals=journals)

        return 0

    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
