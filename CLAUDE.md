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

回帰テストは `tests/test_regressions.py`（pytest形式）にあります。`pip install pytest` 後
`python -m pytest tests/` で実行してください。動作確認には `--dry-run` も利用できます。

## アーキテクチャ

### データフロー

```
Excelジャーナルリスト → PaperFetcher (CrossRef API) → PaperStorage (SQLite重複チェック) → ExcelExporter → output/new_papers_YYYYMMDD.xlsx
```

### コアモジュール

| モジュール | 役割 |
|-----------|------|
| `src/main.py` | CLIエントリーポイント・オーケストレーション |
| `src/fetcher.py` | `CrossRefFetcher`, `PaperFetcher` - 論文取得（CrossRef API） |
| `src/parser.py` | `Paper`, `Journal` データクラス |
| `src/storage.py` | SQLite永続化・重複チェック |
| `src/exporter.py` | Excel出力 |
| `src/html_exporter.py` | `HtmlExporter` - GitHub Pages用HTML出力（Jinja2テンプレート） |
| `src/utils.py` | 設定読み込み (`load_config`)・ジャーナルリスト解析 (`load_journals_from_excel`) |

## 重要な実装詳細

### 論文の一意識別 (unique_id)

DOIがあればDOIを使用。なければ `"{title}:{journal_name}"` のMD5ハッシュ。

### フェッチャー選択ロジック (`PaperFetcher.fetch_all()`)

全ジャーナルを **CrossRef API（`CrossRefFetcher`）で取得**する。

1. ISSN（Online/Printいずれか）あり → `CrossRefFetcher`
2. それ以外 → スキップ（警告ログ）

取得クエリには **Online/Print 両ISSNを併記**する（`Journal.issns`、Online優先・重複除去）。
CrossRefは works の `issn:` フィルタを同名指定でORするため、works が一方のISSNにしか
紐づかない誌でも取りこぼさない。詳細は下記「CrossRef APIクエリ」。

> 以前は「RSSフィードあり & Status='Working' → RSSフィード、無ければCrossRef」のハイブリッド
> だったが、RSSはpublisherのbot対策・エンコーディング宣言不一致・不正XMLで「丸ごと0件」になりやすく
> 保守コストが高い一方、対象（会計トップ誌）は全誌がISSNを持ちCrossRefで網羅でき、デポジット・ラグも
> 中央値0〜数日とRSSと同等以上に速いため、CrossRefへ一本化した（`feedparser` 依存も撤去）。
> Excelの "RSS Feed" / "Status" 列と`Journal.rss_url` / `Journal.status` は互換のため残しているが未使用。

### 「直近N日」フィルタリング基準

HTML出力（GitHub Pages）のスライダーUIによる「直近N日」フィルタは、`published_date`（出版日）ではなく **`fetched_at`（DB登録日）** を基準にしている。
CrossRef APIの日付が `YYYY/MM` のみ（日が欠落）の場合、`day=1` にデフォルト設定されるため、`published_date` 基準では同月の論文が1日に集中し件数が不正確になる問題を回避するため。

- バックエンド（`storage.get_recent_papers()`）: `fetched_at` 基準でDBから取得
- フロントエンド（`templates/index.html` の `filterByDays()`）: `data-fetched` 属性（`fetched_at`）基準でフィルタ
- 表示上の出版日（`YYYY/MM/DD`）は従来通り `published_date` を使用

### バックカタログ再登録ガード (`max_publication_lag_days`)

取得フィルタを `from-created-date`（初回デポジット日・固定）にしたことで、**既存DOIの再デポジット**
（被引用数更新・メタデータ修正）で古い論文が新着扱いされる流入は取得段階で根治した。
ただし、新規参入ジャーナルがアーカイブ全体を**新規DOI**でバックフィルする場合は `created=今日` となり
依然すり抜けうる。その防御として `get_recent_papers(max_publication_lag_days=...)` で
**`fetched_at - published_date` が閾値（既定60日）を超える論文を新着から除外**する（二重防御）。
月のみ日付(`YYYY-MM`→1日扱い)の正規の新着は公表日と取得日が近いため残る。`published_date` が無い論文は除外しない。

> 旧 `from-index-date` 運用時に流入・蓄積した過去分（DB内）は、一度きりの保守スクリプト
> `scripts/prune_backcatalog.py`（同じ閾値判定）で整理済み。

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

# 汎用worksエンドポイント + ISSNフィルタ(Online/Print併記=OR) + 初回デポジット日(created-date)フィルタ
GET https://api.crossref.org/works
    ?filter=issn:{online_issn},issn:{print_issn},from-created-date:{today-days_back}
    &rows=100&sort=created&order=desc
```

- ジャーナル別エンドポイント（`/journals/{issn}/works`）は **ISSNがCrossRefの代表ISSNと一致しないと404** に
  なるため使わない。`/works?filter=issn:` はprint/onlineどちらのISSNでもヒットし404にならない。
- ISSNは **Online/Print 両方を `issn:` で併記**する（`Journal.issns`）。**CrossRefは同名フィルタをOR、
  別名フィルタをANDで解釈する**ため、`(online OR print) AND from-created-date` となる。
  publisherによっては works が一方のISSN（Elsevier等は **Print ISSN** にのみ）紐づき、Online ISSN単独だと
  `total-results=0` で**丸ごと取りこぼす**。両併記でこれを根治した。
  - 逆に、ExcelのISSNが**別誌のもの**だとORで別誌論文が混入する。Excelの全ISSNの妥当性は
    `python -m scripts.diagnose_issn`（CrossRef照会・誌名一致チェック）で点検でき、`run_self_check` も
    全ISSNの取り違え（同一ISSNを複数誌が保持）を検知する。
- フィルタは **`from-created-date`（CrossRefへの初回デポジット日基準）**。
  - `from-pub-date`（出版日基準）だと、月のみ日付（`YYYY-MM` → `day=1`）の論文が登録遅延でローリング窓を
    外れて**恒久的に取りこぼされる**。
  - `from-index-date`（最終インデックス日基準）だと、既存DOIの再デポジットや被引用数更新でindex日が動き、
    **古い論文が新着として大量流入する**（例: 2026-06-14に2005〜2024年の論文が500件超）。
  - `from-created-date` は初回登録時にシステムが付与し以後固定されるため、新着検知が純粋で再インデックスの
    影響を受けない。新着論文は初回デポジット時点では `created≈index` なので取りこぼさず、「直近N日」フィルタが
    `fetched_at` 基準である設計（下記）とも整合する。`sort=created` で新しい順に取得する。

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
