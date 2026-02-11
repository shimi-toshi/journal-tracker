"""HTML出力モジュール - GitHub Pages用"""

import logging
from pathlib import Path
from datetime import datetime
from itertools import groupby
from operator import attrgetter

from jinja2 import Environment, FileSystemLoader

from .parser import Journal, Paper
from .exporter import extract_metadata_from_abstract
from .utils import resolve_path

logger = logging.getLogger(__name__)


class HtmlExporter:
    """論文一覧をHTMLファイルに出力するクラス（GitHub Pages用）"""

    def __init__(self, config: dict):
        html_config = config.get("html_export", {})
        self.output_dir = resolve_path(html_config.get("output_dir", "docs"))
        self.template_dir = resolve_path(html_config.get("template_dir", "templates"))
        self.days_back = html_config.get("days_back", 7)
        # selectable_days_range（範囲指定）が優先、なければselectable_days（個別指定）
        days_range = html_config.get("selectable_days_range")
        if days_range and len(days_range) == 2:
            self.selectable_days = None
            self.selectable_days_range = (int(days_range[0]), int(days_range[1]))
        else:
            self.selectable_days = html_config.get("selectable_days", [7, 14, 30])
            self.selectable_days_range = None
        self.google_analytics_id = config.get("google_analytics")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def max_days(self) -> int:
        """データ取得に必要な最大日数を返す"""
        if self.selectable_days_range:
            return self.selectable_days_range[1]
        if self.selectable_days:
            return max(self.selectable_days)
        return self.days_back

    def export(self, papers: list[Paper], dry_run: bool = False, journals: list[Journal] | None = None) -> Path | None:
        """論文一覧をHTMLに出力"""
        output_path = self.output_dir / "index.html"

        if dry_run:
            logger.info(f"[DRY RUN] Would export {len(papers)} papers to {output_path}")
            print(f"\n--- HTML Export Preview ---")
            print(f"Output: {output_path}")
            print(f"Papers: {len(papers)}")
            print("--- End HTML Preview ---\n")
            return output_path

        try:
            env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=True,
            )
            template = env.get_template("index.html")

            # ジャーナル名→URLのマッピングを作成
            journal_url_map = {}
            if journals:
                for j in journals:
                    if j.journal_url:
                        journal_url_map[j.name] = j.journal_url

            grouped_papers = self._group_by_journal(papers, journal_url_map, all_journals=journals)
            generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

            journals_with_papers = sum(1 for g in grouped_papers if g["count"] > 0)
            html_content = template.render(
                grouped_papers=grouped_papers,
                total_count=len(papers),
                total_journals=len(grouped_papers),
                journals_with_papers=journals_with_papers,
                days_back=self.days_back,
                selectable_days=self.selectable_days,
                selectable_days_range=self.selectable_days_range,
                generated_at=generated_at,
                google_analytics_id=self.google_analytics_id,
            )

            output_path.write_text(html_content, encoding="utf-8")
            logger.info(f"Exported {len(papers)} papers to {output_path}")
            print(f"\n{len(papers)}件の論文をHTMLに出力しました: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to export to HTML: {e}")
            return None

    def _group_by_journal(self, papers: list[Paper], journal_url_map: dict | None = None,
                          all_journals: list[Journal] | None = None) -> list[dict]:
        """論文をジャーナル別にグルーピング（全ジャーナルを含む）"""
        sorted_papers = sorted(papers, key=attrgetter("journal_name"))
        journal_url_map = journal_url_map or {}

        # 論文があるジャーナルをグルーピング
        papers_by_journal: dict[str, list[dict]] = {}
        for journal_name, group in groupby(sorted_papers, key=attrgetter("journal_name")):
            paper_list = []
            for paper in group:
                metadata = extract_metadata_from_abstract(paper.abstract)
                authors = ", ".join(paper.authors) if paper.authors else metadata["authors"]
                if paper.published_date:
                    published = paper.published_date.strftime("%Y/%m/%d")
                else:
                    published = metadata["published"] or ""

                paper_list.append({
                    "title": paper.title,
                    "authors": authors,
                    "published": published,
                    "published_iso": paper.published_date.strftime("%Y-%m-%d") if paper.published_date else "",
                    "fetched_iso": paper.fetched_at.strftime("%Y-%m-%d") if paper.fetched_at else "",
                    "doi": paper.doi,
                    "url": paper.url,
                })
            papers_by_journal[journal_name] = paper_list

        # 全ジャーナルリストからグループを構築（論文がないジャーナルも含む）
        grouped = []
        seen_journals = set()
        if all_journals:
            for j in all_journals:
                seen_journals.add(j.name)
                paper_list = papers_by_journal.get(j.name, [])
                grouped.append({
                    "journal_name": j.name,
                    "journal_url": j.journal_url or "",
                    "count": len(paper_list),
                    "papers": paper_list,
                })

        # Excelリストにないジャーナル名で論文がある場合も追加
        for journal_name, paper_list in papers_by_journal.items():
            if journal_name not in seen_journals:
                grouped.append({
                    "journal_name": journal_name,
                    "journal_url": journal_url_map.get(journal_name, ""),
                    "count": len(paper_list),
                    "papers": paper_list,
                })

        return grouped
