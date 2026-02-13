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

-- 1-3) raw DOI 重複数（normalized_doi が空の legacy データ向け）
SELECT 'before_raw_doi_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT LOWER(TRIM(doi)) AS doi_key
  FROM papers
  WHERE (normalized_doi IS NULL OR TRIM(normalized_doi) = '')
    AND doi IS NOT NULL AND TRIM(doi) <> ''
  GROUP BY doi_key
  HAVING COUNT(*) > 1
);

-- 1-4) raw URL 重複数（normalized_url が空の legacy データ向け）
SELECT 'before_raw_url_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT LOWER(TRIM(url)) AS url_key
  FROM papers
  WHERE (normalized_url IS NULL OR TRIM(normalized_url) = '')
    AND url IS NOT NULL AND TRIM(url) <> ''
  GROUP BY url_key
  HAVING COUNT(*) > 1
);

-- ==========================================================
-- 2) 重複削除（同一キー内で rowid が最小の 1 件を残す）
-- ==========================================================

BEGIN TRANSACTION;

-- 2-A) DOI重複を解消（normalized_doi 優先、空なら raw DOI で代替）
DELETE FROM papers
WHERE rowid IN (
  SELECT rowid
  FROM (
    SELECT rowid,
           ROW_NUMBER() OVER (
             PARTITION BY CASE
               WHEN normalized_doi IS NOT NULL AND TRIM(normalized_doi) <> '' THEN LOWER(TRIM(normalized_doi))
               WHEN doi IS NOT NULL AND TRIM(doi) <> '' THEN LOWER(TRIM(doi))
               ELSE NULL
             END
             ORDER BY rowid ASC
           ) AS rn,
           CASE
             WHEN normalized_doi IS NOT NULL AND TRIM(normalized_doi) <> '' THEN LOWER(TRIM(normalized_doi))
             WHEN doi IS NOT NULL AND TRIM(doi) <> '' THEN LOWER(TRIM(doi))
             ELSE NULL
           END AS doi_key
    FROM papers
  ) t
  WHERE t.doi_key IS NOT NULL AND t.rn > 1
);

-- 2-B) URL重複を解消（normalized_url 優先、空なら raw URL で代替）
DELETE FROM papers
WHERE rowid IN (
  SELECT rowid
  FROM (
    SELECT rowid,
           ROW_NUMBER() OVER (
             PARTITION BY CASE
               WHEN normalized_url IS NOT NULL AND TRIM(normalized_url) <> '' THEN LOWER(TRIM(normalized_url))
               WHEN url IS NOT NULL AND TRIM(url) <> '' THEN LOWER(TRIM(url))
               ELSE NULL
             END
             ORDER BY rowid ASC
           ) AS rn,
           CASE
             WHEN normalized_url IS NOT NULL AND TRIM(normalized_url) <> '' THEN LOWER(TRIM(normalized_url))
             WHEN url IS NOT NULL AND TRIM(url) <> '' THEN LOWER(TRIM(url))
             ELSE NULL
           END AS url_key
    FROM papers
  ) t
  WHERE t.url_key IS NOT NULL AND t.rn > 1
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

SELECT 'after_raw_doi_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT LOWER(TRIM(doi)) AS doi_key
  FROM papers
  WHERE (normalized_doi IS NULL OR TRIM(normalized_doi) = '')
    AND doi IS NOT NULL AND TRIM(doi) <> ''
  GROUP BY doi_key
  HAVING COUNT(*) > 1
);

SELECT 'after_raw_url_duplicates' AS check_name, COUNT(*) AS duplicate_groups
FROM (
  SELECT LOWER(TRIM(url)) AS url_key
  FROM papers
  WHERE (normalized_url IS NULL OR TRIM(normalized_url) = '')
    AND url IS NOT NULL AND TRIM(url) <> ''
  GROUP BY url_key
  HAVING COUNT(*) > 1
);

-- 参考: 総件数
SELECT 'total_rows_after' AS check_name, COUNT(*) AS total_rows
FROM papers;
