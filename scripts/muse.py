"""Muse(別の AI)の点検結果を取り込み、人が見る行を選ぶ。

Muse の判定は「人の再確認」ではない。data/saikakunin.csv の「判定」には入れず、
data/kenshou_muse.csv に別に持つ。

人が見る行:
  1. Muse が「違う」「分からない」とした行
  2. Muse が全項目「合っている」とした制度から、抜き取りで N 件(既定 10)。その制度の全行を見る
     抜き取りは乱数の種を固定し、種を記録に残す(あとで同じ選び方を再現できるように)

使い方: python scripts/muse.py Museの結果.csv [--nuki 10] [--tane 20261115]
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

OUT = "data/kenshou_muse.csv"
COLS = ["id", "項目", "Muse判定", "根拠", "メモ", "開いたURL", "人が見る", "選んだ理由"]
JUDGE = ("合っている", "違う", "分からない")


def check(muse: list[dict[str, str]], ichiran: list[dict[str, str]]) -> list[str]:
    """Muse の行が一覧と1対1で対応しているかを確かめる。問題の一覧を返す。"""
    problems = []
    want = [(r["id"], r["項目"]) for r in ichiran]
    got = [(r.get("id", ""), r.get("項目", "")) for r in muse]
    if collections.Counter(got) != collections.Counter(want):
        missing = set(want) - set(got)
        extra = set(got) - set(want)
        dup = [k for k, n in collections.Counter(got).items() if n > 1]
        problems.append(f"一覧と行が合わない。足りない {sorted(missing)} / 余分 {sorted(extra)} / 重複 {dup}")
    for r in muse:
        if r.get("Muse判定") not in JUDGE:
            problems.append(f"Muse判定が3つのどれでもない: {r.get('id')} {r.get('項目')} {r.get('Muse判定')!r}")
    return problems


def choose(muse: list[dict[str, str]], nuki: int, tane: int) -> list[dict[str, str]]:
    """人が見る行に印を付けた行を返す。"""
    by_id = collections.defaultdict(list)
    for r in muse:
        by_id[r["id"]].append(r["Muse判定"])
    all_ok = sorted(i for i, js in by_id.items() if all(j == "合っている" for j in js))
    picked = set(random.Random(tane).sample(all_ok, min(nuki, len(all_ok))))
    out = []
    for r in muse:
        row = {c: r.get(c, "") for c in COLS}
        if r["Muse判定"] != "合っている":
            row["人が見る"], row["選んだ理由"] = "見る", f"Muse が「{r['Muse判定']}」"
        elif r["id"] in picked:
            row["人が見る"], row["選んだ理由"] = "見る", f"抜き取り(種 {tane})"
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("muse")
    ap.add_argument("--nuki", type=int, default=10)
    ap.add_argument("--tane", type=int, default=20261115)
    args = ap.parse_args()
    muse = schema.read_csv(args.muse)
    ichiran = schema.read_csv("data/saikakunin.csv")
    problems = check(muse, ichiran)
    if problems:
        print("\n".join(problems))
        return 1
    rows = choose(muse, args.nuki, args.tane)
    schema.write_csv(OUT, rows, COLS)
    c = collections.Counter(r["Muse判定"] for r in rows)
    look = [r for r in rows if r["人が見る"]]
    print(f"{OUT}: {len(rows)}行 {dict(c)}")
    print(f"人が見る: {len(look)}行、{len({r['id'] for r in look})}件の制度")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
