"""候補(data/kouho.csv)を、照合の結果で振り分ける。

GitHub Actions の shougou の結果を見て、一致した id を渡す。
一致した行は公開データ(data/seido.csv)へ。--horyu で理由を付けた行は保留(data/horyu.csv)へ。
どちらでもない行は候補に残る。

使い方: python scripts/furiwake.py --icchi id1,id2 --horyu "id3=照合: 根拠の箇所がページに無い"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

HOLD_COLS = schema.COLUMNS + ["保留の理由"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--icchi", default="")
    ap.add_argument("--horyu", action="append", default=[])
    args = ap.parse_args()
    matched = {x for x in args.icchi.split(",") if x}
    reasons = dict(x.split("=", 1) for x in args.horyu)

    kouho = schema.read_csv("data/kouho.csv")
    seido = schema.read_csv("data/seido.csv")
    horyu = schema.read_csv("data/horyu.csv")
    ids = {r["id"] for r in kouho}
    unknown = (matched | set(reasons)) - ids
    if unknown:
        print(f"候補に無い id: {sorted(unknown)}")
        return 1

    moved = {r["id"] for r in kouho if r["id"] in matched or r["id"] in reasons}
    seido = [r for r in seido if r["id"] not in moved] + [r for r in kouho if r["id"] in matched]
    horyu = [r for r in horyu if r["id"] not in moved] + [
        {**r, "保留の理由": reasons[r["id"]]} for r in kouho if r["id"] in reasons
    ]
    seido.sort(key=lambda r: r["id"])
    schema.write_csv("data/seido.csv", seido)
    schema.write_csv("data/horyu.csv", horyu, HOLD_COLS)
    schema.write_csv("data/kouho.csv", [r for r in kouho if r["id"] not in moved])
    schema.load("data/seido.csv")
    print(f"公開 {len(seido)}件 / 保留 {len(horyu)}件 / 候補の残り {len(kouho) - len(moved)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
