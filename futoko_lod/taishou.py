"""「なし」の照合の対照。学びの多様化学校の「なし」が、空振りで通っていないかを確かめる。

「なし」の照合(collate_absence)は、「福岡県+市町村名」が一覧に無いことを見る。
もし一覧が「福岡県糟屋郡宇美町」のように郡を入れて書いていれば、郡部の町村は必ず「無い」になり、照合の意味が無くなる。
そこで、一覧を1回取りに行き、市町村ごとに次の3つを数える(ページの本文は出さない。出すのは有無だけ)。
  A 「福岡県+名前」がある   B 名前だけならある   C 「福岡県+◯◯郡+名前」がある
見る所:
  1. 一覧に学校がある市町村(状態が あり・予定)で A が立つか。立たないなら、「なし」の照合は当てにならない
  2. 「なし」の行で B か C が立つものが無いか。あれば、人が一覧を見る

GitHub Actions で回す。使い方: python -m futoko_lod.taishou [--summary ファイル]
"""

from __future__ import annotations

import argparse
import re

from . import collate, fetch, schema

KIND = "学びの多様化学校"


def check(rows: list[dict[str, str]], page_text: str) -> list[dict[str, str]]:
    page = collate.normalize(page_text)
    out = []
    for r in rows:
        if r["制度の種類"] != KIND or r["市町村コード"] == "40000":
            continue
        name = collate.normalize(r["市町村"])
        a = collate.normalize(collate.PREFECTURE) + name in page
        c = bool(re.search(re.escape(collate.normalize(collate.PREFECTURE)) + r"[^\d、。]{1,5}郡" + re.escape(name), page))
        b = name in page
        if r["状態"] == "なし":
            verdict = "人が見る" if (b or c) else "空振りではない見込み"
        else:
            verdict = "照合の形で拾える" if a else ("照合の形では拾えない" if (b or c) else "一覧に名前が無い")
        out.append({"id": r["id"], "市町村": r["市町村"], "状態": r["状態"], "A": a, "B": b, "C": c, "見立て": verdict})
    return out


def markdown(results: list[dict[str, str]], fetched: str) -> str:
    mark = {True: "ある", False: "無い"}
    lines = ["## 「なし」の照合の対照(学びの多様化学校)", "", f"一覧の取得: {fetched}", "",
             "| id | 市町村 | 状態 | A 福岡県+名前 | B 名前だけ | C 福岡県+郡+名前 | 見立て |", "|---|---|---|---|---|---|---|"]
    shown = [r for r in results if r["状態"] != "なし" or r["B"] or r["C"]]
    lines += [f"| {r['id']} | {r['市町村']} | {r['状態']} | {mark[r['A']]} | {mark[r['B']]} | {mark[r['C']]} | {r['見立て']} |" for r in shown]
    nashi = [r for r in results if r["状態"] == "なし"]
    lines += ["", f"「なし」の行は {len(nashi)}。うち、名前だけ(B)か郡つき(C)で一覧にあるものは {sum(r['B'] or r['C'] for r in nashi)}。"
              "表には、状態が「なし」でない行と、B か C が立った「なし」の行だけを出している。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="")
    args = ap.parse_args()
    rows = schema.load("data/seido.csv")
    urls = {r["出典URL"] for r in rows if r["制度の種類"] == KIND and r["状態"] == "なし" and r["出典URL"]}
    if len(urls) != 1:
        print(f"「なし」の出典が1つではない: {sorted(urls)}")
        return 1
    page = fetch.fetch(urls.pop())
    if page["text"] is None:
        print(f"一覧を取得できなかった: {page.get('結果')}")
        return 1
    md = markdown(check(rows, page["text"]), f"{page['取得日時']} {page['結果']}")
    print(md)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
