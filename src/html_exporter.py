"""HTML出力モジュール - GitHub Pages用

人間向けの index.html に加え、生成AI・スクリプトが効率よく読めるよう
latest.md（直近 days_back 日のMarkdown）・papers.json（全表示期間のJSON）・llms.txt（案内）も出力する。
"""

import json
import logging
from datetime import datetime, timedelta
from itertools import groupby
from operator import attrgetter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .parser import Journal, Paper, clean_abstract, clean_markup
from .utils import resolve_path

logger = logging.getLogger(__name__)

SITE_TITLE = "Accounting & Finance Journal Tracker"
SITE_DESCRIPTION = "会計・ファイナンス主要ジャーナルの新着論文一覧（CrossRefから毎日自動取得）"


def _tz_label(dt: datetime) -> str:
    """表示用のタイムゾーン名（Actionsでは TZ=Asia/Tokyo により "JST"）"""
    return dt.astimezone().tzname() or ""


class HtmlExporter:
    """論文一覧をHTML等に出力するクラス（GitHub Pages用）"""

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
        # バックカタログ再登録ガード（公表が取得よりこの日数より前なら新着扱いしない）
        self.max_publication_lag_days = html_config.get("max_publication_lag_days", 60)
        # 連続失敗がこの回数以上で「長期エラー」と表示する
        self.failure_threshold = html_config.get("failure_threshold", 7)
        # llms.txt 等に載せる公開URL（末尾スラッシュ付き）。未設定なら相対リンク
        site_url = html_config.get("site_url", "") or ""
        self.site_url = site_url if not site_url or site_url.endswith("/") else site_url + "/"
        self.google_analytics_id = config.get("google_analytics")

    @property
    def max_days(self) -> int:
        """データ取得に必要な最大日数を返す"""
        if self.selectable_days_range:
            return self.selectable_days_range[1]
        if self.selectable_days:
            return max(self.selectable_days)
        return self.days_back

    def export(self, papers: list[Paper], dry_run: bool = False, journals: list[Journal] | None = None,
               failing_journals: dict[str, dict] | None = None,
               generated_at: datetime | None = None) -> Path | None:
        """論文一覧を index.html / latest.md / papers.json / llms.txt に出力"""
        output_path = self.output_dir / "index.html"

        if dry_run:
            logger.info(f"[DRY RUN] Would export {len(papers)} papers to {output_path}")
            print(f"\n--- HTML Export Preview ---")
            print(f"Output: {output_path} (+ latest.md, papers.json, llms.txt)")
            print(f"Papers: {len(papers)}")
            print(f"Long-term failing journals: {len(failing_journals or {})}")
            print("--- End HTML Preview ---\n")
            return output_path

        try:
            env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                autoescape=True,
            )
            template = env.get_template("index.html")

            generated_at = generated_at or datetime.now()
            grouped_papers = self._group_by_journal(papers, all_journals=journals, failing_journals=failing_journals)
            visible_count = sum(g["count"] for g in grouped_papers)
            journals_with_papers = sum(1 for g in grouped_papers if g["count"] > 0)
            failing_count = sum(1 for g in grouped_papers if g["is_failing"])
            html_content = template.render(
                site_title=SITE_TITLE,
                site_description=SITE_DESCRIPTION,
                grouped_papers=grouped_papers,
                total_count=visible_count,
                total_journals=len(grouped_papers),
                journals_with_papers=journals_with_papers,
                failing_count=failing_count,
                days_back=self.days_back,
                max_days=self.max_days,
                selectable_days=self.selectable_days,
                selectable_days_range=self.selectable_days_range,
                generated_at=f"{generated_at.strftime('%Y-%m-%d %H:%M')} {_tz_label(generated_at)}".strip(),
                generated_date=generated_at.strftime("%Y-%m-%d"),
                google_analytics_id=self.google_analytics_id,
            )

            self.output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(html_content, encoding="utf-8")
            (self.output_dir / "latest.md").write_text(
                self._render_markdown(grouped_papers, generated_at), encoding="utf-8"
            )
            (self.output_dir / "papers.json").write_text(
                json.dumps(self._build_json(grouped_papers, generated_at), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            (self.output_dir / "llms.txt").write_text(self._render_llms_txt(generated_at), encoding="utf-8")
            logger.info(f"Exported {visible_count} papers to {output_path} (+ latest.md, papers.json, llms.txt)")
            print(f"\n{visible_count}件の論文をHTMLに出力しました: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Failed to export to HTML: {e}")
            return None

    def _group_by_journal(self, papers: list[Paper],
                          all_journals: list[Journal] | None = None,
                          failing_journals: dict[str, dict] | None = None) -> list[dict]:
        """論文をジャーナル別にグルーピング（全ジャーナルを含む）"""
        sorted_papers = sorted(papers, key=attrgetter("journal_name"))
        failing_journals = failing_journals or {}

        # 論文があるジャーナルをグルーピング
        papers_by_journal: dict[str, list[dict]] = {}
        for journal_name, group in groupby(sorted_papers, key=attrgetter("journal_name")):
            papers_by_journal[journal_name] = [self._paper_dict(paper) for paper in group]

        # 全ジャーナルリストからグループを構築（論文がないジャーナルも含む）
        grouped = []
        seen_journals = set()
        for j in all_journals or []:
            seen_journals.add(j.name)
            grouped.append(self._build_group(
                j.name, papers_by_journal.get(j.name, []), failing_journals, journal=j
            ))

        # Excelリストにないジャーナル名で論文がある場合も追加（誌名変更前の論文など）
        for journal_name, paper_list in papers_by_journal.items():
            if journal_name not in seen_journals:
                grouped.append(self._build_group(journal_name, paper_list, failing_journals))

        return grouped

    @staticmethod
    def _paper_dict(paper: Paper) -> dict:
        """テンプレート・機械可読出力用の論文辞書（DB既存行もここでマークアップを除去する）"""
        return {
            "title": clean_markup(paper.title),
            "authors": ", ".join(paper.authors),
            "authors_list": list(paper.authors),
            "abstract": clean_abstract(paper.abstract),
            "published": paper.published_date.strftime("%Y/%m/%d") if paper.published_date else "",
            "published_iso": paper.published_date.strftime("%Y-%m-%d") if paper.published_date else "",
            "fetched_iso": paper.fetched_at.strftime("%Y-%m-%d") if paper.fetched_at else "",
            "doi": paper.doi,
            "url": paper.url,
        }

    # error_type を利用者向けの説明に変換
    _ERROR_DESCRIPTIONS = {
        "http_auth_error": "アクセスが拒否されています",
        "http_client_error": "提供元からエラー応答",
        "http_server_error": "提供元サーバーのエラー",
        "http_error": "提供元からエラー応答",
        "timeout_error": "応答がタイムアウト",
        "dns_error": "提供元に接続できません",
        "connection_refused": "提供元に接続できません",
        "connection_error": "提供元に接続できません",
        "tls_error": "通信(TLS)エラー",
        "proxy_error": "通信エラー",
        "crossref_unknown_error": "取得処理でエラー",
    }

    def _build_group(self, name: str, paper_list: list[dict], failing_journals: dict[str, dict],
                     journal: Journal | None = None) -> dict:
        """テンプレート用のジャーナルグループ辞書を構築（長期エラー判定を含む）"""
        status = failing_journals.get(name)
        is_failing = status is not None
        error_reason = ""
        if is_failing:
            error_reason = self._ERROR_DESCRIPTIONS.get(status.get("error_type", ""), "取得エラー")
        return {
            "journal_name": name,
            "journal_url": journal.journal_url if journal else "",
            "abbreviation": journal.abbreviation if journal else "",
            "abdc": journal.abdc if journal else "",
            "abs_rank": journal.abs_rank if journal else "",
            # 長期エラー誌は論文欄を出さず、名称＋HP＋注意書きのみ表示する
            "count": 0 if is_failing else len(paper_list),
            "papers": [] if is_failing else paper_list,
            "is_failing": is_failing,
            "error_reason": error_reason,
        }

    # ---- 生成AI・スクリプト向けの出力 -------------------------------------------------

    def _cutoff_date(self, generated_at: datetime, days: int) -> str:
        """「直近N日」の起点日（生成日を含めてN日分）。index.html の JS と同じ定義"""
        return (generated_at - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    @staticmethod
    def _md_escape(text: str) -> str:
        """Markdownのリンク・強調として誤解釈される最小限の文字だけエスケープ"""
        for ch in ("\\", "[", "]", "*", "_", "`"):
            text = text.replace(ch, "\\" + ch)
        return text

    def _render_markdown(self, grouped: list[dict], generated_at: datetime) -> str:
        """直近 days_back 日（fetched_at基準）の新着をMarkdownで出力（アブストラクトなし・軽量）"""
        cutoff = self._cutoff_date(generated_at, self.days_back)
        sections: list[str] = []
        total = 0
        for g in grouped:
            if g["is_failing"]:
                continue
            recent = [p for p in g["papers"] if p["fetched_iso"] and p["fetched_iso"] >= cutoff]
            if not recent:
                continue
            total += len(recent)
            rank = " / ".join(x for x in (
                f"ABDC {g['abdc']}" if g["abdc"] else "", f"ABS {g['abs_rank']}" if g["abs_rank"] else ""
            ) if x)
            heading = f"## {g['journal_name']}" + (f" ({rank})" if rank else "")
            lines = [heading, ""]
            for p in recent:
                line = f"- {self._md_escape(p['title'])}"
                if p["authors"]:
                    line += f" — {self._md_escape(p['authors'])}"
                if p["published"]:
                    line += f" ({p['published']})"
                if p["doi"]:
                    line += f" https://doi.org/{p['doi']}"
                elif p["url"]:
                    line += f" {p['url']}"
                lines.append(line)
            sections.append("\n".join(lines))

        failing = [g["journal_name"] for g in grouped if g["is_failing"]]
        header = [
            f"# {SITE_TITLE} — 直近{self.days_back}日の新着論文",
            "",
            f"- 生成日時: {generated_at.strftime('%Y-%m-%d %H:%M')} ({_tz_label(generated_at)})",
            f"- 対象: {cutoff} 以降に本サイトが新規取得した論文（CrossRef初回登録ベース） {total}件 / 全{len(grouped)}誌",
            f"- 形式: 誌ごとに「タイトル — 著者 (公表日) DOI」。公表日が月のみの論文は日=01で表示",
            f"- アブストラクト・ランク・直近{self.max_days}日分は {self._link('papers.json')} を参照",
        ]
        if failing:
            header.append(f"- 長期取得エラー中（新着が載らない誌）: {', '.join(failing)}")
        body = "\n\n".join(sections) if sections else "（該当期間の新着論文はありません）"
        return "\n".join(header) + "\n\n" + body + "\n"

    def _build_json(self, grouped: list[dict], generated_at: datetime) -> dict:
        """表示期間（max_days）の全データをJSONで出力（HTMLと同じ除外を通したもの）"""
        journals = []
        papers = []
        for g in grouped:
            journals.append({
                "name": g["journal_name"],
                "abbrev": g["abbreviation"],
                "abdc": g["abdc"],
                "abs": g["abs_rank"],
                "url": g["journal_url"],
                "status": "failing" if g["is_failing"] else "ok",
                "error": g["error_reason"] or None,
            })
            for p in g["papers"]:
                papers.append({
                    "journal": g["journal_name"],
                    "title": p["title"],
                    "authors": p["authors_list"],
                    "published": p["published_iso"] or None,
                    "fetched": p["fetched_iso"] or None,
                    "doi": p["doi"] or None,
                    "url": p["url"] or None,
                    "abstract": p["abstract"] or None,
                })
        return {
            "title": SITE_TITLE,
            "generated_at": generated_at.astimezone().isoformat(timespec="seconds"),
            "window_days": self.max_days,
            "window_basis": "fetched (date this site first saw the paper; CrossRef created-date based)",
            "notes": [
                "published is YYYY-MM-DD; month-only dates from CrossRef are shown with day 01",
                "journals with status=failing have no papers listed (long-term fetch errors)",
            ],
            "journals": journals,
            "papers": papers,
        }

    def _link(self, filename: str) -> str:
        return f"{self.site_url}{filename}" if self.site_url else filename

    def _render_llms_txt(self, generated_at: datetime) -> str:
        """llms.txt（生成AI向けのサイト案内）"""
        return "\n".join([
            f"# {SITE_TITLE}",
            "",
            f"> {SITE_DESCRIPTION}。対象は会計・ファイナンスの主要誌（ABDC/ABS評価付き）で、"
            "毎日18時(JST)頃に更新される。",
            "",
            f"最終更新: {generated_at.strftime('%Y-%m-%d %H:%M')} ({_tz_label(generated_at)})。"
            "「新着」は本サイトが論文を初めて取得した日（CrossRefへの初回登録日ベース）を基準とし、"
            "公表日が古い再登録論文や Editorial Board 等の論文以外の項目は除外している。",
            "",
            "## Data",
            "",
            f"- [latest.md]({self._link('latest.md')}): 直近{self.days_back}日の新着を誌ごとに列挙したMarkdown"
            "（タイトル・著者・公表日・DOI）。まずこれを読むのが最も効率的",
            f"- [papers.json]({self._link('papers.json')}): 直近{self.max_days}日分の全データ"
            "（アブストラクト・ABDC/ABS・取得日付き）。絞り込みや集計に",
            f"- [index.html]({self._link('')}): 人間向けの閲覧ページ（日数スライダー・検索はJavaScript）",
            "",
        ])
