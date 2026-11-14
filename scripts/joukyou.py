"""README の「いまの状態」を、データから作り直す。

使い方: python scripts/joukyou.py   (README.md の「## いまの状態」から「## つなぐ先」の手前までを書き換える)
"""

from __future__ import annotations

import collections
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

KINDS = ["fs-hojo", "shien-center", "tayouka", "online", "shusseki"]
HEAD = "| 市町 | 利用料の補助 | 教育支援センター | 学びの多様化学校 | オンライン | 出席扱いの要綱・一覧 |"


def block() -> str:
    rows = schema.load("data/seido.csv")
    areas = schema.read_csv("data/shichoson.csv")
    c = collections.Counter(r["状態"] for r in rows)
    cell = {(r["市町村コード"], schema.KIND_BY_LABEL[r["制度の種類"]]): r["状態"] for r in rows}
    metro = [a for a in areas if a["福岡都市圏"] == "○"]
    lines, done, filled = [HEAD, "|---|---|---|---|---|---|"], 0, collections.Counter()
    for a in metro:
        vals = [cell.get((a["市町村コード"], k), "未着手") for k in KINDS]
        done += "未着手" not in vals
        filled.update(v for v in vals if v != "未着手")
        lines.append(f"| {a['市町村']} | " + " | ".join(vals) + " |")
    metro_codes = {a["市町村コード"] for a in metro}
    outside = collections.Counter(r["市町村"] for r in rows if r["市町村コード"] not in metro_codes)
    kouho = len(schema.read_csv("data/kouho.csv"))
    horyu = len(schema.read_csv("data/horyu.csv"))
    today = dt.date.today().isoformat()
    return f"""## いまの状態({today})

福岡都市圏の17市町のうち、{done}市町で5種類すべてに状態が付いた。残りは読んでいる途中か、未着手。

| | 件数 | 数え方 |
|---|---|---|
| 公開データ(`data/seido.csv`) | {len(rows)} | 読み込み時の検査に通り、出典のある行は出典ページとの照合にも通った行 |
| うち あり | {c['あり']} | 出典ページに根拠の箇所と数字がある |
| うち 予定 | {c['予定']} | 同上 |
| うち なし | {c['なし']} | 公式の一覧に、その市町村が載っていないことを照合した(いまは学びの多様化学校だけ) |
| うち 確認できず | {c['確認できず']} | 照合の対象外。探した場所を記録している |
| 候補(`data/kouho.csv`) | {kouho} | 照合を待っている行 |
| 保留(`data/horyu.csv`) | {horyu} | 検査や照合に通らなかった行 |

福岡都市圏の17市町×5種類(85マス)の状況。{sum(filled.values())}マスに状態が付いた(あり {filled['あり']}、予定 {filled['予定']}、なし {filled['なし']}、確認できず {filled['確認できず']})。「未着手」はまだ読んでいないマス。

{chr(10).join(lines)}

都市圏の外は、{len(outside)}の市町村と県で{sum(outside.values())}件。ほとんどが、文部科学省の一覧と突き合わせた学びの多様化学校の行で、ほかの種類はまだ読んでいない。

「確認できず」が多いのは、まだ各市町で1〜数ページしか読んでいないため。見つからなかっただけで、制度が無いという意味ではない。探したページは各行の「探した場所」にある。

学びの多様化学校の「なし」は、文部科学省の設置者一覧に、その市町村を設置場所とする学校が載っていないという意味。設置の検討や予定は、この一覧からは分からない。

公開データは、機械の読み取りと照合だけで、人の再確認をまだしていない。照合の結果は、GitHub Actions の `shougou` の実行結果で見られる。

"""


def main() -> int:
    p = Path("README.md")
    t = p.read_text(encoding="utf-8")
    a, b = t.index("## いまの状態"), t.index("## つなぐ先")
    p.write_text(t[:a] + block() + t[b:], encoding="utf-8")
    print(block())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
