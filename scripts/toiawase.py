"""市町への問い合わせの一覧を、データから作る。

「確認できず」と未着手のマスを市町ごとに拾い、聞くことを並べる。
使い方: python scripts/toiawase.py   (docs/問い合わせ.md を書き換える)
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

KINDS = ["fs-hojo", "shien-center", "online", "shusseki"]  # 学びの多様化学校は国の一覧で確かめるので聞かない

# 聞き方の決まり: 1問は1文で、「ある」「ない」で答えられる形にする。返事を書く手間を小さくするため。
QUESTION = {
    "fs-hojo": "フリースクール等を利用する児童生徒の保護者に、利用料を補助する制度はありますか。",
    "shien-center": "教育支援センター(適応指導教室)のように、不登校の児童生徒が学校の外で通える教室はありますか。",
    "online": "市(町)が行う、不登校の児童生徒向けのオンラインの支援(学習や居場所)はありますか。県の事業は除きます。",
    "shusseki": "フリースクール等での活動を出席扱いにする基準(要綱やガイドライン)、または出席扱いにしている施設の一覧を、公表されていますか。",
}

# 公式サイトに手がかりがある市町は、決まった質問の代わりに、手がかりに沿って聞く
REPLACE = {
    ("40342", "shien-center"): "「篠栗町教育支援センター」には、不登校の児童生徒が通える教室がありますか(相談の窓口だけでしょうか)。",
    ("40349", "shien-center"): "教育相談室「ぽると」のサポートルームは、不登校の児童生徒が通える教室(教育支援センターにあたるもの)ですか。",
}

# 種類の境目など、「あり」の行でも確かめたいこと
EXTRA = {
    "40130": ["教育支援センターの「すまいる学級」は、在籍校に関係なく通える教室ですか(小学校の建物の中にあるため、おたずねします)。",
              # 11/17 に足した(案内の PDF が 404 で、2つ目の出典に入れ直せないため)
              "「オンラインルーム」の案内と、百道松原中学校の生徒募集案内のPDFが、不登校支援のページから開けませんでした。新しい掲載場所はありますか。"],
    "40224": ["出席扱いのガイドラインにある「別紙の一覧表」は、公表されていますか。"],
}

SITE = "https://h-kazuki-pixel.github.io/futoko-shien-lod/"
SUBJECT = "不登校支援の制度についての問い合わせ({n}点)"


def letter(name: str, questions: list[str], sender: str = "◯◯", contact: str = "◯◯") -> str:
    """1市町ぶんの本文。短くして、返事を書きやすくする。応募する大会の名前や、ライセンスは書かない。"""
    unit = "町" if name.endswith("町") else "市"
    qs = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
    return f"""{name}教育委員会 ご担当者様

福岡市在住の{sender}と申します。福岡県内の市町村ごとの不登校支援の制度を、保護者が見比べられる一覧にまとめ、無料で公開しています。
{SITE}

貴{unit}の公式サイトでは分からなかった点が{len(questions)}点あります。「ある」「ない」の一言でかまいませんので、お教えいただけますでしょうか。

{qs}

「ある」場合は、名前か案内のページも教えていただけると助かります。
お答えは、回答日と担当課名を付けて上の一覧に載せる予定です(ご担当の方のお名前は載せません)。差し支えがあれば、お知らせください。

お忙しいところ恐れ入ります。11月中にお返事をいただけますと幸いです。

{contact}"""


def questions_for(code: str, cell: dict) -> list[str]:
    qs = []
    for k in KINDS:
        r = cell.get((code, k))
        if r is None or r["状態"] == "確認できず":
            qs.append(REPLACE.get((code, k), QUESTION[k]))
    return qs + EXTRA.get(code, [])


LETTER = """## 文面(メール・問い合わせフォーム用)

件名は「不登校支援の制度についての問い合わせ(◯点)」。本文は、下の「市町ごとの文面」にある(氏名と連絡先だけ入れる)。

文面の決まり

- 短くする。名乗り、何のためか(1文と公開ページの URL)、質問、回答を載せることの断り、だけ
- 質問は「ある」「ない」で答えられる形にする
- 回答を担当課名つきで載せることは、必ず書く。応募する大会の名前や、ライセンスは書かない
- 返事の目安を書く

## 電話で聞くとき

1. 名乗る: 「福岡市に住んでいる◯◯です。県内の市町村の不登校支援の制度を一覧にするオープンデータを作っています」
2. 質問を1つずつ聞く。「ある」「ない」「分からない」を聞き分ける。「分からない」「担当が違う」は「なし」にしない
3. 「ある」なら、制度名と、載っているページや要綱の場所を聞く
4. 最後に、回答を担当課名つきで公開データに載せる予定だと伝え、差し支えがあるかを聞く
5. 切ったらすぐ、日付・担当課・回答を `data/toiawase.csv` に書く

## 回答の記録と、データへの反映

- 記録は `data/toiawase.csv`。列: 日付、市町村コード、市町村、担当課、方法(電話/メール/フォーム)、種類、回答、公開の可否、反映した id
- 担当の方の個人名は書かない
- 「ない」と答えてもらえた種類は、状態を「なし」にし、「なしの根拠」に「日付・担当課・方法」を書く。確認方法は「問い合わせ」
- 「ある」と答えてもらえた種類は、教わったページを読んで「あり」の候補にし、照合に通す。ページが無い制度は、要綱の場所を聞く
- 回答が無い、分からないと言われた種類は「確認できず」のまま。備考に、問い合わせた日を書く
- 「載せることに差し支えがある」と言われたときは、回答をデータに使わず、「確認できず」のままにする。公開の可否の列に「差し支えあり」と書く
"""


def build() -> str:
    rows = schema.load("data/seido.csv")
    areas = [a for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"]
    cell = {(r["市町村コード"], schema.KIND_BY_LABEL[r["制度の種類"]]): r for r in rows}
    out = [
        "# 市町への問い合わせ",
        "",
        f"このファイルは `scripts/toiawase.py` がデータから作る({dt.date.today().isoformat()} 時点)。手で直さない。",
        "",
        "公式サイトを読んでも分からなかったことを、市町に聞く。目的は、「確認できず」を「あり」か「なし」に変えること。"
        "「なし」は、市町が無いと答えた記録があって初めて書ける。",
        "",
        LETTER,
        "## 市町ごとの文面",
        "",
    ]
    total = 0
    for a in areas:
        code, name = a["市町村コード"], a["市町村"]
        unit = "町" if name.endswith("町") else "市"
        qs = [q.replace("市(町)", unit) for q in questions_for(code, cell)]
        if not qs:
            continue
        total += len(qs)
        out.append(f"### {name}({len(qs)}問)")
        out.append("")
        out.append("件名: " + SUBJECT.format(n=len(qs)))
        out.append("")
        out.append("```")
        out.append(letter(name, qs, contact="◯◯(氏名)\n◯◯(連絡先)"))
        out.append("```")
        out.append("")
    out.insert(6, f"いま聞くことは、福岡都市圏の17市町で合わせて{total}問。")
    out.insert(7, "")
    return "\n".join(out)


def main() -> int:
    Path("docs/問い合わせ.md").write_text(build(), encoding="utf-8")
    print(build().split("## 市町ごとの文面")[0].splitlines()[6])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
