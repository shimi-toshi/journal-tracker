"""既読管理モジュール - SQLite"""

import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Iterator

from .parser import Paper

logger = logging.getLogger(__name__)


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
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal ON papers(journal_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_fetched ON papers(fetched_at)
            """)
            conn.commit()

    def is_new(self, paper: Paper) -> bool:
        """論文が新着かどうかをチェック"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM papers WHERE unique_id = ?",
                (paper.unique_id,)
            )
            return cursor.fetchone() is None

    def save_batch(self, papers: list[Paper]) -> list[Paper]:
        """複数の論文を保存し、新着のみを返す"""
        new_papers = []
        with sqlite3.connect(self.db_path) as conn:
            for paper in papers:
                # 既存チェック
                cursor = conn.execute(
                    "SELECT 1 FROM papers WHERE unique_id = ?",
                    (paper.unique_id,)
                )
                if cursor.fetchone() is not None:
                    continue

                # 新規保存
                conn.execute("""
                    INSERT INTO papers (unique_id, title, journal_name, authors, abstract, doi, url, published_date, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    paper.unique_id,
                    paper.title,
                    paper.journal_name,
                    ",".join(paper.authors),
                    paper.abstract,
                    paper.doi,
                    paper.url,
                    paper.published_date.isoformat() if paper.published_date else None,
                    datetime.now().isoformat(),
                ))
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
                    authors=row["authors"].split(",") if row["authors"] else [],
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
                    authors=row["authors"].split(",") if row["authors"] else [],
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
