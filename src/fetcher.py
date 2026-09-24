"""論文取得モジュール - CrossRef API対応"""

import logging
import os
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .parser import Journal, Paper, clean_abstract, clean_markup

logger = logging.getLogger(__name__)


@dataclass
class FetchRunStats:
    """実行時の取得統計"""

    fetched_count: int = 0
    failed_journals: list[dict[str, str]] = field(default_factory=list)
    skipped_journals: list[str] = field(default_factory=list)
    catchup_journals: dict[str, int] = field(default_factory=dict)  # 誌名 -> 遡った日数


class CrossRefFetcher:
    """CrossRef APIから論文を取得"""

    # ジャーナル別エンドポイント（/journals/{issn}/works）はISSNがCrossRefの代表ISSNと
    # 一致しないと404になるため、ISSNフィルタ付きの汎用worksエンドポイントを使う。
    # これによりprint/onlineどちらのISSNでもヒットし、404にならない。
    WORKS_URL = "https://api.crossref.org/works"
    # CrossRefの1リクエスト上限。大量刊行誌やキャッチアップ取得でも1回で収まる
    MAX_ROWS = 1000
    # 必要なフィールドだけ返させて転送量を抑える
    SELECT_FIELDS = "DOI,title,author,published,published-online,published-print,issued,abstract"

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

        if isinstance(exc, requests.exceptions.ProxyError):
            return "proxy_error"

        if isinstance(exc, requests.exceptions.SSLError):
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

        issns = journal.issns
        if not issns:
            logger.warning(f"No ISSN for {journal.name}")
            return

        try:
            # 出版日(from-pub-date)でも最終インデックス日(from-index-date)でもなく、
            # 初回デポジット日(from-created-date)で絞る。created は初回登録時にシステムが付与し
            # 以後固定されるため、再インデックス（被引用数更新・メタデータ修正・既存DOIの
            # バックカタログ再デポジット）の影響を受けず、古い論文が新着として流入しない。
            # 月のみ日付(YYYY-MM)の正規の新着は公表とほぼ同時にデポジットされるため取りこぼさず、
            # 「直近N日」を fetched_at 基準とする設計とも整合する。
            from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

            # Online/Print 両ISSNを `issn:` フィルタで併記する。CrossRefは同名フィルタを
            # ORで解釈するため、works が一方のISSN（多くのpublisherでPrint）にしか紐づかない
            # 誌でも取りこぼさない。from-created-date は別名フィルタなのでANDで効く。
            issn_filter = ",".join(f"issn:{issn}" for issn in issns)

            params = {
                "filter": f"{issn_filter},from-created-date:{from_date}",
                "rows": self.MAX_ROWS,
                "sort": "created",
                "order": "desc",
                "select": self.SELECT_FIELDS,
            }

            response = self.session.get(self.WORKS_URL, params=params, headers=self.headers, timeout=self.timeout)
            response.raise_for_status()

            message = response.json().get("message", {})
            items = message.get("items", [])
            total = message.get("total-results")
            if isinstance(total, int) and total > len(items):
                logger.warning(
                    f"CrossRef returned {len(items)} of {total} works for {journal.name}"
                    f" (days_back={days_back}); older items in the window were not fetched"
                )

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
                f" (error_type={error_type}, status={status_code}, issn={','.join(issns)})"
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
            except (TypeError, ValueError):
                # date-parts が [[null]] のように欠損値を含む場合もあるため次のキーへ
                logger.warning(f"Invalid CrossRef date parts for key '{date_key}': {parts}")
                continue

        return None

    def _parse_item(self, item: dict, journal: Journal) -> Paper | None:
        """CrossRef APIレスポンスをPaperオブジェクトに変換"""
        try:
            title_list = item.get("title", [])
            title = clean_markup(title_list[0]) if title_list else ""
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
                elif author.get("name"):
                    authors.append(author["name"])  # 団体著者（コンソーシアム等）

            doi = item.get("DOI", "")
            url = f"https://doi.org/{doi}" if doi else ""

            published_date = self._extract_published_date(item)

            abstract = clean_abstract(item.get("abstract", ""))

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
    """論文取得の統合クラス（CrossRef APIで全ジャーナルを取得）"""

    def __init__(self, config: dict):
        fetch_config = config.get("fetch", {})
        self.timeout = fetch_config.get("timeout", 30)
        self.days_back = fetch_config.get("days_back", 7)
        self.max_catchup_days = int(fetch_config.get("max_catchup_days", 30))
        self.rate_limit_seconds = float(fetch_config.get("rate_limit_seconds", 1.0))

        email = os.environ.get("CROSSREF_EMAIL", "")
        self.crossref_fetcher = CrossRefFetcher(timeout=self.timeout, email=email)
        self.last_run_stats = FetchRunStats()

    def window_days(self, last_success: datetime | None, now: datetime | None = None) -> int:
        """ジャーナルごとの取得日数を決める（キャッチアップ取得）。

        通常は days_back。最後の取得成功から days_back 日以上空いている（Actions停止・長期エラー等）
        場合は、その空白期間の登録分を取りこぼさないよう「最後の成功日の1日前」まで遡る。
        遡りすぎを防ぐため max_catchup_days で頭打ちにする。
        """
        if last_success is None:
            return self.days_back
        now = now or datetime.now()
        gap_days = (now - last_success).days + 1
        return max(self.days_back, min(self.max_catchup_days, gap_days))

    def fetch_all(
        self, journals: list[Journal], last_success: dict[str, datetime] | None = None
    ) -> Iterator[Paper]:
        """全ジャーナルから論文を取得（ISSNがあればCrossRef、無ければスキップ）

        last_success: {journal_name: 最後に取得成功した日時}。指定するとキャッチアップ取得を行う。
        """
        self.last_run_stats = FetchRunStats()
        last_success = last_success or {}

        total_journals = len(journals)
        for index, journal in enumerate(journals):
            logger.info(f"Fetching papers from {journal.name}...")

            fetched_from_journal = 0
            if journal.issns:
                days_back = self.window_days(last_success.get(journal.name))
                if days_back > self.days_back:
                    self.last_run_stats.catchup_journals[journal.name] = days_back
                    logger.info(f"Catch-up fetch for {journal.name}: last {days_back} days")
                for paper in self.crossref_fetcher.fetch(journal, days_back):
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
