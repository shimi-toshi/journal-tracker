"""Excel出力モジュール"""

import logging
import re
from pathlib import Path
from datetime import datetime
from html import unescape

import pandas as pd

from .parser import Paper

logger = logging.getLogger(__name__)


MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def normalize_date(date_str: str) -> str:
    """日付を YYYY/MM 形式に正規化"""
    if not date_str:
        return ""

    # 既に YYYY-MM-DD 形式の場合
    match = re.match(r'(\d{4})-(\d{2})-\d{2}', date_str)
    if match:
        return f"{match.group(1)}/{match.group(2)}"

    # YYYY-MM 形式の場合
    match = re.match(r'(\d{4})-(\d{2})', date_str)
    if match:
        return f"{match.group(1)}/{match.group(2)}"

    # "June 2026" 形式の場合
    match = re.match(r'([A-Za-z]+)\s*(\d{4})', date_str)
    if match:
        month_name = match.group(1).lower()
        year = match.group(2)
        month = MONTH_MAP.get(month_name, "01")
        return f"{year}/{month}"

    return date_str


def extract_metadata_from_abstract(abstract: str) -> dict:
    """Abstractからメタデータ（著者、発行日）を抽出"""
    result = {
        "authors": "",
        "published": "",
    }

    if not abstract:
        return result

    # HTMLエンティティをデコード
    text = unescape(abstract)
    # HTMLタグを除去
    text = re.sub(r'<[^>]+>', ' ', text)

    # Publication date を抽出 (例: "Publication date: June 2026")
    pub_match = re.search(r'Publication date:\s*([A-Za-z]+\s*\d{4})', text, re.IGNORECASE)
    if pub_match:
        result["published"] = normalize_date(pub_match.group(1).strip())

    # Author(s) を抽出 (例: "Author(s): Name1, Name2, Name3")
    author_match = re.search(r'Author\(s\):\s*([^<\n]+)', text, re.IGNORECASE)
    if author_match:
        authors = author_match.group(1).strip()
        result["authors"] = authors

    return result


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
                # Abstractからメタデータを抽出
                metadata = extract_metadata_from_abstract(paper.abstract)

                # 著者: paperにあればそれを使用、なければAbstractから抽出
                authors = ", ".join(paper.authors) if paper.authors else metadata["authors"]

                # 発行日: paperにあればそれを使用、なければAbstractから抽出
                if paper.published_date:
                    published = paper.published_date.strftime("%Y/%m")
                else:
                    published = metadata["published"]

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
