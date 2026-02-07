"""ユーティリティモジュール"""

from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .parser import Journal

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
        return yaml.safe_load(f)


def validate_journal_excel(excel_path: str) -> None:
    """ジャーナルExcelの存在と必須列を検証"""
    resolved_path = resolve_path(excel_path)
    if not resolved_path.exists():
        raise FileNotFoundError(f"Excel file not found: {resolved_path}")

    header_df = pd.read_excel(resolved_path, nrows=0)
    missing = [col for col in REQUIRED_JOURNAL_COLUMNS if col not in header_df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")


def load_journals_from_excel(excel_path: str) -> list[Journal]:
    """Excelファイルからジャーナルリストを読み込む"""
    validate_journal_excel(excel_path)

    resolved_path = resolve_path(excel_path)
    df = pd.read_excel(resolved_path)

    journals = []
    for _, row in df.iterrows():
        rss_url = str(row.get("RSS Feed", "")) if pd.notna(row.get("RSS Feed")) else ""

        online_issn = str(row.get("Online ISSN", "")) if pd.notna(row.get("Online ISSN")) else ""
        print_issn = str(row.get("Print ISSN", "")) if pd.notna(row.get("Print ISSN")) else ""
        issn = online_issn if online_issn else print_issn

        journal = Journal(
            name=str(row.get("Journal Title", "")),
            abbreviation=str(row.get("Abbrev", "")),
            publisher=str(row.get("Publisher", "")),
            journal_url=str(row.get("Journal URL", "")),
            rss_url=rss_url if rss_url != "-" else "",
            issn=issn,
            status=str(row.get("Status", "")),
        )
        journals.append(journal)

    return journals


def ensure_data_dir(config: dict) -> Path:
    """データディレクトリを確保"""
    db_path = resolve_path(config.get("database", {}).get("path", "data/papers.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path
