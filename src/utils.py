"""ユーティリティモジュール"""

import os
from pathlib import Path
import yaml
import pandas as pd
from typing import Any

from .parser import Journal


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


def load_journals_from_excel(excel_path: str) -> list[Journal]:
    """Excelファイルからジャーナルリストを読み込む"""
    resolved_path = resolve_path(excel_path)
    df = pd.read_excel(resolved_path)

    journals = []
    for _, row in df.iterrows():
        rss_url = str(row.get("RSS Feed", "")) if pd.notna(row.get("RSS Feed")) else ""

        # ISSN取得（Online ISSNを優先、なければPrint ISSN）
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
