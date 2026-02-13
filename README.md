# Journal Tracker

会計・ファイナンスのトップジャーナルから新着論文を自動取得し、Excel・HTMLに出力するツールです。
GitHub Actionsによる日次自動更新に対応しています。

**URL**: https://shimi-toshi.github.io/journal-tracker/

> **免責事項**: 本ページの情報は最終更新日時点で最新かつ正確な内容を掲載するよう努めていますが、誤りが含まれる可能性があります。ご利用の際は、必ず一次情報をご確認ください。
>
> **最終更新日**: 2026年2月7日

## 対象ジャーナル・ランキング一覧

本ツールが対象とするジャーナルとその主要ランキングの一覧です。

> **ランキング凡例**
> - **ABDC**: Australian Business Deans Council Journal Quality List (A*, A, B, C)
> - **ABS**: Chartered Association of Business Schools Academic Journal Guide (4*, 4, 3, 2, 1)
> - **SJR-Accounting**: SCImago Journal Rank - Accounting カテゴリ (Q1–Q4)
> - **SJR-Finance**: SCImago Journal Rank - Finance カテゴリ (Q1–Q4)

### Accounting Journals

| Journal Title | Abbrev | ABDC | ABS | SJR-Accounting | SJR-Finance |
|---|---|---|---|---|---|
| Accounting, Organizations and Society | AOS | A* | 4* | Q1 | - |
| Journal of Accounting and Economics | JAE | A* | 4* | Q1 | Q1 |
| Journal of Accounting Research | JAR | A* | 4* | Q1 | Q1 |
| The Accounting Review | TAR | A* | 4* | Q1 | Q1 |
| Contemporary Accounting Research | CAR | A* | 4 | Q1 | Q1 |
| Review of Accounting Studies | RAST | A* | 4 | Q1 | - |
| Accounting Auditing and Accountability Journal | AAAJ | A* | 3 | Q1 | - |
| Auditing: A Journal of Practice and Theory | AJPT | A* | 3 | Q1 | Q1 |
| British Accounting Review | BAR | A* | 3 | Q1 | - |
| Journal of Business Finance & Accounting | JBFA | A* | 3 | Q1 | Q1 |
| Management Accounting Research | MAR | A* | 3 | Q1 | Q1 |
| The European Accounting Review | EAR | A* | 3 | Q1 | Q1 |
| Journal of Accounting and Public Policy | JAPP | A* | 3 | Q1 | - |
| Abacus | Abacus | A | 3 | Q3 | - |
| Accounting and Business Research | ABR | A | 3 | Q2 | Q2 |
| Accounting Horizons | AH | A | 3 | Q1 | - |
| Behavioral Research in Accounting | BRIA | A | 3 | Q2 | - |
| Critical Perspectives on Accounting | CPA | A | 3 | Q1 | Q1 |
| Financial Accountability and Management | FAM | A | 3 | Q1 | Q1 |
| Foundations and Trends in Accounting | FTA | A | 3 | Q1 | Q1 |
| Journal of Accounting Auditing and Finance | JAAF | A | 3 | Q2 | Q2 |
| Journal of Accounting Literature | JAL | A | 3 | Q3 | - |
| Journal of Financial Reporting | JFR | A | 3 | - | - |
| The International Journal of Accounting | TIJA | A | 3 | Q3 | Q2 |
| Accounting Forum | AF | B | 3 | Q2 | Q1 |
| Journal of International Accounting, Auditing and Taxation | JIAAT | B | 3 | Q2 | Q2 |
| Journal of Management Accounting Research | JMAR | A* | 2 | Q1 | - |
| Accounting and Finance | A&F | A | 2 | Q2 | Q2 |
| Accounting in Europe | AIE | A | 2 | Q2 | Q1 |
| Advances in Accounting | AiA | A | 2 | Q3 | Q2 |
| Advances in Accounting Behavioral Research | AABR | A | 2 | - | - |
| Advances in Management Accounting | AMA | A | 2 | - | - |
| International Journal of Accounting Information Systems | IJAIS | A | 2 | Q1 | Q1 |
| International Journal of Auditing | IJA | A | 2 | Q2 | - |
| Journal of Contemporary Accounting and Economics | JCAE | A | 2 | Q2 | - |
| Journal of International Accounting Research | JIAR | A | 2 | Q3 | - |
| Journal of Management Control | JMC | A | 2 | Q2 | - |
| Managerial Auditing Journal | MAJ | A | 2 | Q2 | - |
| Qualitative Research in Accounting and Management | QRAM | A | 2 | Q2 | - |
| Accounting and the Public Interest | API | B | 2 | Q4 | - |
| Accounting Research Journal | ARJ | B | 2 | Q3 | Q2 |
| Accounting, Economics and Law: A Convivium | AEL | B | 2 | Q2 | - |
| Asia-Pacific Journal of Accounting and Economics | APJAE | B | 2 | Q3 | Q3 |
| Asian Review of Accounting | ARA | B | 2 | Q3 | Q2 |
| Australian Accounting Review | AAR | B | 2 | Q2 | - |
| China Journal of Accounting Research | CJAR | B | 2 | Q2 | Q2 |
| Current Issues in Auditing | CIA | B | 2 | Q3 | - |
| International Journal of Accounting and Information Management | IJAIM | B | 2 | Q1 | - |
| International Journal of Disclosure and Governance | IJDG | B | 2 | Q2 | Q2 |
| International Journal of Managerial and Financial Accounting | IJMFA | B | 2 | Q3 | - |
| Journal of Accounting & Organizational Change | JAOC | B | 2 | Q2 | - |
| Journal of Accounting in Emerging Economies | JAEE | B | 2 | Q2 | - |
| Journal of Applied Accounting Research | JAAR | B | 2 | Q2 | - |
| Journal of Forensic Accounting Research | JFAR | B | 2 | - | - |
| Journal of Public Budgeting, Accounting and Financial Management | JPBAFM | B | 2 | - | Q2 |
| Sustainability Accounting, Management and Policy Journal | SAMPJ | B | 2 | Q1 | - |

### Finance Journals

| Journal Title | Abbrev | ABDC | ABS | SJR-Accounting | SJR-Finance |
|---|---|---|---|---|---|
| Journal of Finance | JF | A* | 4* | Q1 | Q1 |
| Journal of Financial Economics | JFE | A* | 4* | Q1 | Q1 |
| Review of Financial Studies | RFS | A* | 4 | Q1 | Q1 |
| Journal of Financial and Quantitative Analysis | JFQA | A* | 4 | Q1 | Q1 |
| Review of Finance | RF | A* | 3 | Q1 | Q1 |
| Journal of Corporate Finance | JCF | A* | 3 | - | Q1 |
| Journal of Banking and Finance | JBF | A* | 3 | - | Q1 |
| Financial Analysts Journal | FAJ | A | 3 | Q1 | Q1 |
| Pacific Basin Finance Journal | PBFJ | A | 2 | - | Q1 |
| Journal of the Japanese and International Economies | JJIE | A | 2 | - | Q1 |
| Finance Research Letters | FRL | A | 2 | - | Q1 |

## 機能

- **RSS/CrossRef対応**: RSSフィードまたはCrossRef APIから論文情報を取得
- **重複チェック**: SQLiteデータベースで既読管理し、新着論文のみを出力
- **Excel出力**: ジャーナル名、発行日、タイトル、著者、DOI、URLを一覧化
- **HTML出力**: GitHub Pages用のHTML一覧ページを生成（日数スライダーUI付き、DB登録日基準でフィルタ）
- **日次自動更新**: GitHub Actionsで毎日自動実行し、GitHub Pagesを更新

## セットアップ

### 必要環境

- Python 3.10以上

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/shimi-toshi/journal-tracker.git
cd journal-tracker

# 依存パッケージをインストール
pip install -r requirements.txt
```

### 環境変数（任意）

`.env.example` を `.env` にコピーし、CrossRef APIの優遇レート制限を受けるためにメールアドレスを設定できます。設定しなくても動作しますが、設定するとCrossRef APIのレスポンスが速くなります。

```bash
cp .env.example .env
# .env を編集してメールアドレスを設定
```

### 設定

`config/config.yaml` を環境に合わせて編集してください。

```yaml
export:
  output_dir: "output"            # Excel出力先

html_export:
  output_dir: "docs"              # HTML出力先（GitHub Pages用）
  template_dir: "templates"       # Jinja2テンプレートフォルダ
  days_back: 7                    # デフォルト表示日数
  selectable_days_range: [1, 30]  # スライダーUIの範囲

database:
  path: "data/papers.db"          # SQLiteデータベース

journals:
  excel_path: "Accounting_Journals_URL_List.xlsx"  # ジャーナルリスト

fetch:
  days_back: 7                    # 何日前までの論文を取得するか
  timeout: 30                     # HTTPタイムアウト（秒）
  rate_limit_seconds: 1.0         # ジャーナル間の待機秒（0で無効）
```

## 使い方

### 基本実行

```bash
python -m src.main
```

### オプション

| オプション | 説明 |
|-----------|------|
| `--dry-run` | テスト実行（Excel・HTML出力なし） |
| `--stats` | 統計情報を表示 |
| `--list-journals` | ジャーナル一覧を表示 |
| `--config <path>` | 設定ファイルを指定 |
| `--self-check` | 設定・Excel・DB・テンプレートの自己診断を実施 |

### Windows での実行

`run_tracker.bat` をダブルクリック、またはコマンドプロンプトから実行してください。

## ディレクトリ構成

```
journal-tracker/
├── src/
│   ├── main.py           # メインエントリーポイント
│   ├── fetcher.py        # 論文取得（RSS/CrossRef）
│   ├── parser.py         # データクラス定義
│   ├── storage.py        # SQLite既読管理
│   ├── exporter.py       # Excel出力
│   ├── html_exporter.py  # HTML出力（GitHub Pages用）
│   └── utils.py          # ユーティリティ
├── config/
│   └── config.yaml       # 設定ファイル
├── templates/
│   └── index.html        # HTML出力用Jinja2テンプレート
├── docs/                 # GitHub Pages公開ディレクトリ
├── data/                 # SQLiteデータベース
├── output/               # Excel出力先
├── logs/                 # ログ出力先
├── .github/workflows/
│   └── update-pages.yml  # GitHub Actions定期実行
├── Accounting_Journals_URL_List.xlsx  # ジャーナルリスト
├── .env.example          # 環境変数テンプレート
├── requirements.txt
└── run_tracker.bat       # Windows実行用
```

## ジャーナルリスト

`Accounting_Journals_URL_List.xlsx` には以下の列が必要です：

| 列名 | 説明 |
|------|------|
| Journal Title | ジャーナル名 |
| Abbrev | 略称 |
| Publisher | 出版社 |
| Journal URL | ジャーナルのURL |
| RSS Feed | RSSフィードURL（なければ「-」） |
| Online ISSN | オンラインISSN |
| Print ISSN | 印刷版ISSN |
| Status | 「Working」でRSS有効 |

## 出力形式

### Excel出力

新着論文は `output/new_papers_YYYYMMDD.xlsx` として出力されます。

| 列 | 内容 |
|----|------|
| Journal | ジャーナル名 |
| Published | 発行日 (YYYY/MM) |
| Title | 論文タイトル |
| Authors | 著者 |
| DOI | DOI |
| URL | 論文URL |

### HTML出力

`docs/index.html` にジャーナル別の論文一覧HTMLが生成されます。GitHub Pagesで公開可能です。
スライダーUIで表示期間を変更できます。フィルタはDB登録日（`fetched_at`）基準で行われます（出版日が月単位のみの論文でも正確にカウントされます）。


## 重複検知・DB移行に関する実装メモ（LLM/開発者向け）

以下は 2026-02 の優先改善で導入した仕様です。後続のLLMや開発者が修正しやすいよう、運用ルールを明記します。

1. **DOI正規化の単一責務**
   - 実装は `src/parser.py` の `normalize_doi()` に集約。
   - `Paper.unique_id` と `PaperStorage.save_batch()` の両方がこの関数を利用。
   - DOIが空（または `doi:` のように正規化後空）なら、`title + journal_name` 正規化ハッシュへフォールバック。

2. **SQLiteスキーマ拡張と自動移行**
   - `papers` テーブルに `normalized_doi` カラムを保持。
   - `metadata` テーブルで `schema_version` を管理し、必要な移行のみ実行する（毎回全件移行しない）。
   - バックフィル時は `normalized_doi` が空の行だけを対象にする。
   - 同一DOIが複数行ある場合、先頭行のみ `normalized_doi` を埋め、残りは空のまま（履歴保全優先）。

3. **DB制約による重複防止**
   - `normalized_doi` に部分ユニークインデックス（NULL/空は除外）を設定。
   - 保存処理は `INSERT OR IGNORE` を使用し、アプリ側の二重チェックを簡素化。
   - 事前判定 `is_new()` も `unique_id` と `normalized_doi` の両方を評価し、保存結果と整合するようにする。

4. **CrossRef通信の回復性**
   - `CrossRefFetcher` は `requests.Session` + `Retry` を使用し、`429/5xx` を自動リトライ。
   - `Retry-After` を尊重してバックオフする。

### 変更時の注意
- DOI関連ロジックを変更する場合は、`src/parser.py` と `src/storage.py` の両方を確認する。
- スキーマ変更を入れる場合は、`PaperStorage._init_db()` の `schema_version` を更新し、**後方互換マイグレーション**を追加する。
- 回帰防止として `tests/test_regressions.py` を更新する。

## GitHub Actions（自動更新）

`.github/workflows/update-pages.yml` により、毎日 UTC 9:00（JST 18:00）に自動実行されます。
手動実行（`workflow_dispatch`）にも対応しています。

## 全体エラーの検討メモ（運用チェック観点）

最新の回帰テストとCLI確認の観点では、致命的な例外で処理全体が停止する経路は限定的です。

- 単体/回帰テスト（`tests/test_regressions.py`）で、DOI正規化・DB移行・重複判定・CrossRef日付フォールバックの主要経路をカバー。
- `python -m src.main --list-journals` はローカル環境で正常終了することを確認。
- `python -m src.main --dry-run` は、ネットワーク制限下でも個別フェッチ失敗をログ出力しつつ継続可能（`main()` 全体が即時クラッシュしない）。

### 実装済みの改善（2026-02 追加）

1. **取得品質の可視化**
   - 実行終了時に `logs/run_report_*.json` を出力し、`fetched_count`, `inserted_count`, `failed_journals`, `skipped_journals`, `duration_sec` を保存。

2. **接続エラー種別ごとの分類**
   - CrossRefの通信例外を `http_auth_error`, `http_server_error`, `proxy_error`, `dns_error`, `tls_error` などに分類してログ出力。
   - リトライは `429/5xx` のHTTPステータスに限定（接続エラーの無駄リトライを抑制）。

3. **CLI自己診断モード**
   - `--self-check` で、設定読込・ジャーナルExcel必須列・DB初期化/移行・HTMLテンプレート存在/構文に加えて、出力ディレクトリ（Excel/HTML/ログ）の書き込み可否を事前確認。

4. **統合テスト（疑似レスポンス）**
   - `requests` モックを用いた最小統合テストを追加し、`PaperFetcher -> PaperStorage` の結合経路を検証。

5. **DB健全性チェックSQLの標準化**
   - 以下のSQLを定期確認用として運用する。

```sql
-- 1) normalized_doi 重複疑い（本来0件）
SELECT normalized_doi, COUNT(*) AS c
FROM papers
WHERE normalized_doi IS NOT NULL AND normalized_doi <> ''
GROUP BY normalized_doi
HAVING c > 1;

-- 2) published_date 欠損率
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN published_date IS NULL OR published_date = '' THEN 1 ELSE 0 END) AS missing,
  ROUND(100.0 * SUM(CASE WHEN published_date IS NULL OR published_date = '' THEN 1 ELSE 0 END) / COUNT(*), 2) AS missing_pct
FROM papers;

-- 3) authors がJSON配列でない件数（legacy残件確認）
SELECT COUNT(*) AS non_json_authors
FROM papers
WHERE authors IS NOT NULL
  AND TRIM(authors) <> ''
  AND SUBSTR(TRIM(authors), 1, 1) <> '[';
```

## 重複データの安全な削除手順（SQLite）

過去データに重複が残っている場合は、`docs/safe_deduplicate_papers.sql` を使用してください。

### 実行手順（そのままコピペでOK）

```bash
# 1) リポジトリ直下へ移動
cd /workspace/journal-tracker

# 2) DBファイルがあることを確認
ls -l data/papers.db

# 3) 重複削除SQLを実行
sqlite3 data/papers.db ".read docs/safe_deduplicate_papers.sql"
```

### 実行後に確認すること

- バックアップファイル `data/papers.backup.before_dedup.db` が生成されていること
- SQLの出力で、以下が `0` になっていること
  - `after_normalized_doi_duplicates`
  - `after_normalized_url_duplicates`

### 補足

- このSQLは次を一括実行します。
  1. `VACUUM INTO` によるバックアップ作成（`data/papers.backup.before_dedup.db`）
  2. `normalized_doi` / `normalized_url` の重複件数を削除前に確認
  3. 同一キー内で `rowid` 最小の1件だけ残して重複削除
  4. 削除後の重複件数を再確認
- `VACUUM INTO` が失敗する場合は、`sqlite3 --version` でSQLiteのバージョンを確認してください（3.27+ 推奨）。

## ライセンス

MIT License
