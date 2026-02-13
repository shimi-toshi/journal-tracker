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

    def get_recent_papers(self, days: int = 7) -> list[Paper]:
        """直近N日分の論文を取得（fetched_at基準）"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor = conn.execute(
                "SELECT * FROM papers WHERE fetched_at >= ? ORDER BY journal_name, published_date DESC",
                (cutoff,)
            )
            papers = []
            for row in cursor:
                papers.append(Paper(
                    title=row["title"],
                    journal_name=row["journal_name"],
                    authors=self._parse_authors(row["authors"]),
                    abstract=row["abstract"] or "",
                    doi=row["doi"] or "",
                    url=row["url"] or "",
                    published_date=datetime.fromisoformat(row["published_date"]) if row["published_date"] else None,
                    fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else None,
                ))
            return papers

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
