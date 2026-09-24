# AGENTS.md

このリポジトリを保守・改善する **AIエージェント（Claude Code / Codex 等）向けの正本**。
人が手で改良するのではなく、エージェントが「現状把握 → 課題選定 → 修正 → 検証 → PR」を自律的に回す前提で書いている。
`CLAUDE.md` はこのファイルを読み込むだけ。README は公開ページの訪問者向けで、開発情報は置かない。

## 0. セットアップ（最初に実行）

```bash
pip install -r requirements-dev.txt   # 本番依存 + pytest（Python 3.10+。CIは3.13）
python -m pytest tests/ -q            # 全テスト（ネットワーク不要・数秒）
python -m src.main --self-check       # 設定・Excel・DB・テンプレート・出力先の自己診断
```

Claude Code on the web では `.claude/settings.json` の SessionStart フックが `scripts/setup_dev.sh` を実行し、依存を自動で入れる。

## 1. 目的と不変条件

**目的**：会計・ファイナンス主要誌（`Accounting_Journals_URL_List.xlsx` の67誌）の新着論文を、**漏れなく・誤りなく**毎日集め、
GitHub Pages（https://shimi-toshi.github.io/journal-tracker/ ）に公開する。利用者は会計学（財務会計）の研究者。

次の設計判断は過去の事故から導いたもの。**理由を理解せずに変えないこと**（変える場合はPRで根拠を示す）。

| 不変条件 | 理由（変えると何が起きるか） |
|---|---|
| CrossRef `/works` を **`from-created-date`（初回登録日）** で絞る | `from-pub-date` だと月のみ日付の論文が登録遅延で窓を外れ恒久的に取りこぼす。`from-index-date` だと既存DOIの再デポジットで古い論文が大量流入する（2026-06-14 に500件超の実例） |
| ISSNは **Online/Print 両方を `issn:` で併記**（`Journal.issns`） | CrossRefは同名フィルタをOR解釈。publisherにより works が片方のISSNにしか無い（Elsevierは Print、De Gruyter は Online のみ等）。片方だけだと誌ごと0件になる |
| `/journals/{issn}/works` は使わない | 代表ISSNと一致しないと404 |
| 「直近N日」は **`fetched_at`（本サイトの取得日）基準**、起点は**ページ生成日** | CrossRefの月のみ日付は day=1 に丸められ、公表日基準だと件数が狂う。ページは1日1回生成なので閲覧時刻基準だと翌朝「直近1日」が0件になる |
| `fetched_at - published_date > max_publication_lag_days(60)` は新着から除外 | 新規参入誌のアーカイブ一括登録（新規DOI）は created=今日 ですり抜けるための二重防御 |
| **`--dry-run` はDB・journal_statusに書かない** | 書くと新着が「消費」され、次回の本番出力から永久に漏れる |
| 論文以外の項目（Editorial Board 等）は `filter.exclude_title_patterns` で除外 | 取得時はDBに入れず、表示時は既存行も隠す。**訂正記事（Erratum/Corrigendum）は除外しない** |
| タイトル・アブストラクトは `clean_markup()` で整形してから表示 | CrossRefのタイトルには `<scp>` `<i>` 等が入り、自動エスケープで `&lt;scp&gt;` と表示される |
| DBは **ロールバックジャーナル（journal_mode=DELETE）** | DBファイルをgitにコミットするため。WALだと `-wal` 未反映の変更が失われうる（過去の保守SQLがWALを永続化していた） |
| Actions は **`TZ=Asia/Tokyo`** で実行 | 生成時刻・`fetched_at`・日付フィルタをJSTで揃える（利用者は日本） |

## 2. アーキテクチャ

```
Accounting_Journals_URL_List.xlsx ─(utils.load_journals_from_excel)→ list[Journal]
  → PaperFetcher.fetch_all (CrossRef /works, 誌ごとにキャッチアップ窓)
  → タイトル除外 → PaperStorage.save_batch (SQLite, 重複はDB制約で排除) → 新着
  → ExcelExporter (output/new_papers_YYYYMMDD.xlsx, CIでは捨てられる)
  → PaperStorage.update_journal_status (誌別の成否)
  → get_recent_papers(30日, ラグ除外, タイトル除外) + get_failing_journals
  → HtmlExporter → docs/index.html, docs/latest.md, docs/papers.json, docs/llms.txt
  → logs/run_report_*.json（最新30件）+ data/last_run.json（コミットされる）
```

| モジュール | 役割 |
|---|---|
| `src/main.py` | CLI・オーケストレーション・`run_self_check` |
| `src/fetcher.py` | `CrossRefFetcher`（1誌1リクエスト、rows=1000、429/5xxリトライ）、`PaperFetcher`（全誌ループ・キャッチアップ・統計） |
| `src/parser.py` | `Paper`/`Journal`、`normalize_doi/url`、`clean_markup/clean_abstract`、`is_excluded_title` |
| `src/storage.py` | SQLite（`_connect()` で必ずclose）、重複排除、journal_status、長期エラー判定、最終成功日 |
| `src/html_exporter.py` | 公開ページ一式（HTML＋AI向け Markdown/JSON/llms.txt） |
| `src/exporter.py` | Excel出力 |
| `src/utils.py` | 設定・パス解決（プロジェクトルート基準）・Excel読込（空セル→""） |
| `templates/index.html` | Jinja2テンプレート（日数スライダー・検索・アブストラクト折りたたみはクライアントJS） |
| `scripts/status_report.py` | **現状把握レポート**（読み取り専用） |
| `scripts/diagnose_issn.py` | ExcelのISSN妥当性をCrossRefに照会（誌名不一致・旧ISSN・兄弟ISSN欠落） |

### 主要ロジック
- **unique_id**：正規化DOI → 正規化URLのMD5 → 「タイトル:誌名」のMD5 の順。DBは `normalized_doi`/`normalized_url` の部分ユニークインデックス＋`INSERT OR IGNORE` で重複排除。
- **キャッチアップ取得**：誌ごとに `max(days_back, min(max_catchup_days, 最後の成功からの日数+1))` 日遡る。Actions停止や長期エラーからの復帰時の取りこぼし防止。
- **長期エラー**（`failing_journals_from_conn`）：連続失敗 ≥ 閾値、または直近失敗かつ最後の成功（無ければ最新 fetched_at）から閾値日以上。該当誌は論文欄を出さず注意書きのみ。Excelから外した誌は対象外。
- **終了コード**：Excel/HTML出力の失敗は処理を続けたうえで最後に1を返す（Actionsが失敗として検知し、コミットされない）。

### DBスキーマ（`SCHEMA_VERSION = 3`）
```sql
papers(unique_id TEXT PK, normalized_doi TEXT, normalized_url TEXT, title TEXT NOT NULL, journal_name TEXT NOT NULL,
       authors TEXT /*JSON配列。旧行はCSV*/, abstract TEXT, doi TEXT, url TEXT, published_date TEXT /*ISO*/,
       fetched_at TEXT NOT NULL /*ISO, ローカル時刻(Actions=JST)*/, notified INTEGER DEFAULT 0 /*Excel出力済み*/)
  -- idx_journal(journal_name), idx_fetched(fetched_at),
  -- UNIQUE idx_unique_normalized_doi / idx_unique_normalized_url（NULL/空は除外の部分インデックス）
metadata(key TEXT PK, value TEXT)            -- schema_version
journal_status(journal_name TEXT PK, last_success_at, last_error_at, last_error_type,
               consecutive_failures INTEGER DEFAULT 0, updated_at)
```
スキーマ変更時は `SCHEMA_VERSION` を上げ、`_init_db()` に**後方互換マイグレーション**を追加し、`tests/` に移行テストを足す。

### 設定（`config/config.yaml`）
| キー | 既定 | 説明 |
|---|---|---|
| `fetch.days_back` | 7 | 通常の取得窓（CrossRef初回登録日基準） |
| `fetch.max_catchup_days` | 30 | キャッチアップの上限日数 |
| `fetch.timeout` / `fetch.rate_limit_seconds` | 30 / 1.0 | HTTPタイムアウト / 誌間の待機 |
| `filter.exclude_title_patterns` | Editorial Board 等 | 論文以外の除外（先頭一致の正規表現・大小無視） |
| `html_export.days_back` | 7 | 既定表示日数・latest.md の期間 |
| `html_export.selectable_days_range` | [1, 30] | スライダー範囲。上限が papers.json・DB取得期間 |
| `html_export.max_publication_lag_days` | 60 | バックカタログ除外の閾値 |
| `html_export.failure_threshold` | 7 | 長期エラー判定（連続失敗回数≒日数） |
| `html_export.site_url` | 公開URL | llms.txt 等の絶対リンク |
| `database.path` / `logs.output_dir` / `export.output_dir` | data/papers.db / logs / output | パスはプロジェクトルート基準 |
| `journals.excel_path` | Accounting_Journals_URL_List.xlsx | 対象誌リスト |
| `google_analytics` | ID | 公開ページのGA |

環境変数 `CROSSREF_EMAIL`（`.env` / Actions Secret）：CrossRef polite pool 用。

## 3. 現状把握（改善サイクルの最初に必ず行う）

1. `python -m scripts.status_report`（`--json` で全項目）— DBを**読み取り専用**で開き、次を出す：
   - 要確認事項（長期エラー誌、DBに論文が1件も無い誌、ISSN未設定、journal_mode、最終実行の古さ・失敗）
   - 直近の実行結果（`data/last_run.json`：取得件数・新着数・除外数・失敗誌・キャッチアップ誌・終了コード）
   - DB統計（直近7/30日件数、除外された件数、タグ入りタイトル数、公表日欠損率）
   - 誌別フラグ（`no_papers_ever` / `no_new_30d` / `long_term_failing` / `recent_failure` / `no_issn`）
2. フラグの付いた誌は `python -m scripts.diagnose_issn --problems-only` で CrossRef と突き合わせる（1誌数秒・全誌で約5分）。
   「直近365日の登録0件」「兄弟ISSNがExcelに無い」が出たら、`https://api.crossref.org/journals/{issn}` と
   `works?filter=issn:A,issn:B,from-created-date:...&select=container-title` で**取りこぼし件数と混入の有無**を確かめてから Excel を直す。
3. 公開ページの実物は `docs/latest.md`（直近7日）と `docs/papers.json`（30日）で確認できる。
4. Actions のログが必要なら GitHub の Actions 実行履歴（Update Journal Tracker Pages / Tests）を見る。

## 4. 改善サイクル

1. 上の「現状把握」を実行し、問題があれば最優先で対処。無ければ §6 バックログから1件選ぶ。
2. 変更は最小限に。ロジック変更には**回帰テストを同時に追加**（`tests/test_improvements.py` 等。ネットワークは `unittest.mock` で遮断）。
3. `python -m pytest tests/ -q` と `python -m src.main --self-check` を通す。表示に関わる変更は、実DBのコピーと一時ディレクトリの設定で
   `python -m src.main` を実行し（`CrossRefFetcher.fetch` をモック）、生成物を確認。UIは Playwright（`/opt/pw-browsers/chromium`）で確認できる。
4. ブランチを切って draft PR。CI（`.github/workflows/tests.yml`）が通ること。§6 のバックログを更新（完了は削除、新発見は追記）。

### 作業上の注意
- **`data/papers.db`・`data/last_run.json`・`docs/*` は Actions が毎日更新する生成物。手で編集・コミットしない**。
  ローカルで `python -m src.main` を実DBに対して実行すると DB が変わるので、検証は DB のコピーで行い、誤って変えたら `git checkout data/papers.db`。
- Excel（対象誌リスト）の修正は openpyxl で該当セルだけ書き換え、変更セルを読み戻して確認する。`--list-journals` で反映を確認。
- コメント・ログ・ドキュメントは日本語（既存に合わせる）。README のランキング表は Excel の ABDC/ABS と一致させる。

## 5. よくある落とし穴
- ExcelのISSNが**旧誌・旧レコード**のもの（例：AAAJ の 0951-3574 は CrossRef上 “Accounting Auditing & Accountability” の旧レコードで2025-08以降登録なし。現行は 1368-0668/1758-4205）や、
  **出版社移籍前**のもの（TIJA は Elsevier→World Scientific 移籍で 0020-7063/1873-6548 → 1094-4060/2213-3933）。いずれもHTTP 200・0件で静かに取りこぼす。
- ISSNを併記すると OR になるため、**別誌のISSN**を入れると他誌の論文が混入する（`--self-check` が同一ISSNの重複を検知）。
- Excelセルの前後空白・タブ・空セル（`utils._cell` が吸収）。
- GitHub Pages は `docs/` 以下を**すべて公開**する。保守用ファイルを置かない。
- Actions の cron は混雑で遅延する（毎時0分を避けて 9:17 UTC）。
- CrossRef は無認証だと 429 を返しやすい。スクリプトからの連続照会は `--sleep 1.0` 以上＋`CROSSREF_EMAIL` 設定で。

## 6. 既知の課題・改善バックログ（完了したら削除、見つけたら追記）

| 優先 | 課題 | 詳細・想定方針 |
|---|---|---|
| 中 | Advances in Accounting Behavioral Research / Advances in Management Accounting が取得0件 | Emerald の年刊ブックシリーズ。ISSNでの直近1年の登録が0件。巻が book-chapter（ISBN）として登録されている可能性。CrossRef で `container-title` 検索して登録形態を確認し、取得方法を検討（年刊なので影響は小さい） |
| 低 | `diagnose_issn` が「兄弟ISSNがExcelに無い」と出す誌（ARJ, ARA, IJAIM, JAOC, JAAR, JPBAFM, RF, FAJ, JAAF） | 2026-09時点で追加しても取りこぼし0件（現ISSNで網羅）。混入リスクを増やさないため未追加。定期的に取りこぼし件数を再確認 |
| 低 | DBを毎日コミットするため履歴が肥大（約5MB/日の差分） | データ専用ブランチ or Release アセット or Actions cache への移行を検討。Pages 公開物との整合に注意 |
| 低 | 月のみの公表日が `YYYY/MM/01` と表示される | 日付精度をDBに保持するスキーマ変更（v4）が必要 |
| 低 | 旧RSS時代（〜2026-06）の行：DOIなし約1,150件・公表日欠損あり | 表示窓（30日）外なので実害なし。必要なら整理スクリプトを書く |
| 低 | `notified` 列と `get_unnotified()` は Excel 出力済みフラグにすぎず、ほぼ未使用 | 削除するならスキーマ移行とテスト修正を伴う |
| 低 | 依存に上限バージョンが無い（`>=` のみ） | Tests ワークフローで早期検知している。壊れたら上限を付ける |
| 低 | index.html が約740KB（アブストラクト込み） | 増え続けるなら、アブストラクトを papers.json から遅延読込する設計を検討 |
| 低 | Excel の "RSS Feed" / "Status" 列は未使用（互換のため必須列に残置） | 列を削除するなら `REQUIRED_JOURNAL_COLUMNS` とテストも更新 |
