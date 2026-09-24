"""2026-09 全体レビューで入れた修正・機能の回帰テスト"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import yaml

from scripts.status_report import build_report
from src.fetcher import CrossRefFetcher, PaperFetcher
from src.html_exporter import HtmlExporter
from src.main import main
from src.parser import Journal, Paper, clean_abstract, clean_markup, compile_title_patterns, is_excluded_title
from src.storage import PaperStorage
from src.utils import load_config, load_journals_from_excel, load_title_exclusions

JOURNAL_COLUMNS = [
    "Journal Title", "Abbrev", "Publisher", "Journal URL", "RSS Feed", "Online ISSN", "Print ISSN", "Status",
]


def _write_journals(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows, columns=JOURNAL_COLUMNS + ["ABDC", "ABS"]).to_excel(path, index=False)


def _config(td: Path, excel_path: Path) -> dict:
    template_dir = Path(__file__).resolve().parent.parent / "templates"
    return {
        "journals": {"excel_path": str(excel_path)},
        "database": {"path": str(td / "papers.db")},
        "export": {"output_dir": str(td / "output")},
        "logs": {"output_dir": str(td / "logs")},
        "html_export": {
            "template_dir": str(template_dir),
            "output_dir": str(td / "docs"),
            "days_back": 7,
            "selectable_days_range": [1, 30],
        },
        "fetch": {"days_back": 7, "timeout": 10, "rate_limit_seconds": 0},
        "filter": {"exclude_title_patterns": ["^editorial board$", "^issue information\\b"]},
    }


# ---- タイトル・アブストラクトの整形 -------------------------------------------------

def test_clean_markup_strips_tags_entities_and_footnote_links():
    assert clean_markup("The <scp>ESG</scp> premium") == "The ESG premium"
    assert clean_markup("Italian <em>Commercialisti</em>'s pursuit") == "Italian Commercialisti's pursuit"
    assert clean_markup("Auditing &amp; EDP.") == "Auditing & EDP."
    assert clean_markup('Default risk<a href="https://x#fn1" id="c"><sup>1</sup></a>') == "Default risk"
    assert clean_markup("  multi \n  space  ") == "multi space"


def test_clean_abstract_separates_paragraphs_and_drops_heading():
    raw = "<jats:title>Abstract</jats:title><jats:p>We study.</jats:p><jats:p>We find.</jats:p>"
    assert clean_abstract(raw) == "We study. We find."


def test_crossref_parse_cleans_title_and_keeps_organization_authors():
    item = {
        "title": ["Taxes and <i>q</i>"],
        "author": [{"given": "A", "family": "B"}, {"name": "IFRS Research Consortium"}],
        "abstract": "<jats:p>Text &amp; more</jats:p>",
        "DOI": "10.1/x",
        "issued": {"date-parts": [[2026, 5]]},
    }
    paper = CrossRefFetcher()._parse_item(item, Journal(name="J"))
    assert paper.title == "Taxes and q"
    assert paper.authors == ["A B", "IFRS Research Consortium"]
    assert paper.abstract == "Text & more"


def test_crossref_date_with_null_parts_falls_back_instead_of_dropping_paper():
    # date-parts: [[null]] で TypeError になり論文ごと捨てられていた
    item = {
        "title": ["A"],
        "published": {"date-parts": [[None]]},
        "issued": {"date-parts": [[2026, 3, 4]]},
    }
    paper = CrossRefFetcher()._parse_item(item, Journal(name="J"))
    assert paper is not None
    assert paper.published_date == datetime(2026, 3, 4)


def test_crossref_query_uses_max_rows_and_select():
    fetcher = CrossRefFetcher()
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(params)
        resp = Mock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"items": [], "total-results": 0}}
        return resp

    with patch.object(fetcher.session, "get", side_effect=fake_get):
        list(fetcher.fetch(Journal(name="J", issn="1234-5678"), days_back=7))
    assert captured["rows"] == 1000
    assert "DOI" in captured["select"] and "abstract" in captured["select"]


# ---- 論文以外の項目の除外 -------------------------------------------------------------

def test_title_exclusions_from_project_config():
    patterns = load_title_exclusions(load_config())
    for title in ["Editorial Board", "ISSUE INFORMATION", "Issue Information ‐ TOC", "ANNOUNCEMENTS",
                  "AMERICAN FINANCE ASSOCIATION", "Acknowledgement", "2025 Excellence in Refereeing"]:
        assert is_excluded_title(title, patterns), title
    # 訂正記事・通常の論文・誌名を含む論文タイトルは除外しない
    for title in ["Erratum to: Audit fees", "Corrigendum", "Editorial board independence and earnings quality",
                  "The American Finance Association at 85"]:
        assert not is_excluded_title(title, patterns), title


def test_get_recent_papers_applies_title_exclusion_and_lag_guard(tmp_path):
    storage = PaperStorage(tmp_path / "papers.db")
    now = datetime.now()
    storage.save_batch([
        Paper(title="Editorial Board", journal_name="J", doi="10.1/eb"),
        Paper(title="Real paper", journal_name="J", doi="10.1/real", published_date=now),
        Paper(title="Old backfill", journal_name="J", doi="10.1/old", published_date=now - timedelta(days=400)),
    ])
    patterns = compile_title_patterns(["^editorial board$"])
    titles = [p.title for p in storage.get_recent_papers(days=7, max_publication_lag_days=60,
                                                         exclude_title_patterns=patterns)]
    assert titles == ["Real paper"]


# ---- journal_status / 長期エラー / キャッチアップ ------------------------------------

def test_failing_journal_detection_and_reset_on_success(tmp_path):
    storage = PaperStorage(tmp_path / "papers.db")
    for _ in range(3):
        storage.update_journal_status(["A", "B"], [{"journal": "A", "error_type": "timeout_error"}])
    assert set(storage.get_failing_journals(threshold=3)) == {"A"}
    assert storage.get_failing_journals(threshold=3)["A"]["error_type"] == "timeout_error"

    storage.update_journal_status(["A", "B"], [])
    assert storage.get_failing_journals(threshold=3) == {}
    assert set(storage.get_last_success_map()) == {"A", "B"}


def test_catchup_window_days():
    fetcher = PaperFetcher({"fetch": {"days_back": 7, "max_catchup_days": 30}})
    now = datetime(2026, 9, 24, 18, 0)
    assert fetcher.window_days(None, now) == 7
    assert fetcher.window_days(now - timedelta(days=1), now) == 7
    assert fetcher.window_days(now - timedelta(days=20), now) == 21
    assert fetcher.window_days(now - timedelta(days=90), now) == 30


def test_fetch_all_uses_catchup_days_per_journal():
    fetcher = PaperFetcher({"fetch": {"days_back": 7, "max_catchup_days": 30, "rate_limit_seconds": 0}})
    journals = [Journal(name="Stale", issn="1111-1111"), Journal(name="Fresh", issn="2222-2222")]
    seen = {}

    def fake_fetch(journal, days_back):
        seen[journal.name] = days_back
        return iter([])

    with patch.object(fetcher.crossref_fetcher, "fetch", side_effect=fake_fetch):
        list(fetcher.fetch_all(journals, last_success={"Stale": datetime.now() - timedelta(days=15)}))
    assert seen == {"Stale": 16, "Fresh": 7}
    assert fetcher.last_run_stats.catchup_journals == {"Stale": 16}


# ---- ストレージ ---------------------------------------------------------------------

def test_storage_switches_wal_database_back_to_rollback_journal(tmp_path):
    db_path = tmp_path / "papers.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    PaperStorage(db_path)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()


# ---- Excel入力 ----------------------------------------------------------------------

def test_excel_blank_cells_become_empty_strings_not_nan(tmp_path):
    excel_path = tmp_path / "journals.xlsx"
    _write_journals(excel_path, [
        {"Journal Title": " Journal A ", "Abbrev": None, "Publisher": "P ", "Journal URL": None,
         "RSS Feed": "—", "Online ISSN": "1234-5678\t", "Print ISSN": None, "Status": None,
         "ABDC": "A*", "ABS": 4},
        {"Journal Title": None},  # 空行は読み飛ばす
    ])
    journals = load_journals_from_excel(str(excel_path))
    assert len(journals) == 1
    j = journals[0]
    assert (j.name, j.abbreviation, j.publisher, j.journal_url, j.rss_url) == ("Journal A", "", "P", "", "")
    assert j.issns == ["1234-5678"]
    assert (j.abdc, j.abs_rank) == ("A*", "4")


# ---- HTML / 機械可読出力 ------------------------------------------------------------

def _paper(title, journal, fetched, doi, abstract=""):
    return Paper(title=title, journal_name=journal, authors=["A B"], doi=doi, url=f"https://doi.org/{doi}",
                 abstract=abstract, published_date=fetched, fetched_at=fetched)


def test_html_export_writes_ai_readable_files(tmp_path):
    config = _config(tmp_path, tmp_path / "unused.xlsx")
    config["html_export"]["site_url"] = "https://example.org/jt"
    exporter = HtmlExporter(config)
    generated = datetime(2026, 9, 24, 18, 0)
    journals = [
        Journal(name="J1", abbreviation="J1", journal_url="https://j1", abdc="A*", abs_rank="4"),
        Journal(name="J2", journal_url="https://j2"),
    ]
    papers = [
        _paper("New <i>paper</i>", "J1", generated - timedelta(days=1), "10.1/new", "<jats:p>Abs</jats:p>"),
        _paper("Older paper", "J1", generated - timedelta(days=20), "10.1/older"),
        _paper("Hidden paper", "J2", generated, "10.1/hidden"),
    ]
    failing = {"J2": {"error_type": "timeout_error"}}

    assert exporter.export(papers, journals=journals, failing_journals=failing, generated_at=generated)

    docs = tmp_path / "docs"
    html = (docs / "index.html").read_text(encoding="utf-8")
    assert 'href="latest.md"' in html and 'href="papers.json"' in html
    assert 'data-generated="2026-09-24"' in html
    assert "New paper" in html and "&lt;i&gt;" not in html
    assert "ABDC A*" in html and "<details" in html

    md = (docs / "latest.md").read_text(encoding="utf-8")
    assert "New paper" in md and "Older paper" not in md  # 直近7日のみ
    assert "## J1 (ABDC A* / ABS 4)" in md
    assert "Hidden paper" not in md and "J2" in md  # 長期エラー誌は論文を出さず注記のみ

    data = json.loads((docs / "papers.json").read_text(encoding="utf-8"))
    assert [p["title"] for p in data["papers"]] == ["New paper", "Older paper"]
    assert data["papers"][0]["abstract"] == "Abs"
    assert {j["name"]: j["status"] for j in data["journals"]} == {"J1": "ok", "J2": "failing"}

    llms = (docs / "llms.txt").read_text(encoding="utf-8")
    assert "https://example.org/jt/latest.md" in llms


def test_group_by_journal_hides_papers_of_failing_journal():
    exporter = HtmlExporter({})
    groups = exporter._group_by_journal(
        [_paper("P", "J", datetime.now(), "10.1/p")],
        all_journals=[Journal(name="J")],
        failing_journals={"J": {"error_type": "dns_error"}},
    )
    assert groups[0]["is_failing"] and groups[0]["papers"] == [] and groups[0]["count"] == 0
    assert groups[0]["error_reason"] == "提供元に接続できません"


# ---- main の終了コード・フロー -----------------------------------------------------

def _run_main(config: dict, tmp_path: Path, papers: list[Paper], argv_extra=()):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with patch("src.fetcher.CrossRefFetcher.fetch", return_value=papers), \
         patch("sys.argv", ["prog", "--config", str(config_path), *argv_extra]):
        return main()


def test_excel_failure_still_updates_html_and_returns_nonzero(tmp_path):
    excel_path = tmp_path / "journals.xlsx"
    _write_journals(excel_path, [{"Journal Title": "J", "Online ISSN": "1234-5678"}])
    config = _config(tmp_path, excel_path)
    paper = Paper(title="P", journal_name="J", doi="10.1/p")

    with patch("src.main.ExcelExporter.export", return_value=None):
        assert _run_main(config, tmp_path, [paper]) == 1
    assert "P" in (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    last_run = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert last_run["exit_code"] == 1 and last_run["inserted_count"] == 1


def test_main_excludes_non_research_items_and_ignores_removed_journals(tmp_path):
    excel_path = tmp_path / "journals.xlsx"
    _write_journals(excel_path, [{"Journal Title": "J", "Online ISSN": "1234-5678"}])
    config = _config(tmp_path, excel_path)

    # リストから外した誌 "Gone" が長期エラーのまま journal_status に残っているケース
    storage = PaperStorage(tmp_path / "papers.db")
    for _ in range(10):
        storage.update_journal_status(["Gone"], [{"journal": "Gone", "error_type": "timeout_error"}])

    papers = [
        Paper(title="Editorial Board", journal_name="J", doi="10.1/eb"),
        Paper(title="Real", journal_name="J", doi="10.1/real"),
    ]
    assert _run_main(config, tmp_path, papers) == 0

    conn = sqlite3.connect(tmp_path / "papers.db")
    try:
        titles = [r[0] for r in conn.execute("SELECT title FROM papers")]
    finally:
        conn.close()
    assert titles == ["Real"]
    data = json.loads((tmp_path / "docs" / "papers.json").read_text(encoding="utf-8"))
    assert [j["name"] for j in data["journals"]] == ["J"]


# ---- 現状把握レポート -----------------------------------------------------------------

def test_status_report_is_read_only_and_flags_problems(tmp_path):
    excel_path = tmp_path / "journals.xlsx"
    _write_journals(excel_path, [
        {"Journal Title": "Active", "Online ISSN": "1111-1111"},
        {"Journal Title": "Empty", "Online ISSN": "2222-2222"},
        {"Journal Title": "NoIssn"},
    ])
    config = _config(tmp_path, excel_path)
    storage = PaperStorage(tmp_path / "papers.db")
    storage.save_batch([
        Paper(title="Paper", journal_name="Active", doi="10.1/a"),
        Paper(title="Editorial Board", journal_name="Active", doi="10.1/eb"),
    ])
    db_file = tmp_path / "papers.db"
    before = hashlib.md5(db_file.read_bytes()).hexdigest()

    report = build_report(config)

    assert hashlib.md5(db_file.read_bytes()).hexdigest() == before  # DBを書き換えない
    assert report["database"]["papers_total"] == 2
    assert report["database"]["non_research_rows_in_db"] == 1
    flags = {j["name"]: j["flags"] for j in report["journals"]}
    assert flags["Active"] == []
    assert "no_papers_ever" in flags["Empty"]
    assert "no_issn" in flags["NoIssn"]
    assert any("Empty" in p for p in report["problems"])


# ---- ドキュメント整合性 ---------------------------------------------------------------

def test_readme_ranking_table_matches_journal_list():
    """README のランキング表（公開情報）と Excel の ABDC/ABS・誌名が一致していること"""
    import re

    root = Path(__file__).resolve().parent.parent
    readme_rows = {}
    for line in (root / "README.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| (.+?) \| (.+?) \| (.+?) \| (.+?) \| .+? \| .+? \|$", line.strip())
        if m and m.group(1) not in ("Journal Title",) and not m.group(1).startswith("---"):
            readme_rows[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    journals = load_journals_from_excel(str(root / "Accounting_Journals_URL_List.xlsx"))
    excel_rows = {j.name: (j.abbreviation, j.abdc, j.abs_rank) for j in journals}
    assert readme_rows == excel_rows


def test_self_check_and_reinit_do_not_modify_committed_database(tmp_path):
    """エージェントが --self-check を実行しても、git管理下のDBファイルに差分を出さない"""
    from src.main import run_self_check

    excel_path = tmp_path / "journals.xlsx"
    _write_journals(excel_path, [{"Journal Title": "J", "Online ISSN": "1234-5678"}])
    config = _config(tmp_path, excel_path)
    db_file = tmp_path / "papers.db"
    PaperStorage(db_file).save_batch([Paper(title="P", journal_name="J", doi="10.1/p")])
    before = hashlib.md5(db_file.read_bytes()).hexdigest()

    assert run_self_check(config) == []
    PaperStorage(db_file)  # 移行済みDBの再初期化も無変更
    assert hashlib.md5(db_file.read_bytes()).hexdigest() == before
