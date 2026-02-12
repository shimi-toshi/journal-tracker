"""論文取得モジュール - RSS/CrossRef API対応"""

import logging
import os
import re
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterator

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .parser import Journal, Paper

logger = logging.getLogger(__name__)

# HTMLタグ除去用の正規表現（コンパイル済み）
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass
class FetchRunStats:
    """実行時の取得統計"""

    fetched_count: int = 0
    failed_journals: list[dict[str, str]] = field(default_factory=list)
    skipped_journals: list[str] = field(default_factory=list)


class RSSFetcher:
    """RSSフィードから論文を取得"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.last_error: str | None = None
        self.last_error_type: str | None = None

    def fetch(self, journal: Journal, days_back: int = 7) -> Iterator[Paper]:
        """RSSフィードから論文を取得"""
        self.last_error = None
        self.last_error_type = None

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
            self.last_error = str(e)
            self.last_error_type = "rss_fetch_error"
            logger.error(f"Failed to fetch RSS for {journal.name}: {e}")

    def _parse_entry(self, entry: dict, journal: Journal) -> Paper | None:
        """RSSエントリーをPaperオブジェクトに変換"""
        try:
            title = entry.get("title", "").strip()
            if not title:
                return None

            authors = []
            if "authors" in entry:
                authors = [a.get("name", "") for a in entry.authors if a.get("name")]
            elif "author" in entry:
                authors = [entry.author]

            doi = ""
            link = entry.get("link", "")
            if "doi.org/" in link:
                doi = link.split("doi.org/")[-1]
            elif "prism_doi" in entry:
                doi = entry.prism_doi

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
        self.last_error: str | None = None
        self.last_error_type: str | None = None
        self.last_status_code: int | None = None

        self.headers = {"User-Agent": f"JournalTracker/1.0 (mailto:{email})" if email else "JournalTracker/1.0"}

        retry = Retry(
            total=3,
            connect=0,
            read=0,
            status=3,
            other=0,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    @staticmethod
    def classify_request_exception(exc: requests.RequestException) -> str:
        """接続例外を運用上扱いやすいカテゴリに分類"""
        if isinstance(exc, requests.HTTPError):
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {401, 403}:
                return "http_auth_error"
            if status is not None and 400 <= status < 500:
                return "http_client_error"
            if status is not None and status >= 500:
                return "http_server_error"
            return "http_error"

        if isinstance(exc, requests.Timeout):
            return "timeout_error"

        if isinstance(exc, requests.ProxyError):
            return "proxy_error"

        if isinstance(exc, requests.SSLError):
            return "tls_error"

        if isinstance(exc, requests.ConnectionError):
            message = str(exc).lower()
            if "name or service not known" in message or "temporary failure in name resolution" in message:
                return "dns_error"
            if "connection refused" in message:
                return "connection_refused"
            return "connection_error"

        if isinstance(exc.__cause__, socket.gaierror):
            return "dns_error"
        if isinstance(exc.__cause__, ssl.SSLError):
            return "tls_error"

        return "network_error"

    def fetch(self, journal: Journal, days_back: int = 7) -> Iterator[Paper]:
        """CrossRef APIから論文を取得"""
        self.last_error = None
        self.last_error_type = None
        self.last_status_code = None

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
            response = self.session.get(url, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            items = data.get("message", {}).get("items", [])

            for item in items:
                paper = self._parse_item(item, journal)
                if paper:
                    yield paper

        except requests.RequestException as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            error_type = self.classify_request_exception(e)
            self.last_error = str(e)
            self.last_error_type = error_type
            self.last_status_code = status_code
            logger.error(
                f"Failed to fetch from CrossRef for {journal.name}: {e}"
                f" (error_type={error_type}, status={status_code}, issn={journal.issn})"
            )
        except Exception as e:
            self.last_error = str(e)
            self.last_error_type = "crossref_unknown_error"
            logger.error(f"Failed to fetch from CrossRef for {journal.name}: {e}")

    @staticmethod
    def _extract_published_date(item: dict) -> datetime | None:
        """CrossRefの日付情報を優先順で解釈してdatetimeに変換"""
        date_keys = ["published", "published-online", "published-print", "issued"]
        for date_key in date_keys:
            date_parts = item.get(date_key, {}).get("date-parts", [[]])
            if not date_parts or not date_parts[0]:
                continue

            parts = date_parts[0]
            year = parts[0] if len(parts) > 0 else 2000
            month = parts[1] if len(parts) > 1 else 1
            day = parts[2] if len(parts) > 2 else 1
            try:
                return datetime(year, month, day)
            except ValueError:
                logger.warning(f"Invalid CrossRef date parts for key '{date_key}': {parts}")
                continue

        return None

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

            published_date = self._extract_published_date(item)

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
        self.rate_limit_seconds = float(fetch_config.get("rate_limit_seconds", 1.0))

        email = os.environ.get("CROSSREF_EMAIL", config.get("email", {}).get("sender_email", ""))
        self.rss_fetcher = RSSFetcher(timeout=self.timeout)
        self.crossref_fetcher = CrossRefFetcher(timeout=self.timeout, email=email)
        self.last_run_stats = FetchRunStats()

    def fetch_all(self, journals: list[Journal]) -> Iterator[Paper]:
        """全ジャーナルから論文を取得"""
        self.last_run_stats = FetchRunStats()

        total_journals = len(journals)
        for index, journal in enumerate(journals):
            logger.info(f"Fetching papers from {journal.name}...")

            fetched_from_journal = 0
            if journal.has_rss:
                for paper in self.rss_fetcher.fetch(journal, self.days_back):
                    fetched_from_journal += 1
                    self.last_run_stats.fetched_count += 1
                    yield paper

                if self.rss_fetcher.last_error:
                    self.last_run_stats.failed_journals.append(
                        {"journal": journal.name, "source": "rss", "error_type": self.rss_fetcher.last_error_type or "unknown"}
                    )

            elif journal.issn:
                for paper in self.crossref_fetcher.fetch(journal, self.days_back):
                    fetched_from_journal += 1
                    self.last_run_stats.fetched_count += 1
                    yield paper

                if self.crossref_fetcher.last_error:
                    self.last_run_stats.failed_journals.append(
                        {
                            "journal": journal.name,
                            "source": "crossref",
                            "error_type": self.crossref_fetcher.last_error_type or "unknown",
                        }
                    )
            else:
                logger.warning(f"No fetch method available for {journal.name}")
                self.last_run_stats.skipped_journals.append(journal.name)

            logger.info(f"Fetched {fetched_from_journal} papers from {journal.name}")
            if self.rate_limit_seconds > 0 and index < total_journals - 1:
                time.sleep(self.rate_limit_seconds)  # Rate limiting
