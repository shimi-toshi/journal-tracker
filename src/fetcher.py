"""論文取得モジュール - RSS/CrossRef API対応"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Iterator
import time

import feedparser
import requests

from .parser import Paper, Journal

logger = logging.getLogger(__name__)

# HTMLタグ除去用の正規表現（コンパイル済み）
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


class RSSFetcher:
    """RSSフィードから論文を取得"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def fetch(self, journal: Journal, days_back: int = 7) -> Iterator[Paper]:
        """RSSフィードから論文を取得"""
        if not journal.has_rss:
            logger.warning(f"No RSS feed for {journal.name}")
            return

        try:
            feed = feedparser.parse(journal.rss_url)
            if feed.bozo:
                logger.warning(f"RSS parse error for {journal.name}: {feed.bozo_exception}")

            cutoff_date = datetime.now() - timedelta(days=days_back)

            for entry in feed.entries:
                paper = self._parse_entry(entry, journal)
                if paper:
                    if paper.published_date and paper.published_date < cutoff_date:
                        continue
                    yield paper

        except Exception as e:
            logger.error(f"Failed to fetch RSS for {journal.name}: {e}")

    def _parse_entry(self, entry: dict, journal: Journal) -> Paper | None:
        """RSSエントリーをPaperオブジェクトに変換"""
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None

            # 著者の解析
            authors = []
            if "authors" in entry:
                authors = [a.get("name", "") for a in entry.authors if a.get("name")]
            elif "author" in entry:
                authors = [entry.author]

            # DOIの抽出
            doi = ""
            link = entry.get("link", "")
            if "doi.org/" in link:
                doi = link.split("doi.org/")[-1]
            elif "prism_doi" in entry:
                doi = entry.prism_doi

            # 公開日の解析
            published_date = None
            if "published_parsed" in entry and entry.published_parsed:
                published_date = datetime(*entry.published_parsed[:6])
            elif "updated_parsed" in entry and entry.updated_parsed:
                published_date = datetime(*entry.updated_parsed[:6])

            return Paper(
                title=title,
                journal_name=journal.name,
                authors=authors,
                abstract=entry.get("summary", ""),
                doi=doi,
                url=link,
                published_date=published_date,
            )
        except Exception as e:
            logger.error(f"Failed to parse entry: {e}")
            return None


class CrossRefFetcher:
    """CrossRef APIから論文を取得（RSSがないジャーナル用）"""

    BASE_URL = "https://api.crossref.org/journals/{issn}/works"

    def __init__(self, timeout: int = 30, email: str = ""):
        self.timeout = timeout
        self.email = email
        self.headers = {"User-Agent": f"JournalTracker/1.0 (mailto:{email})" if email else "JournalTracker/1.0"}

    def fetch(self, journal: Journal, days_back: int = 7) -> Iterator[Paper]:
        """CrossRef APIから論文を取得"""
        if not journal.issn:
            logger.warning(f"No ISSN for {journal.name}")
            return

        try:
            from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

            params = {
                "filter": f"from-pub-date:{from_date}",
                "rows": 100,
                "sort": "published",
                "order": "desc",
            }

            url = self.BASE_URL.format(issn=journal.issn)
            response = requests.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            items = data.get("message", {}).get("items", [])

            for item in items:
                paper = self._parse_item(item, journal)
                if paper:
                    yield paper

        except Exception as e:
            logger.error(f"Failed to fetch from CrossRef for {journal.name}: {e}")

    def _parse_item(self, item: dict, journal: Journal) -> Paper | None:
        """CrossRef APIレスポンスをPaperオブジェクトに変換"""
        try:
            title_list = item.get("title", [])
            title = title_list[0] if title_list else ""
            if not title:
                return None

            authors = []
            for author in item.get("author", []):
                name_parts = []
                if author.get("given"):
                    name_parts.append(author["given"])
                if author.get("family"):
                    name_parts.append(author["family"])
                if name_parts:
                    authors.append(" ".join(name_parts))

            doi = item.get("DOI", "")
            url = f"https://doi.org/{doi}" if doi else ""

            published_date = None
            date_parts = item.get("published", {}).get("date-parts", [[]])
            if date_parts and date_parts[0]:
                parts = date_parts[0]
                year = parts[0] if len(parts) > 0 else 2000
                month = parts[1] if len(parts) > 1 else 1
                day = parts[2] if len(parts) > 2 else 1
                published_date = datetime(year, month, day)

            abstract = item.get("abstract", "")
            if abstract.startswith("<jats:"):
                abstract = HTML_TAG_PATTERN.sub("", abstract)

            return Paper(
                title=title,
                journal_name=journal.name,
                authors=authors,
                abstract=abstract,
                doi=doi,
                url=url,
                published_date=published_date,
            )
        except Exception as e:
            logger.error(f"Failed to parse CrossRef item: {e}")
            return None


class PaperFetcher:
    """論文取得の統合クラス"""

    def __init__(self, config: dict):
        fetch_config = config.get("fetch", {})
        self.timeout = fetch_config.get("timeout", 30)
        self.days_back = fetch_config.get("days_back", 7)

        email = os.environ.get("CROSSREF_EMAIL", config.get("email", {}).get("sender_email", ""))
        self.rss_fetcher = RSSFetcher(timeout=self.timeout)
        self.crossref_fetcher = CrossRefFetcher(timeout=self.timeout, email=email)

    def fetch_all(self, journals: list[Journal]) -> Iterator[Paper]:
        """全ジャーナルから論文を取得"""
        for journal in journals:
            logger.info(f"Fetching papers from {journal.name}...")

            if journal.has_rss:
                yield from self.rss_fetcher.fetch(journal, self.days_back)
            elif journal.issn:
                yield from self.crossref_fetcher.fetch(journal, self.days_back)
            else:
                logger.warning(f"No fetch method available for {journal.name}")

            time.sleep(1)  # Rate limiting
