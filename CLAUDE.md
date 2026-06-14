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

### RSS取得の堅牢化 (`RSSFetcher`)

`feedparser.parse(url)` にURLを直接渡すと、publisherのbot対策・エンコーディング宣言不一致
（例: `declared as us-ascii, but parsed as utf-8`）・不正トークン（裸の `&` 等）でパースが壊れ、
`feed.entries` が空になり**ジャーナル丸ごと0件**になる（Taylor & Francis / Springer / Oxford 等）。
対策として **`requests`（ブラウザ風User-Agent + リトライ）で生バイトを取得 → デコード → `sanitize_feed_text()`
で緩く修復してから `feedparser.parse()` に文字列を渡す** 方式にしている。
サニタイズしても解釈できない場合は `last_error_type="rss_parse_error"` を立て、`failed_journals`
（run report）に載せて可視化する。

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

### バックカタログ再登録ガード (`max_publication_lag_days`)

`fetched_at` 基準のみだと、publisherがCrossRefに**過去論文のメタデータを再デポジット**した際、
それらが新しい登録日(index-date)を得て `from-index-date` フィルタを通過し、`fetched_at=今日` でDB登録され、
**数年前の論文が「直近1日」に大量流入する**（例: 2026-06-14に2005〜2024年の論文が500件超）。
対策として `get_recent_papers(max_publication_lag_days=...)` で
**`fetched_at - published_date` が閾値（既定60日）を超える論文＝バックカタログ再登録を新着から除外**する。
月のみ日付(`YYYY-MM`→1日扱い)の正規の新着は公表日と取得日が近いため残る。`published_date` が無い論文は除外しない。

### 長期エラー誌の表示 (`journal_status` / `get_failing_journals`)

長期間エラーで論文を取得できていないジャーナルは、「新着なし」と誤解されないよう、
論文欄を出さず **Journal名 + HPリンク + 注意書き** のみを表示する。
- `journal_status` テーブルにジャーナル別の取得成否（`last_success_at` / `consecutive_failures` / `last_error_type` 等）を毎回記録（`storage.update_journal_status()`、dry-runでは更新しない）。
- 判定（`storage.get_failing_journals(threshold)`、既定7）: **連続失敗が閾値以上**、または **直近の取得が失敗(連続失敗≥1)していて、最後の取得成功（`last_success_at`、無ければ `papers` の最新 `fetched_at` を代用）から閾値日数以上経過**。
  後者の代用により、`journal_status` の履歴が無い導入直後でも次回実行から即座に検知できる。
- フロント（`templates/index.html`）: 該当セクションに `data-journal-error` を付与し、`filterByDays()` の日数フィルタ対象外にする。

### レート制限

ジャーナル間で `time.sleep(1)` を挿入。APIレート制限とサーバー負荷軽減のため。

### CrossRef APIクエリ (`CrossRefFetcher.fetch()`)

```python
headers = {"User-Agent": "JournalTracker/1.0 (mailto:your@email.com)"}

# 汎用worksエンドポイント + ISSNフィルタ + 登録日(index-date)フィルタ
GET https://api.crossref.org/works
    ?filter=issn:{issn},from-index-date:{today-days_back}
    &rows=100&sort=indexed&order=desc
```

- ジャーナル別エンドポイント（`/journals/{issn}/works`）は **ISSNがCrossRefの代表ISSNと一致しないと404** に
  なるため使わない。`/works?filter=issn:` はprint/onlineどちらのISSNでもヒットし404にならない。
- フィルタは **`from-index-date`（CrossRef登録日基準）**。`from-pub-date`（出版日基準）だと、月のみ日付
  （`YYYY-MM` → `day=1`）の論文が登録遅延でローリング窓を外れて**恒久的に取りこぼされる**ため。
  これは「直近N日」フィルタが `fetched_at` 基準である設計（下記）とも整合する。

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
| `html_export.max_publication_lag_days` | これ以上前に公表された論文は新着扱いしない（バックカタログ再登録対策） | 60 |
| `html_export.failure_threshold` | 連続失敗がこの回数以上で「長期エラー」表示（毎日実行のため回数≒日数） | 7 |
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

CREATE TABLE journal_status (        -- 長期エラー検知用（ジャーナル別の取得成否）
    journal_name TEXT PRIMARY KEY,
    last_success_at TEXT,
    last_error_at TEXT,
    last_error_type TEXT,
    consecutive_failures INTEGER DEFAULT 0,
    updated_at TEXT
);
```

## GitHub Actions

`.github/workflows/update-pages.yml` で毎日 UTC 9:00（JST 18:00）に自動実行。
`docs/index.html` と `data/papers.db` を更新してコミット・プッシュする。手動実行（`workflow_dispatch`）にも対応。

## 日本語コンテキスト

コードベースは日本語コメント・ログメッセージを含みます：
- 新着 (new/recent)
- 既読 (already read)
- 取得 (fetch/retrieve)
