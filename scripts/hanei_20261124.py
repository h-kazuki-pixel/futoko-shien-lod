"""志免町の回答(2026-11-24 受信)を data/seido.csv と data/toiawase.csv に反映する。1回きり。

決まりは docs/問い合わせ.md の「回答の記録と、データへの反映」。作りは scripts/hanei_20261121.py と同じ。
担当者の個人名は書かない。回答の文面は写さず、項目に直して書く。
"""
import csv
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent / "data"

# (市町村コード, 種類): (回答日, 担当課, 方法, 回答, 反映後の状態 or None=変えない, 備考)
ANS = {
    ("40343", "fs-hojo"): ("2026-11-24", "学校教育課", "フォーム", "ない", "なし", ""),
    ("40343", "shien-center"): ("2026-11-24", "学校教育課", "フォーム", "ある。教育支援センター「さくらのみち」と適応指導教室「ぐんぐん」", None,
                                "町は、適応指導教室「ぐんぐん」もあると回答(2026-11-24)"),
    ("40343", "online"): ("2026-11-24", "学校教育課", "フォーム", "ない。町独自のもの", "なし", "町独自のオンラインの学習支援・居場所支援はない(回答)"),
    ("40343", "shusseki"): ("2026-11-24", "学校教育課", "フォーム", "公表していない。基準・施設一覧とも", "なし", "基準・施設一覧とも公表していない(回答)"),
}
KOUKAI: dict = {}
FULL: dict = {}

NASHI_NOTE = "公式ページに記載が見つからなかった。無いことは確認していない"


def main() -> None:
    path = BASE / "seido.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        cols, rows = rd.fieldnames, list(rd)
    ids: dict[tuple[str, str], str] = {}
    for r in rows:
        code, kind = r["id"].split("-", 1)
        if (code, kind) not in ANS:
            continue
        date, ka, how, ans, new, note = ANS[(code, kind)]
        ids[(code, kind)] = r["id"]
        if new == "なし":
            assert r["状態"] == "確認できず", r["id"]
            r["状態"] = "なし"
            word = "「公表していない」" if ans.startswith("公表していない") else "「ない」"
            r["なしの根拠"] = f"{date}、{r['市町村']} {ka}が{how}で{word}と回答"
            r["確認日"] = date
            r["確認方法"] = "問い合わせ"
            # 「無いことは確認していない」は、回答で無いと分かったので外す
            old = r["備考"].replace(NASHI_NOTE, "").replace("無いことは確認していない", "").replace("。。", "。").strip("。 ")
            r["備考"] = FULL.get((code, kind)) or "。".join(x for x in (note, old) if x)
        elif (code, kind) in FULL:
            r["備考"] = FULL[(code, kind)]
        else:
            r["備考"] = "。".join(x for x in (r["備考"].replace(NASHI_NOTE, "公式ページに記載が見つからなかった").strip("。 "), note) if x)
    assert len(ids) == len(ANS), set(ANS) - set(ids)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    tpath = BASE / "toiawase.csv"
    with tpath.open(encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        tcols, trows = rd.fieldnames, list(rd)
    n = 0
    for t in trows:
        key = (t["市町村コード"], t["種類"].strip())
        if key not in ANS:
            continue
        date, ka, how, ans, new, _ = ANS[key]
        t["担当課"] = ka
        t["回答"] = f"{ans}(回答日 {date})"
        t["公開の可否"] = KOUKAI.get(key, "可(差し支えの申し出なし)")
        t["反映したid"] = ids[key]
        n += 1
    assert n == len(ANS), n
    with tpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tcols, lineterminator="\n")
        w.writeheader()
        w.writerows(trows)
    print(f"seido.csv: {sum(1 for v in ANS.values() if v[4] == 'なし')} 行をなしに、ほかは備考だけ。toiawase.csv: {n} 行")


if __name__ == "__main__":
    main()
