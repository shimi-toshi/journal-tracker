"""既読管理モジュール - SQLite"""

import sqlite3
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterator

from .parser import Paper, normalize_doi, normalize_url

logger = logging.getLogger(__name__)
SCHEMA_VERSION = 3


class PaperStorage:
    """論文の既読管理をSQLiteで行うクラス"""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """データベースを初期化"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    unique_id TEXT PRIMARY KEY,
                    normalized_doi TEXT,
                    normalized_url TEXT,
                    title TEXT NOT NULL,
                    journal_name TEXT NOT NULL,
                    authors TEXT,
                    abstract TEXT,
                    doi TEXT,
                    url TEXT,
                    published_date TEXT,
                    fetched_at TEXT NOT NULL,
                    notified INTEGER DEFAULT 0
                )
            """)
            self._init_meta_table(conn)
            self._init_journal_status_table(conn)

            columns = {row[1] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
            if "normalized_doi" not in columns:
                conn.execute("ALTER TABLE papers ADD COLUMN normalized_doi TEXT")
            if "normalized_url" not in columns:
                conn.execute("ALTER TABLE papers ADD COLUMN normalized_url TEXT")

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal ON papers(journal_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fetched ON papers(fetched_at)
            """)

            current_version = self._get_schema_version(conn)
            if current_version < SCHEMA_VERSION:
                self._backfill_normalized_doi(conn)
                self._backfill_normalized_url(conn)

            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_normalized_doi
                ON papers(normalized_doi)
                WHERE normalized_doi IS NOT NULL AND normalized_doi != ''
            """)
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_normalized_url
                ON papers(normalized_url)
                WHERE normalized_url IS NOT NULL AND normalized_url != ''
            """)

            self._set_schema_version(conn, SCHEMA_VERSION)
            conn.commit()

    @staticmethod
    def _init_meta_table(conn: sqlite3.Connection):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

    @staticmethod
    def _init_journal_status_table(conn: sqlite3.Connection):
        """ジャーナル別の取得成否を継続記録するテーブル（長期エラー検知用）"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal_status (
                journal_name TEXT PRIMARY KEY,
                last_success_at TEXT,
                last_error_at TEXT,
                last_error_type TEXT,
                consecutive_failures INTEGER DEFAULT 0,
                updated_at TEXT
            )
        """)

    @staticmethod
    def _get_schema_version(conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        if not row:
            return 0
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int):
        conn.execute(
            """
            INSERT INTO metadata(key, value) VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(version),),
        )

    @staticmethod
    def _backfill_normalized_doi(conn: sqlite3.Connection):
        """旧データのnormalized_doiを必要行のみバックフィル"""
        rows = conn.execute(
            """
            SELECT rowid, doi, normalized_doi
            FROM papers
            WHERE normalized_doi IS NULL OR normalized_doi = ''
            ORDER BY rowid
            """
        ).fetchall()
        existing = {
            row[0] for row in conn.execute(
                "SELECT normalized_doi FROM papers WHERE normalized_doi IS NOT NULL AND normalized_doi != ''"
            ).fetchall()
        }

        for rowid, doi, existing_normalized in rows:
            normalized = normalize_doi(existing_normalized or doi or "")
            if not normalized or normalized in existing:
                continue
            conn.execute(
                "UPDATE papers SET normalized_doi = ? WHERE rowid = ?",
                (normalized, rowid),
            )
            existing.add(normalized)

    @staticmethod
    def _backfill_normalized_url(conn: sqlite3.Connection):
        """旧データのnormalized_urlを必要行のみバックフィル"""
        rows = conn.execute(
            """
            SELECT rowid, url, normalized_url
            FROM papers
            WHERE normalized_url IS NULL OR normalized_url = ''
            ORDER BY rowid
            """
        ).fetchall()
        existing = {
            row[0] for row in conn.execute(
                "SELECT normalized_url FROM papers WHERE normalized_url IS NOT NULL AND normalized_url != ''"
            ).fetchall()
        }

        for rowid, url, existing_normalized in rows:
            normalized = normalize_url(existing_normalized or url or "")
            if not normalized or normalized in existing:
                continue
            conn.execute(
                "UPDATE papers SET normalized_url = ? WHERE rowid = ?",
                (normalized, rowid),
            )
            existing.add(normalized)

    def is_new(self, paper: Paper) -> bool:
        """論文が新着かどうかをチェック（unique_id と normalized_doi の両方を評価）"""
        normalized_doi = normalize_doi(paper.doi)
        normalized_url = normalize_url(paper.url)
        with sqlite3.connect(self.db_path) as conn:
            if normalized_doi and normalized_url:
                cursor = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ? OR normalized_doi = ? OR normalized_url = ? LIMIT 1",
                    (paper.unique_id, normalized_doi, normalized_url),
                )
            elif normalized_doi:
                cursor = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ? OR normalized_doi = ? LIMIT 1",
                    (paper.unique_id, normalized_doi),
                )
            elif normalized_url:
                cursor = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ? OR normalized_url = ? LIMIT 1",
                    (paper.unique_id, normalized_url),
                )
            else:
                cursor = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ? LIMIT 1",
                    (paper.unique_id,),
                )
            return cursor.fetchone() is None

    def save_batch(self, papers: list[Paper]) -> list[Paper]:
        """複数の論文を保存し、新着のみを返す"""
        new_papers = []
        with sqlite3.connect(self.db_path) as conn:
            for paper in papers:
                normalized_authors = [str(author).strip() for author in paper.authors if str(author).strip()]
                normalized_doi = normalize_doi(paper.doi)
                normalized_url = normalize_url(paper.url)
                cursor = conn.execute("""
                    INSERT OR IGNORE INTO papers
                    (unique_id, normalized_doi, normalized_url, title, journal_name, authors, abstract, doi, url, published_date, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper.unique_id,
                    normalized_doi,
                    normalized_url,
                    paper.title,
                    paper.journal_name,
                    json.dumps(normalized_authors, ensure_ascii=False),
                    paper.abstract,
                    paper.doi,
                    paper.url,
                    paper.published_date.isoformat() if paper.published_date else None,
                    datetime.now().isoformat(),
                ))

                if cursor.rowcount == 1:
                    new_papers.append(paper)
                    logger.info(f"New paper saved: {paper.title[:50]}...")
            conn.commit()
        return new_papers

    def mark_notified(self, papers: list[Paper]):
        """論文を通知済みとしてマーク"""
        with sqlite3.connect(self.db_path) as conn:
            for paper in papers:
                conn.execute(
                    "UPDATE papers SET notified = 1 WHERE unique_id = ?",
                    (paper.unique_id,)
                )
            conn.commit()

    @staticmethod
    def _parse_authors(raw_authors: str | None) -> list[str]:
        """保存済み著者文字列を配列に復元（JSON優先、旧CSV形式も互換対応）"""
        if not raw_authors:
            return []

        try:
            parsed = json.loads(raw_authors)
            if isinstance(parsed, list):
                return [str(author) for author in parsed if str(author)]
        except (json.JSONDecodeError, TypeError):
            pass

        return [author.strip() for author in raw_authors.split(",") if author.strip()]

    def get_unnotified(self) -> Iterator[Paper]:
        """未通知の論文を取得"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM papers WHERE notified = 0 ORDER BY fetched_at DESC"
            )
            for row in cursor:
                yield Paper(
                    title=row["title"],
                    journal_name=row["journal_name"],
                    authors=self._parse_authors(row["authors"]),
                    abstract=row["abstract"] or "",
                    doi=row["doi"] or "",
                    url=row["url"] or "",
                    published_date=datetime.fromisoformat(row["published_date"]) if row["published_date"] else None,
                    fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None,
                )

    def get_recent_papers(self, days: int = 7, max_publication_lag_days: int | None = None) -> list[Paper]:
        """直近N日分の論文を取得（fetched_at基準）

        max_publication_lag_days を指定すると、取得日(fetched_at)より大きく前に公表された論文
        （= CrossRef等のバックカタログ再登録で古い論文が直近に紛れ込むケース）を除外する。
        月のみ日付(YYYY-MM→1日扱い)の正規の新着は公表日と取得日が近いため残る。
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor = conn.execute(
                "SELECT * FROM papers WHERE fetched_at >= ? ORDER BY journal_name, published_date DESC",
                (cutoff,)
            )
            papers = []
            for row in cursor:
                published_date = datetime.fromisoformat(row["published_date"]) if row["published_date"] else None
                fetched_at = datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None

                # バックカタログ再登録ガード: 公表が取得より大幅に前なら新着扱いしない
                if (
                    max_publication_lag_days is not None
                    and published_date is not None
                    and fetched_at is not None
                    and (fetched_at - published_date).days > max_publication_lag_days
                ):
                    continue

                papers.append(Paper(
                    title=row["title"],
                    journal_name=row["journal_name"],
                    authors=self._parse_authors(row["authors"]),
                    abstract=row["abstract"] or "",
                    doi=row["doi"] or "",
                    url=row["url"] or "",
                    published_date=published_date,
                    fetched_at=fetched_at,
                ))
            return papers

    def update_journal_status(
        self,
        attempted_journals: list[str],
        failed_journals: list[dict[str, str]],
    ) -> None:
        """各ジャーナルの取得成否を記録し、連続失敗回数を更新する。

        attempted_journals: 今回取得を試みたジャーナル名（RSS/CrossRefを実行したもの）
        failed_journals: 今回失敗したジャーナル情報（{"journal", "source", "error_type"}）
        """
        now = datetime.now().isoformat()
        error_by_journal = {f["journal"]: f.get("error_type", "unknown") for f in failed_journals}

        with sqlite3.connect(self.db_path) as conn:
            for name in attempted_journals:
                if name in error_by_journal:
                    conn.execute(
                        """
                        INSERT INTO journal_status
                            (journal_name, last_error_at, last_error_type, consecutive_failures, updated_at)
                        VALUES (?, ?, ?, 1, ?)
                        ON CONFLICT(journal_name) DO UPDATE SET
                            last_error_at = excluded.last_error_at,
                            last_error_type = excluded.last_error_type,
                            consecutive_failures = journal_status.consecutive_failures + 1,
                            updated_at = excluded.updated_at
                        """,
                        (name, now, error_by_journal[name], now),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO journal_status
                            (journal_name, last_success_at, consecutive_failures, updated_at)
                        VALUES (?, ?, 0, ?)
                        ON CONFLICT(journal_name) DO UPDATE SET
                            last_success_at = excluded.last_success_at,
                            consecutive_failures = 0,
                            updated_at = excluded.updated_at
                        """,
                        (name, now, now),
                    )
            conn.commit()

    def get_failing_journals(self, threshold: int = 7) -> dict[str, dict]:
        """長期エラーで取得できていないジャーナルを返す。

        判定: 連続失敗が threshold 回以上、または、直近の取得が失敗していて(連続失敗>=1)、
        最後に取得できた時点（journal_status の last_success_at、無ければ papers の最新 fetched_at を代用）
        から threshold 日以上経過しているもの。後者により履歴が浅い導入直後でも即座に検知できる。
        戻り値: {journal_name: {"error_type", "consecutive_failures", "last_success_at", "days_since_success"}}
        """
        now = datetime.now()
        result: dict[str, dict] = {}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            last_paper = dict(
                conn.execute(
                    "SELECT journal_name, MAX(fetched_at) FROM papers GROUP BY journal_name"
                ).fetchall()
            )
            for row in conn.execute("SELECT * FROM journal_status"):
                name = row["journal_name"]
                consecutive = row["consecutive_failures"] or 0
                if consecutive < 1:
                    continue  # 直近で成功しているジャーナルは対象外

                proxy_success = row["last_success_at"] or last_paper.get(name)
                days_since_success = None
                if proxy_success:
                    try:
                        days_since_success = (now - datetime.fromisoformat(proxy_success)).days
                    except (TypeError, ValueError):
                        days_since_success = None

                long_term = consecutive >= threshold or (
                    days_since_success is not None and days_since_success >= threshold
                )
                if not long_term:
                    continue

                result[name] = {
                    "error_type": row["last_error_type"] or "unknown",
                    "consecutive_failures": consecutive,
                    "last_success_at": proxy_success,
                    "days_since_success": days_since_success,
                }
        return result

    def get_stats(self) -> dict:
        """統計情報を取得"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            notified = conn.execute("SELECT COUNT(*) FROM papers WHERE notified = 1").fetchone()[0]
            by_journal = dict(conn.execute(
                "SELECT journal_name, COUNT(*) FROM papers GROUP BY journal_name"
            ).fetchall())

            return {
                "total": total,
                "notified": notified,
                "unnotified": total - notified,
                "by_journal": by_journal,
            }
