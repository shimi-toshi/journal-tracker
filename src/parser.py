"""論文データ解析モジュール"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Optional
import hashlib
import html
import re
from urllib.parse import urlsplit, urlunsplit


DOI_PREFIX_PATTERN = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)
# 段落・見出し等のブロック要素は語が連結しないよう空白に、インライン要素（<i>, <scp> 等）は削除する
BLOCK_TAG_PATTERN = re.compile(r"</?(?:jats:)?(?:p|title|sec|br|div|list|list-item)\b[^>]*>", re.IGNORECASE)
MARKUP_TAG_PATTERN = re.compile(r"<[^>]+>")
# 旧RSS由来の脚注リンク（<a ...><sup>1</sup></a>）は中身ごと除去する
FOOTNOTE_LINK_PATTERN = re.compile(r"<a\b[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL)
ABSTRACT_HEADING_PATTERN = re.compile(r"^(?:abstract|summary)\s*[:.]?\s+", re.IGNORECASE)


def clean_markup(text: str) -> str:
    """CrossRef由来のマークアップ（JATS/HTML/MathMLタグ・実体参照）を除去し空白を正規化する。

    タイトルには `<scp>`, `<i>`, `<sup>` 等が混入し、そのままだとHTML上で
    エスケープされたタグ文字列として表示されるため、取得時と表示時の両方で適用する。
    """
    if not text:
        return ""
    without_links = FOOTNOTE_LINK_PATTERN.sub("", text)
    without_tags = MARKUP_TAG_PATTERN.sub("", BLOCK_TAG_PATTERN.sub(" ", without_links))
    return " ".join(html.unescape(without_tags).split())


def clean_abstract(text: str) -> str:
    """アブストラクトを整形（マークアップ除去＋先頭の "Abstract" 見出し除去）"""
    return ABSTRACT_HEADING_PATTERN.sub("", clean_markup(text))


def compile_title_patterns(patterns: Iterable[str] | None) -> list[re.Pattern]:
    """除外タイトルの正規表現（大文字小文字無視）をコンパイル"""
    return [re.compile(p, re.IGNORECASE) for p in (patterns or []) if p]


def is_excluded_title(title: str, patterns: list[re.Pattern]) -> bool:
    """論文以外の項目（Editorial Board, Issue Information 等）かを判定（先頭一致）"""
    cleaned = clean_markup(title)
    return any(p.match(cleaned) for p in patterns)


def normalize_doi(doi: str) -> str:
    """DOIを正規化（プレフィックス除去・trim・小文字化）"""
    if not doi:
        return ""
    return DOI_PREFIX_PATTERN.sub("", doi.strip()).lower()


def normalize_url(url: str) -> str:
    """URLを正規化（trim・フラグメント除去・スキーム/ホスト小文字化）"""
    if not url:
        return ""

    stripped = url.strip()
    parts = urlsplit(stripped)
    if not parts.scheme or not parts.netloc:
        return stripped

    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


@dataclass
class Paper:
    """論文データを表すクラス"""
    title: str
    journal_name: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    doi: str = ""
    url: str = ""
    published_date: Optional[datetime] = None
    fetched_at: Optional[datetime] = None

    @property
    def unique_id(self) -> str:
        """論文の一意識別子を生成（DOI→URL→タイトル+ジャーナルの順で採用）"""
        normalized_doi = normalize_doi(self.doi)
        if normalized_doi:
            return normalized_doi

        normalized_url = normalize_url(self.url)
        if normalized_url:
            return hashlib.md5(normalized_url.encode()).hexdigest()

        normalized_title = " ".join(self.title.split()).lower()
        normalized_journal = " ".join(self.journal_name.split()).lower()
        return hashlib.md5(f"{normalized_title}:{normalized_journal}".encode()).hexdigest()

    def to_dict(self) -> dict:
        """辞書形式に変換"""
        return {
            "title": self.title,
            "journal_name": self.journal_name,
            "authors": self.authors,
            "abstract": self.abstract,
            "doi": self.doi,
            "url": self.url,
            "published_date": self.published_date.isoformat() if self.published_date else None,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "unique_id": self.unique_id,
        }


@dataclass
class Journal:
    """ジャーナル情報を表すクラス"""
    name: str
    abbreviation: str = ""
    publisher: str = ""
    journal_url: str = ""
    rss_url: str = ""   # 現在は未使用（Excel列との互換のため保持）
    issn: str = ""          # 主ISSN（Online優先、無ければPrint）
    issn_print: str = ""    # Print ISSN（取得時にissnとORで併用。issnと同一/空なら無視）
    status: str = ""    # 現在は未使用（Excel列との互換のため保持）
    abdc: str = ""      # ABDC評価（任意列。HTMLのバッジ表示用）
    abs_rank: str = ""  # ABS(AJG)評価（任意列。HTMLのバッジ表示用）

    @property
    def issns(self) -> list[str]:
        """取得クエリに使う全ISSN（主→Printの順、空白・重複を除去）。

        CrossRefは works の `issn:` フィルタを同名指定でORするため、Online/Print 両方を
        渡すことで「片方のISSNにしか works が無い」publisher（Elsevier等、works が
        Print ISSN にのみ紐づく）でも取りこぼさない。Online ISSNを優先採用していた旧実装では
        これらの誌が CrossRef で恒久的に0件になっていた。
        """
        result: list[str] = []
        for value in (self.issn, self.issn_print):
            value = (value or "").strip()
            if value and value not in result:
                result.append(value)
        return result
