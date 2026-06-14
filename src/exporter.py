"""Excel出力モジュール"""

import logging
from pathlib import Path
from datetime import datetime

import pandas as pd

from .parser import Paper

logger = logging.getLogger(__name__)


class ExcelExporter:
    """新着論文をExcelファイルに出力するクラス"""

    def __init__(self, config: dict):
        export_config = config.get("export", {})
        self.output_dir = Path(export_config.get("output_dir", "output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export(self, papers: list[Paper], dry_run: bool = False) -> Path | None:
        """新着論文をExcelファイルに出力"""
        if not papers:
            logger.info("No papers to export")
            return None

        # 日付入りファイル名
        today = datetime.now().strftime("%Y%m%d")
        filename = f"new_papers_{today}.xlsx"
        output_path = self.output_dir / filename

        if dry_run:
            logger.info(f"[DRY RUN] Would export {len(papers)} papers to {output_path}")
            print(f"\n--- Export Preview ---")
            print(f"Output: {output_path}")
            print(f"Papers: {len(papers)}")
            for paper in papers[:5]:
                # Windows console encoding issues対策
                title = paper.title[:60].encode('ascii', 'replace').decode('ascii')
                journal = paper.journal_name.encode('ascii', 'replace').decode('ascii')
                print(f"  - {title}... ({journal})")
            if len(papers) > 5:
                print(f"  ... and {len(papers) - 5} more")
            print("--- End Preview ---\n")
            return output_path

        try:
            # DataFrameに変換
            data = []
            for paper in papers:
                authors = ", ".join(paper.authors)
                published = paper.published_date.strftime("%Y/%m") if paper.published_date else ""

                data.append({
                    "Journal": paper.journal_name,
                    "Published": published,
                    "Title": paper.title,
                    "Authors": authors,
                    "DOI": paper.doi,
                    "URL": paper.url,
                })

            df = pd.DataFrame(data)

            # ジャーナル名でソート
            df = df.sort_values(["Journal", "Title"])

            # Excelに出力
            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="New Papers")

                # 列幅の調整
                worksheet = writer.sheets["New Papers"]
                worksheet.column_dimensions["A"].width = 30  # Journal
                worksheet.column_dimensions["B"].width = 10  # Published
                worksheet.column_dimensions["C"].width = 80  # Title
                worksheet.column_dimensions["D"].width = 50  # Authors
                worksheet.column_dimensions["E"].width = 25  # DOI
                worksheet.column_dimensions["F"].width = 50  # URL

            logger.info(f"Exported {len(papers)} papers to {output_path}")
            print(f"\n{len(papers)}件の新着論文を出力しました: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to export to Excel: {e}")
            return None
