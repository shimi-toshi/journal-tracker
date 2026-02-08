"""論文データ解析モジュール"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import hashlib


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
        """論文の一意識別子を生成（DOIがあればDOI、なければタイトルのハッシュ）"""
        if self.doi:
            return self.doi
        return hashlib.md5(f"{self.title}:{self.journal_name}".encode()).hexdigest()

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
    rss_url: str = ""
    issn: str = ""
    status: str = ""  # Working / No RSS

    @property
    def has_rss(self) -> bool:
        """RSSフィードが利用可能か"""
        return self.rss_url and self.rss_url != "-" and self.status == "Working"
