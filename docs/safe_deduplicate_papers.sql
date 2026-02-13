-- journal-tracker: papers テーブルの重複整理手順（SQLite）
-- 対象DB: data/papers.db
-- 実行例:
--   sqlite3 data/papers.db ".read docs/safe_deduplicate_papers.sql"

PRAGMA foreign_keys = OFF;
PRAGMA journal_mode = WAL;

-- ==========================================================
-- 0) 事前バックアップ（失敗時は即中断）
-- ==========================================================
-- SQLite 3.27+ の VACUUM INTO を利用
VACUUM INTO 'data/papers.backup.before_dedup.db';

-- ==========================================================
-- 1) 削除前チェック
-- ==========================================================

-- 1-1) normalized_doi 重複数（本来 0 件想定）
SELECT 'before_normalized_doi_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT normalized_doi
  FROM papers
  WHERE normalized_doi IS NOT NULL AND TRIM(normalized_doi) <> ''
  GROUP BY normalized_doi
  HAVING COUNT(*) > 1
);

-- 1-2) normalized_url 重複数（本来 0 件想定）
SELECT 'before_normalized_url_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT normalized_url
  FROM papers
  WHERE normalized_url IS NOT NULL AND TRIM(normalized_url) <> ''
  GROUP BY normalized_url
  HAVING COUNT(*) > 1
);

-- ==========================================================
-- 2) 重複削除（同一キー内で rowid が最小の 1 件を残す）
-- ==========================================================

BEGIN TRANSACTION;

-- 2-A) DOI重複を解消
DELETE FROM papers
WHERE rowid IN (
  SELECT rowid
  FROM (
    SELECT rowid,
           ROW_NUMBER() OVER (
             PARTITION BY normalized_doi
             ORDER BY rowid ASC
           ) AS rn
    FROM papers
    WHERE normalized_doi IS NOT NULL AND TRIM(normalized_doi) <> ''
  ) t
  WHERE t.rn > 1
);

-- 2-B) URL重複を解消（DOI削除後に再評価）
DELETE FROM papers
WHERE rowid IN (
  SELECT rowid
  FROM (
    SELECT rowid,
           ROW_NUMBER() OVER (
             PARTITION BY normalized_url
             ORDER BY rowid ASC
           ) AS rn
    FROM papers
    WHERE normalized_url IS NOT NULL AND TRIM(normalized_url) <> ''
  ) t
  WHERE t.rn > 1
);

COMMIT;

-- ==========================================================
-- 3) 削除後チェック
-- ==========================================================

SELECT 'after_normalized_doi_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT normalized_doi
  FROM papers
  WHERE normalized_doi IS NOT NULL AND TRIM(normalized_doi) <> ''
  GROUP BY normalized_doi
  HAVING COUNT(*) > 1
);

SELECT 'after_normalized_url_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT normalized_url
  FROM papers
  WHERE normalized_url IS NOT NULL AND TRIM(normalized_url) <> ''
  GROUP BY normalized_url
  HAVING COUNT(*) > 1
);

-- 参考: 総件数
SELECT 'total_rows_after' AS check_name, COUNT(*) AS total_rows
FROM papers;
