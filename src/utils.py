"""ユーティリティモジュール"""

import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .parser import Journal, compile_title_patterns

REQUIRED_JOURNAL_COLUMNS = [
    "Journal Title",
    "Abbrev",
    "Publisher",
    "Journal URL",
    "RSS Feed",
    "Online ISSN",
    "Print ISSN",
    "Status",
]


def get_project_root() -> Path:
    """プロジェクトルートディレクトリを取得"""
    return Path(__file__).parent.parent


def resolve_path(path: str | Path) -> Path:
    """相対パスをプロジェクトルートからの絶対パスに解決"""
    path = Path(path)
    if path.is_absolute():
        return path
    return get_project_root() / path


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """設定ファイルを読み込む"""
    if config_path is None:
        config_path = get_project_root() / "config" / "config.yaml"

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_journal_excel(excel_path: str) -> None:
    """ジャーナルExcelの存在と必須列を検証"""
    resolved_path = resolve_path(excel_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Excel file not found: {resolved_path}")

    header_df = pd.read_excel(resolved_path, nrows=0)
    missing = [col for col in REQUIRED_JOURNAL_COLUMNS if col not in header_df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def _cell(row: pd.Series, column: str) -> str:
    """Excelセルを文字列で取得（空セル/NaN/列なしは空文字、前後の空白・タブは除去）。

    素朴に str() すると空セルが "nan" になり、HTMLに href="nan" のリンクが出るため。
    """
    value = row.get(column)
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def load_journals_from_excel(excel_path: str) -> list[Journal]:
    """Excelファイルからジャーナルリストを読み込む"""
    validate_journal_excel(excel_path)

    resolved_path = resolve_path(excel_path)
    df = pd.read_excel(resolved_path)

    journals = []
    for _, row in df.iterrows():
        # ISSNは取得クエリのキー。Excel由来の前後空白・タブ（例: "1879-0585\t"）を除去する。
        # CrossRefフィルタに混入すると当該誌が丸ごと取得不能になるため。
        online_issn = _cell(row, "Online ISSN")
        print_issn = _cell(row, "Print ISSN")
        rss_url = _cell(row, "RSS Feed")

        journal = Journal(
            name=_cell(row, "Journal Title"),
            abbreviation=_cell(row, "Abbrev"),
            publisher=_cell(row, "Publisher"),
            journal_url=_cell(row, "Journal URL"),
            rss_url=rss_url if rss_url not in ("-", "—") else "",
            issn=online_issn or print_issn,
            issn_print=print_issn,  # Online と Print 双方を取得時にORで併用（fetcher）
            status=_cell(row, "Status"),
            abdc=_cell(row, "ABDC"),        # 任意列（無ければ空）
            abs_rank=_cell(row, "ABS"),     # 任意列（無ければ空）
        )
        if not journal.name:
            continue  # 空行
        journals.append(journal)

    return journals


def ensure_data_dir(config: dict) -> Path:
    """データディレクトリを確保"""
    db_path = resolve_path(config.get("database", {}).get("path", "data/papers.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def load_title_exclusions(config: dict) -> list[re.Pattern]:
    """論文以外の項目（Editorial Board 等）を除外するタイトル正規表現を設定から読み込む"""
    return compile_title_patterns(config.get("filter", {}).get("exclude_title_patterns", []))
