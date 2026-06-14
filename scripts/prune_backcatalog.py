"""バックカタログ再登録の残渣を一度だけ整理する保守スクリプト（使い捨て）。

旧来 CrossRef を `from-index-date`（最終インデックス日）で取得していたため、publisher が
既存DOIのメタデータを再デポジットすると古い論文が新着として流入し、DBに蓄積されていた。
これらは HTML 出力では `max_publication_lag_days` ガード（storage.get_recent_papers）で
既に非表示だが、DB本体と統計には残っている。`from-created-date` への切替で今後は再発しないため、
過去分を一度だけ削除して整理する。

判定は get_recent_papers のガードと完全に一致させる:
    (fetched_at - published_date).days > max_publication_lag_days

published_date が無い論文は対象外（ガードと同じく除外しない）。

使い方（リポジトリルートから）:
    python -m scripts.prune_backcatalog            # ドライラン（件数のみ表示）
    python -m scripts.prune_backcatalog --apply    # 実際に削除
"""

import argparse
import sqlite3
import sys
from datetime import datetime

from src.utils import ensure_data_dir, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="バックカタログ残渣の一度きり整理")
    parser.add_argument("--config", "-c", default=None, help="設定ファイルパス")
    parser.add_argument("--apply", action="store_true", help="実際に削除する（既定はドライラン）")
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = ensure_data_dir(config)
    threshold = config.get("html_export", {}).get("max_publication_lag_days", 60)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]

    to_delete: list[str] = []
    for row in conn.execute(
        "SELECT unique_id, published_date, fetched_at FROM papers "
        "WHERE published_date IS NOT NULL AND published_date != ''"
    ):
        try:
            published = datetime.fromisoformat(row["published_date"])
            fetched = datetime.fromisoformat(row["fetched_at"])
        except (TypeError, ValueError):
            continue
        if (fetched - published).days > threshold:
            to_delete.append(row["unique_id"])

    print(f"DB総行数: {total}")
    print(f"閾値(max_publication_lag_days): {threshold} 日")
    print(f"削除対象（lag > 閾値）: {len(to_delete)} 件")

    if not args.apply:
        print("ドライラン: 削除は行っていません。--apply で実行してください。")
        return 0

    with conn:
        conn.executemany("DELETE FROM papers WHERE unique_id = ?", [(uid,) for uid in to_delete])
    remaining = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    print(f"削除完了。残り行数: {remaining}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
