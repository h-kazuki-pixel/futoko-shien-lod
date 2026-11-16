"""人の再確認のための一覧を作り、結果を集計する。

「あり」「予定」の行を、項目ごとに1行にして data/saikakunin.csv に書く。
人が出典のページを開き、判定の列に「合っている / 違う / 分からない」を入れる。

使い方:
  python scripts/saikakunin.py            # 一覧を作り直す(値が変わっていない行の判定は残す)
  python scripts/saikakunin.py --shukei   # 判定を集計して表示する

人が判定を入れる場所は、同じ行を持つスプレッドシート(Claude の Sheets「不登校支援制度LOD 再確認の一覧」)。
入った判定・メモ・確認日は、id と項目で突き合わせて data/saikakunin.csv に写す。CSV を正とする。

誤り率の数え方: 違う ÷ (合っている + 違う)。「分からない」と未記入は分母に入れず、件数を別に出す。
項目ごとと、制度(id)ごとの両方を出す。制度ごとでは、1項目でも「違う」があれば「違う」と数える。
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

PATH = "data/saikakunin.csv"
COLS = ["id", "市町村", "項目", "値", "見るページ", "補助の資料", "判定", "メモ", "確認日"]
JUDGE = ("合っている", "違う", "分からない")
FIELDS = ["制度名", "対象", "金額", "開始", "補助の形", "備考"]

# 項目の根拠が、出典のページでなく別の資料にあるもの(docs/検証の結果.md)。
# 第2の出典の列(出典URL_2)に移したものは、列の値を使う。ここに残すのは、まだ移していないもの
# (福岡市のサイトが止まっていて、照合で確かめられない行など)。列に値があれば、そちらを優先する。
HOJO = {
    "40000-online": "https://www.pref.fukuoka.lg.jp/uploaded/attachment/268359.pdf",
    "40130-online": "https://www.city.fukuoka.lg.jp/kyoiku-iinkai/kyoikusodan/child/documents/onlineroom-annai.pdf",
    "40130-tayouka": "https://www.city.fukuoka.lg.jp/kyoiku-iinkai/kyoikusodan/child/documents/seitobosyuannai.pdf",
}


def make(seido: list[dict[str, str]], old: list[dict[str, str]]) -> list[dict[str, str]]:
    """一覧を作る。前の一覧と id・項目・値が同じ行は、判定・メモ・確認日を引き継ぐ。

    値が変わった行は判定を空にし、前の判定をメモに残す。
    """
    kept = {(r["id"], r["項目"], r["値"]): r for r in old}
    before = {(r["id"], r["項目"]): r for r in old if r["判定"]}
    out = []
    for r in seido:
        if r["状態"] not in ("あり", "予定"):
            continue
        second = r.get("出典URL_2", "") or HOJO.get(r["id"], "")
        hojo = " | ".join(dict.fromkeys(x for x in (second, r["要綱URL"]) if x))  # 同じ URL は1回だけ
        items = [("種類と状態", f"{r['制度の種類']} / {r['状態']}")]
        items += [(f, r[f]) for f in FIELDS if r[f]]
        for name, value in items:
            prev = kept.get((r["id"], name, value), {})
            if not prev and (r["id"], name) in before:
                # 値が変わった項目は、判定を引き継がない。前に何と判定されたかだけ、メモに残す
                b = before[(r["id"], name)]
                prev = {"メモ": f"値を直したので見直しが要る。直す前の値は、人が「{b['判定']}」と判定({b['確認日']})"}
            out.append(
                {
                    "id": r["id"],
                    "市町村": r["市町村"],
                    "項目": name,
                    "値": value,
                    "見るページ": r["出典URL"],
                    "補助の資料": hojo,
                    "判定": prev.get("判定", ""),
                    "メモ": prev.get("メモ", ""),
                    "確認日": prev.get("確認日", ""),
                }
            )
    return out


def shukei(rows: list[dict[str, str]]) -> dict:
    """判定を数える。誤り率は 違う ÷ (合っている + 違う)。分母が0なら None。"""
    bad = [r for r in rows if r["判定"] and r["判定"] not in JUDGE]
    if bad:
        raise ValueError(f"判定は {' / '.join(JUDGE)} のどれか: {[(r['id'], r['項目'], r['判定']) for r in bad]}")

    def rate(c: collections.Counter) -> float | None:
        n = c["合っている"] + c["違う"]
        return c["違う"] / n if n else None

    item = collections.Counter(r["判定"] or "未記入" for r in rows)
    by_field = collections.defaultdict(collections.Counter)
    by_id = collections.defaultdict(list)
    for r in rows:
        by_field[r["項目"]][r["判定"] or "未記入"] += 1
        by_id[r["id"]].append(r["判定"])
    seido = collections.Counter()
    for judges in by_id.values():
        if "違う" in judges:
            seido["違う"] += 1
        elif all(j == "合っている" for j in judges):
            seido["合っている"] += 1
        elif any(judges):
            seido["途中・分からないを含む"] += 1
        else:
            seido["未記入"] += 1
    return {
        "項目": dict(item),
        "項目の誤り率": rate(item),
        "項目ごと": {k: dict(v) for k, v in by_field.items()},
        "制度": dict(seido),
        "制度の誤り率": rate(seido),
        "違う": [(r["id"], r["項目"], r["メモ"]) for r in rows if r["判定"] == "違う"],
    }


def _pct(x: float | None) -> str:
    return "まだ出せない(合っている・違うが0件)" if x is None else f"{x:.1%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shukei", action="store_true")
    args = ap.parse_args()
    old = schema.read_csv(PATH) if Path(PATH).exists() else []
    if args.shukei:
        s = shukei(old)
        print(f"項目: {len(old)}行 {s['項目']} / 誤り率 {_pct(s['項目の誤り率'])}")
        print(f"制度: {sum(s['制度'].values())}件 {s['制度']} / 誤り率 {_pct(s['制度の誤り率'])}")
        for k, v in s["項目ごと"].items():
            print(f"  {k}: {v}")
        for x in s["違う"]:
            print(f"  違う: {x}")
        return 0
    rows = make(schema.load("data/seido.csv"), old)
    schema.write_csv(PATH, rows, COLS)
    print(f"{PATH}: {len({r['id'] for r in rows})}件の制度、{len(rows)}行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
