# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**Journal Tracker** は、会計のトップジャーナル（The Accounting Review, Journal of Accounting Research 等）から新着論文を自動取得し、Excelに出力するPython CLIツールです。Python 3.10以上が必要です（型ヒントに `|` 演算子を使用）。

## 主要コマンド

すべてのコマンドはリポジトリルートから実行してください。

```bash
# 依存パッケージのインストール
pip install -r requirements.txt

# 標準実行
python -m src.main

# テスト実行（Excel出力なし）
python -m src.main --dry-run

# 統計情報表示
python -m src.main --stats

# ジャーナル一覧表示
python -m src.main --list-journals

# カスタム設定ファイル指定
python -m src.main --config path/to/config.yaml

# Windows実行（文字コード対応）
run_tracker.bat
```

テストフレームワークは未導入です。`--dry-run` で動作確認してください。

## アーキテクチャ

### データフロー

```
Excelジャーナルリスト → PaperFetcher (RSS/CrossRef) → PaperStorage (SQLite重複チェック) → ExcelExporter → output/new_papers_YYYYMMDD.xlsx
```

### コアモジュール

| モジュール | 役割 |
|-----------|------|
| `src/main.py` | CLIエントリーポイント・オーケストレーション |
| `src/fetcher.py` | `RSSFetcher`, `CrossRefFetcher`, `PaperFetcher` - 論文取得 |
| `src/parser.py` | `Paper`, `Journal` データクラス |
| `src/storage.py` | SQLite永続化・重複チェック |
| `src/exporter.py` | Excel出力・HTMLからのメタデータ正規表現抽出 |
| `src/html_exporter.py` | `HtmlExporter` - GitHub Pages用HTML出力（Jinja2テンプレート） |
| `src/utils.py` | 設定読み込み (`load_config`)・ジャーナルリスト解析 (`load_journals_from_excel`) |

## 重要な実装詳細

### 論文の一意識別 (unique_id)

DOIがあればDOIを使用。なければ `"{title}:{journal_name}"` のMD5ハッシュ。

### フェッチャー選択ロジック (`PaperFetcher.fetch_all()`)

1. RSSフィードあり & Status="Working" → `RSSFetcher`
2. ISSNあり → `CrossRefFetcher`
3. それ以外 → スキップ（警告ログ）

### 抽象からのメタデータ抽出 (`exporter.py`)

一部のRSSフィードは構造化フィールドではなくHTML抽象にメタデータを埋め込むため、正規表現で抽出：
- 著者: `Author\(s\):\s*([^<\n]+)`
- 発行日: `Publication date:\s*([A-Za-z]+\s*\d{4})`

### 「直近N日」フィルタリング基準

HTML出力（GitHub Pages）のスライダーUIによる「直近N日」フィルタは、`published_date`（出版日）ではなく **`fetched_at`（DB登録日）** を基準にしている。
CrossRef APIの日付が `YYYY/MM` のみ（日が欠落）の場合、`day=1` にデフォルト設定されるため、`published_date` 基準では同月の論文が1日に集中し件数が不正確になる問題を回避するため。

- バックエンド（`storage.get_recent_papers()`）: `fetched_at` 基準でDBから取得
- フロントエンド（`templates/index.html` の `filterByDays()`）: `data-fetched` 属性（`fetched_at`）基準でフィルタ
- 表示上の出版日（`YYYY/MM/DD`）は従来通り `published_date` を使用

### レート制限

ジャーナル間で `time.sleep(1)` を挿入。APIレート制限とサーバー負荷軽減のため。

### CrossRef APIヘッダー

```python
headers = {"User-Agent": "JournalTracker/1.0 (mailto:your@email.com)"}
```

## 環境変数

`.env.example` を `.env` にコピーして使用。CrossRef APIの優遇レート制限を受けるためのメールアドレスを設定。

## 設定 (`config/config.yaml`)

| キー | 説明 | デフォルト |
|------|------|-----------|
| `fetch.days_back` | 何日前まで取得するか | 7 |
| `fetch.timeout` | HTTPタイムアウト（秒） | 30 |
| `database.path` | SQLiteパス | `data/papers.db` |
| `export.output_dir` | Excel出力先 | `output` |
| `html_export.output_dir` | HTML出力先（GitHub Pages） | `docs` |
| `html_export.template_dir` | Jinja2テンプレートフォルダ | `templates` |
| `html_export.days_back` | デフォルト表示日数 | 7 |
| `html_export.selectable_days_range` | スライダーUI範囲 | `[1, 30]` |
| `journals.excel_path` | ジャーナルリスト | `Accounting_Journals_URL_List.xlsx` |

## データベーススキーマ

```sql
CREATE TABLE papers (
    unique_id TEXT PRIMARY KEY,  -- DOI or title hash
    title TEXT,
    journal_name TEXT,
    authors TEXT,
    abstract TEXT,
    doi TEXT,
    url TEXT,
    published_date TEXT,  -- ISO format
    fetched_at TEXT,
    notified INTEGER DEFAULT 0
);
-- インデックス: journal_name, fetched_at
```

## GitHub Actions

`.github/workflows/update-pages.yml` で毎日 UTC 9:00（JST 18:00）に自動実行。
`docs/index.html` と `data/papers.db` を更新してコミット・プッシュする。手動実行（`workflow_dispatch`）にも対応。

## 日本語コンテキスト

コードベースは日本語コメント・ログメッセージを含みます：
- 新着 (new/recent)
- 既読 (already read)
- 取得 (fetch/retrieve)
