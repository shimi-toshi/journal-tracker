"""ジャーナルExcelのISSN妥当性をCrossRefに照会して診断する保守スクリプト。

論文取得は各誌の Online/Print 両ISSNを `issn:` フィルタに併記してCrossRefへ問い合わせる
（CrossRefは同名フィルタをORで解釈。fetcher.CrossRefFetcher.fetch / Journal.issns 参照）。
ISSNが誤っている／別誌のものだと、HTTPは200でも次のように静かに事故る:

  - 全ISSNで登録0件 … そのISSN群では1件も取得できない（取りこぼし）
  - ISSNが別誌に紐づく … ORで併記すると**別誌の論文が混入**する（汚染）

このスクリプトは production と同じ Journal.issns を使って各ISSNをCrossRefへ照会し、

  - 全ISSNで works=0（＝そのISSN群では取得不能）
  - いずれかのISSNにCrossRefが結び付ける誌名が、こちらの誌名と一致しない（＝混入リスク）

を検出する。あわせて現在のDB登録件数も並記する。判定は目安で、最終判断（Excel修正）は人手で。

使い方（リポジトリルートから）:
    python -m scripts.diagnose_issn                 # 全誌を診断
    python -m scripts.diagnose_issn --problems-only # 要確認の誌だけ表示
    python -m scripts.diagnose_issn --config path/to/config.yaml
    python -m scripts.diagnose_issn --sleep 0.5     # API間の待機秒（既定1.0）
"""

import argparse
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass

import requests

from src.utils import ensure_data_dir, load_config, load_journals_from_excel

CROSSREF_WORKS = "https://api.crossref.org/works"
CROSSREF_JOURNALS = "https://api.crossref.org/journals/{issn}"

_WORD = re.compile(r"[a-z0-9]+")
# 誌名一致判定で無視する汎用語
_STOPWORDS = {"the", "of", "and", "a", "an", "for", "in", "on", "journal", "review"}


@dataclass
class IssnProbe:
    """単一ISSNのCrossRef照会結果"""

    issn: str
    works: int | None = None  # 登録件数（None=未照会/エラー）
    title: str | None = None  # CrossRefが結び付ける誌名（None=journal記録なし）
    error: str | None = None


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _title_matches(journal_name: str, crossref_title: str | None) -> bool:
    """誌名のゆるい一致判定（語の重なり率で混入を検出）"""
    if not crossref_title:
        return True  # journal記録が無いだけでは混入と断定しない
    a, b = _tokens(journal_name), _tokens(crossref_title)
    if not a or not b:
        return True
    a2, b2 = a - _STOPWORDS, b - _STOPWORDS
    if not a2 or not b2:
        a2, b2 = a, b
    return len(a2 & b2) / len(a2 | b2) >= 0.4


class CrossRefProber:
    def __init__(self, email: str, timeout: int, sleep: float):
        self.timeout = timeout
        self.sleep = sleep
        self.session = requests.Session()
        ua = f"JournalTracker/1.0 (mailto:{email})" if email else "JournalTracker/1.0"
        self.session.headers.update({"User-Agent": ua})

    def _get(self, url: str, **kw):
        resp = self.session.get(url, timeout=self.timeout, **kw)
        if self.sleep > 0:
            time.sleep(self.sleep)
        return resp

    def works_count(self, issns: list[str]) -> int | None:
        """ISSN群（OR）の登録件数。production の取得クエリと同じ併記方式。"""
        if not issns:
            return None
        filt = ",".join(f"issn:{issn}" for issn in issns)
        try:
            resp = self._get(CROSSREF_WORKS, params={"filter": filt, "rows": 0})
            resp.raise_for_status()
            return resp.json().get("message", {}).get("total-results")
        except requests.RequestException:
            return None

    def probe(self, issn: str) -> IssnProbe:
        result = IssnProbe(issn=issn)
        try:
            resp = self._get(CROSSREF_WORKS, params={"filter": f"issn:{issn}", "rows": 0})
            resp.raise_for_status()
            result.works = resp.json().get("message", {}).get("total-results")
        except requests.RequestException as exc:
            result.error = str(exc)[:80]
            return result
        try:
            resp = self._get(CROSSREF_JOURNALS.format(issn=issn))
            if resp.status_code == 200:
                result.title = resp.json().get("message", {}).get("title")
        except requests.RequestException:
            pass
        return result


def _db_counts(db_path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not os.path.exists(db_path):
        return counts
    conn = sqlite3.connect(db_path)
    try:
        for name, c in conn.execute("SELECT journal_name, COUNT(*) FROM papers GROUP BY journal_name"):
            counts[name] = c
    finally:
        conn.close()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="ジャーナルISSNのCrossRef妥当性診断")
    parser.add_argument("--config", "-c", default=None, help="設定ファイルパス")
    parser.add_argument("--problems-only", action="store_true", help="要確認の誌だけ表示")
    parser.add_argument("--sleep", type=float, default=1.0, help="API呼び出し間の待機秒（既定1.0）")
    parser.add_argument("--limit", type=int, default=0, help="先頭N誌のみ診断（0=全件、デバッグ用）")
    args = parser.parse_args()

    config = load_config(args.config)
    excel_path = config.get("journals", {}).get("excel_path", "Accounting_Journals_URL_List.xlsx")
    timeout = config.get("fetch", {}).get("timeout", 30)
    email = os.environ.get("CROSSREF_EMAIL", config.get("email", {}).get("sender_email", ""))

    journals = load_journals_from_excel(excel_path)
    if args.limit > 0:
        journals = journals[: args.limit]
    db_counts = _db_counts(ensure_data_dir(config))

    prober = CrossRefProber(email=email, timeout=timeout, sleep=args.sleep)

    problems: list[tuple[str, str]] = []
    print(f"診断対象: {len(journals)} 誌  (CrossRef照会・API間 {args.sleep}s 待機)\n")

    for j in journals:
        issns = j.issns
        # 各ISSNを個別照会（誌名一致の確認用）し、取得件数はproduction同様のOR併記で測る
        probes = [prober.probe(i) for i in issns]
        or_works = prober.works_count(issns)

        verdict = "OK"
        if not issns:
            verdict = "ISSN未設定"
        elif any(p.error for p in probes):
            verdict = "照会エラー(" + next(p.error for p in probes if p.error) + ")"
        elif (or_works or 0) == 0:
            verdict = "全ISSNで0件（取得不能）"
        else:
            mismatched = [p for p in probes if not _title_matches(j.name, p.title)]
            if mismatched:
                m = mismatched[0]
                verdict = f"誌名不一致(ISSN {m.issn}→CrossRef='{m.title}')"

        is_problem = verdict != "OK"
        if is_problem:
            problems.append((j.name, verdict))
        if args.problems_only and not is_problem:
            continue

        flag = "  " if not is_problem else "⚠ "
        print(
            f"{flag}{j.name[:50]:50} issns={','.join(issns) or '∅':23} "
            f"works={or_works} DB={db_counts.get(j.name, 0)}  → {verdict}"
        )

    print(f"\n要確認: {len(problems)} 誌")
    for name, verdict in problems:
        print(f"  - {name}: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
