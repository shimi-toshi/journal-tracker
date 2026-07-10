import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests
import yaml

from src.fetcher import CrossRefFetcher, PaperFetcher
from src.main import main, run_self_check
from src.parser import Journal, Paper, normalize_doi, normalize_url
from src.storage import PaperStorage, SCHEMA_VERSION


def test_classify_request_exception_handles_proxy_and_ssl_errors():
    # requests.ProxyError / SSLError は requests.exceptions 経由でのみ存在する（トップレベルには無い）
    assert CrossRefFetcher.classify_request_exception(requests.exceptions.ProxyError("x")) == "proxy_error"
    assert CrossRefFetcher.classify_request_exception(requests.exceptions.SSLError("x")) == "tls_error"


def test_crossref_uses_works_endpoint_with_issn_and_created_date_filter():
    fetcher = CrossRefFetcher(email="x@y.com")
    journal = Journal(name="C", issn="2380-2871")

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"items": []}}
        return resp

    with patch.object(fetcher.session, "get", side_effect=fake_get):
        list(fetcher.fetch(journal, days_back=7))

    assert captured["url"] == "https://api.crossref.org/works"
    # 初回デポジット日(from-created-date)で絞り、created降順で取得する
    assert captured["params"]["filter"].startswith("issn:2380-2871,from-created-date:")
    assert captured["params"]["sort"] == "created"


def test_crossref_queries_both_online_and_print_issn_with_or():
    # Online/Print 双方を持つ誌は両ISSNを issn: フィルタで併記する（CrossRefはORで解釈）。
    # works が一方のISSN（多くのpublisherでPrint）にしか紐づかない誌の取りこぼし防止。
    fetcher = CrossRefFetcher(email="x@y.com")
    journal = Journal(name="AOS", issn="1873-6289", issn_print="0361-3682")

    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"items": []}}
        return resp

    with patch.object(fetcher.session, "get", side_effect=fake_get):
        list(fetcher.fetch(journal, days_back=7))

    assert captured["params"]["filter"].startswith("issn:1873-6289,issn:0361-3682,from-created-date:")


def test_journal_issns_dedupes_and_keeps_order():
    # Online優先・重複/空白除去。Print のみの誌は1つ、Online==Print は1つに畳む。
    assert Journal(name="J", issn="A", issn_print="B").issns == ["A", "B"]
    assert Journal(name="J", issn="P", issn_print="P").issns == ["P"]
    assert Journal(name="J", issn="O").issns == ["O"]
    assert Journal(name="J").issns == []


def test_normalize_doi_url_and_unique_id_fallback():
    assert normalize_doi(" https://doi.org/10.1234/ABC ") == "10.1234/abc"
    assert normalize_url(" HTTPS://EXAMPLE.com/paper?a=1#frag ") == "https://example.com/paper?a=1"

    p = Paper(title="  Sample   Title  ", journal_name="  Journal X ", doi="doi:", url="")
    assert p.unique_id == Paper(title="sample title", journal_name="journal x", doi="", url="").unique_id

    u1 = Paper(title="Title A", journal_name="J", doi="", url="https://example.com/paper")
    u2 = Paper(title="Title B", journal_name="J", doi="", url="https://example.com/paper")
    assert u1.unique_id == u2.unique_id


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
            assert "normalized_url" in cols
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


def test_storage_deduplicates_same_url_without_doi():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "papers.db"
        storage = PaperStorage(db_path)

        first = Paper(title="Version A", journal_name="J", url="https://example.com/paper")
        second = Paper(title="Version B", journal_name="J", url="https://example.com/paper")

        inserted_first = storage.save_batch([first])
        inserted_second = storage.save_batch([second])

        assert len(inserted_first) == 1
        assert inserted_second == []
        assert storage.is_new(second) is False


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


def test_run_self_check_detects_duplicate_issn_and_missing_fetch_method():
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        excel_path = td_path / "journals.xlsx"
        # 同一Online ISSNを持つ2誌（取得元の取り違え）と、ISSNの無い1誌
        df = pd.DataFrame(
            [
                {"Journal Title": "Journal A", "Abbrev": "A", "Publisher": "P", "Journal URL": "",
                 "RSS Feed": "—", "Online ISSN": "1758-7743", "Print ISSN": "1111-1111", "Status": "No RSS"},
                {"Journal Title": "Journal B", "Abbrev": "B", "Publisher": "P", "Journal URL": "",
                 "RSS Feed": "—", "Online ISSN": "1758-7743", "Print ISSN": "2222-2222", "Status": "No RSS"},
                {"Journal Title": "Journal C", "Abbrev": "C", "Publisher": "P", "Journal URL": "",
                 "RSS Feed": "—", "Online ISSN": "", "Print ISSN": "", "Status": "No RSS"},
            ],
            columns=[
                "Journal Title", "Abbrev", "Publisher", "Journal URL", "RSS Feed",
                "Online ISSN", "Print ISSN", "Status",
            ],
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
        assert any("ISSN重複" in issue and "1758-7743" in issue for issue in issues)
        assert any("取得手段がありません" in issue and "Journal C" in issue for issue in issues)


def test_dry_run_does_not_write_to_database():
    # 回帰: --dry-run が save_batch でDBに書き込むと新着が「消費」され、
    # 次回の本番実行で同じ論文が新着扱いされず出力から永久に漏れる
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        excel_path = td_path / "journals.xlsx"
        pd.DataFrame(
            [
                {"Journal Title": "Dry Run Journal", "Abbrev": "DRJ", "Publisher": "P", "Journal URL": "",
                 "RSS Feed": "—", "Online ISSN": "1234-5678", "Print ISSN": "", "Status": "No RSS"},
            ],
            columns=[
                "Journal Title", "Abbrev", "Publisher", "Journal URL", "RSS Feed",
                "Online ISSN", "Print ISSN", "Status",
            ],
        ).to_excel(excel_path, index=False)

        template_dir = td_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        db_path = td_path / "papers.db"
        config = {
            "journals": {"excel_path": str(excel_path)},
            "database": {"path": str(db_path)},
            "export": {"output_dir": str(td_path / "output")},
            "logs": {"output_dir": str(td_path / "logs")},
            "html_export": {"template_dir": str(template_dir), "output_dir": str(td_path / "docs")},
            "fetch": {"days_back": 7, "timeout": 10, "rate_limit_seconds": 0},
        }
        config_path = td_path / "config.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

        paper = Paper(title="Dry Paper", journal_name="Dry Run Journal", doi="10.1000/dry")

        def run_main(argv):
            with patch("src.fetcher.CrossRefFetcher.fetch", return_value=[paper]), \
                 patch("sys.argv", argv):
                return main()

        def paper_count():
            with sqlite3.connect(db_path) as conn:
                return conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

        # dry-runではDBに保存されず、journal_statusも更新されない
        assert run_main(["prog", "--config", str(config_path), "--dry-run"]) == 0
        assert paper_count() == 0
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM journal_status").fetchone()[0] == 0

        # 本番実行では同じ論文が新着として保存される（dry-runに消費されていない）
        assert run_main(["prog", "--config", str(config_path)]) == 0
        assert paper_count() == 1
