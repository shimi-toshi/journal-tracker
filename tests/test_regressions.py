import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src.fetcher import CrossRefFetcher, PaperFetcher
from src.main import run_self_check
from src.parser import Journal, Paper, normalize_doi
from src.storage import PaperStorage, SCHEMA_VERSION


def test_normalize_doi_and_unique_id_fallback():
    assert normalize_doi(" https://doi.org/10.1234/ABC ") == "10.1234/abc"

    p = Paper(title="  Sample   Title  ", journal_name="  Journal X ", doi="doi:")
    assert p.unique_id == Paper(title="sample title", journal_name="journal x", doi="").unique_id


def test_storage_authors_json_roundtrip_and_backward_compat():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "papers.db"
        storage = PaperStorage(db_path)

        paper = Paper(title="T", journal_name="J", authors=["Smith, Jr., John", "Alice"])
        storage.save_batch([paper])
        rows = storage.get_recent_papers(days=1)
        assert rows[0].authors == ["Smith, Jr., John", "Alice"]

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO papers (unique_id, title, journal_name, authors, abstract, doi, url, published_date, fetched_at, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
                """,
                ("legacy-id", "Legacy", "J", "Author One,Author Two", "", "", "", None),
            )
            conn.commit()

        legacy = [p for p in storage.get_unnotified() if p.title == "Legacy"][0]
        assert legacy.authors == ["Author One", "Author Two"]


def test_crossref_date_fallback_order_and_invalid_date_skip():
    fetcher = CrossRefFetcher()
    journal = Journal(name="J")
    item = {
        "title": ["A"],
        "author": [],
        "published": {"date-parts": [[2026, 13, 40]]},
        "published-online": {"date-parts": [[2026, 7]]},
    }
    paper = fetcher._parse_item(item, journal)
    assert paper is not None
    assert paper.published_date.year == 2026
    assert paper.published_date.month == 7
    assert paper.published_date.day == 1


def test_storage_migrates_old_schema_backfills_and_sets_version():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "papers.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE papers (
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
                """
            )
            conn.execute(
                """
                INSERT INTO papers (unique_id, title, journal_name, authors, abstract, doi, url, published_date, fetched_at, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
                """,
                ("legacy-1", "Title", "J", "[]", "", "https://doi.org/10.9999/ABC", "", None),
            )
            conn.commit()

        PaperStorage(db_path)

        with sqlite3.connect(db_path) as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)")}
            assert "normalized_doi" in cols
            normalized = conn.execute(
                "SELECT normalized_doi FROM papers WHERE unique_id = ?", ("legacy-1",)
            ).fetchone()[0]
            assert normalized == "10.9999/abc"
            schema_version = conn.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()[0]
            assert int(schema_version) == SCHEMA_VERSION


def test_unique_index_on_normalized_doi_blocks_duplicate_legacy_rows_and_is_new_consistent():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "papers.db"
        storage = PaperStorage(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO papers (unique_id, normalized_doi, title, journal_name, authors, abstract, doi, url, published_date, fetched_at, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
                """,
                ("legacy-custom-id", "10.1234/abc", "Old", "J", "[]", "", "10.1234/ABC", "", None),
            )
            conn.commit()

        duplicate = Paper(title="New Title", journal_name="J", doi="https://doi.org/10.1234/abc")
        inserted = storage.save_batch([duplicate])
        assert inserted == []
        assert storage.is_new(duplicate) is False


def test_crossref_fetcher_configures_retry_for_transient_status_codes():
    fetcher = CrossRefFetcher()
    https_adapter = fetcher.session.get_adapter("https://api.crossref.org")
    retries = https_adapter.max_retries

    assert retries.total == 3
    assert retries.connect == 0
    assert retries.status == 3
    assert 429 in retries.status_forcelist
    assert 503 in retries.status_forcelist


def test_crossref_error_classification():
    response = Mock(status_code=403)
    error = requests.HTTPError("forbidden", response=response)
    assert CrossRefFetcher.classify_request_exception(error) == "http_auth_error"


def test_fetch_save_export_integration_with_mocked_crossref():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        db_path = td_path / "papers.db"

        config = {
            "database": {"path": str(db_path)},
            "export": {"output_dir": str(td_path / "output")},
            "fetch": {"days_back": 7, "timeout": 10, "rate_limit_seconds": 0},
        }
        journal = Journal(name="Test Journal", issn="1234-5678")

        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Test Paper"],
                        "author": [{"given": "Alice", "family": "Smith"}],
                        "DOI": "10.1000/xyz",
                        "issued": {"date-parts": [[2026, 2, 1]]},
                    }
                ]
            }
        }

        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = payload

        fetcher = PaperFetcher(config)
        with patch.object(fetcher.crossref_fetcher.session, "get", return_value=mock_response):
            papers = list(fetcher.fetch_all([journal]))

        assert len(papers) == 1
        assert fetcher.last_run_stats.fetched_count == 1
        assert fetcher.last_run_stats.failed_journals == []

        storage = PaperStorage(db_path)
        inserted = storage.save_batch(papers)
        assert len(inserted) == 1



def test_fetcher_rate_limit_can_be_disabled_for_fast_runs():
    config = {"fetch": {"days_back": 7, "timeout": 10, "rate_limit_seconds": 0}}
    fetcher = PaperFetcher(config)
    journal = Journal(name="NoSource")

    with patch("src.fetcher.time.sleep") as mocked_sleep:
        papers = list(fetcher.fetch_all([journal]))

    assert papers == []
    mocked_sleep.assert_not_called()


def test_fetcher_sleeps_between_journals_but_not_after_last():
    config = {"fetch": {"days_back": 7, "timeout": 10, "rate_limit_seconds": 0.5}}
    fetcher = PaperFetcher(config)
    journals = [Journal(name="A"), Journal(name="B")]

    with patch("src.fetcher.time.sleep") as mocked_sleep:
        papers = list(fetcher.fetch_all(journals))

    assert papers == []
    mocked_sleep.assert_called_once_with(0.5)

def test_run_self_check_ok_with_minimal_config():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        excel_path = td_path / "journals.xlsx"
        df = pd.DataFrame(
            columns=[
                "Journal Title",
                "Abbrev",
                "Publisher",
                "Journal URL",
                "RSS Feed",
                "Online ISSN",
                "Print ISSN",
                "Status",
            ]
        )
        df.to_excel(excel_path, index=False)

        template_dir = td_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        config = {
            "journals": {"excel_path": str(excel_path)},
            "database": {"path": str(td_path / "papers.db")},
            "export": {"output_dir": str(td_path / "output")},
            "logs": {"output_dir": str(td_path / "logs")},
            "html_export": {"template_dir": str(template_dir), "output_dir": str(td_path / "docs")},
        }

        issues = run_self_check(config)
        assert issues == []


def test_run_self_check_detects_invalid_template():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        excel_path = td_path / "journals.xlsx"
        pd.DataFrame(columns=[
            "Journal Title", "Abbrev", "Publisher", "Journal URL", "RSS Feed", "Online ISSN", "Print ISSN", "Status"
        ]).to_excel(excel_path, index=False)

        template_dir = td_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "index.html").write_text("{% if broken %}", encoding="utf-8")

        config = {
            "journals": {"excel_path": str(excel_path)},
            "database": {"path": str(td_path / "papers.db")},
            "export": {"output_dir": str(td_path / "output")},
            "logs": {"output_dir": str(td_path / "logs")},
            "html_export": {"template_dir": str(template_dir), "output_dir": str(td_path / "docs")},
        }

        issues = run_self_check(config)
        assert any("HTMLテンプレート検証に失敗" in issue for issue in issues)
