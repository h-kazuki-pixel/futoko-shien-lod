"""照合。データの項目が、出典のページに実際にあるかをコードで確かめる。

やり方は2つ。
1. 根拠の箇所(短い語句)が、ページの文字列にそのままあるか
2. 金額・対象・開始に出てくる「数字と単位」が、ページにもあるか

表記のゆれ(全角と半角、カンマ、「3万円」と「30,000円」、令和と西暦、
「2分の1」と「1/2」)はそろえてから比べる。合わないものは公開データに入れず、
人が見る一覧に回す。照合は「ページに無い数字を載せない」ための網で、
「意味が正しい」ことまでは保証しない(そこは検証役と人の再確認が見る)。
"""

from __future__ import annotations

import re
import unicodedata

_KANJI_DIGIT = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
_ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}

# 数字のあとに来る単位(汎用)。長いものを先に。
_UNITS = ["か月", "ヶ月", "カ月", "ケ月", "箇月", "年生", "日", "回", "名", "人", "歳", "校", "時間", "分", "割", "%"]


def normalize(text: str) -> str:
    """全角半角をそろえ、空白と数字のカンマを取る。"""
    t = unicodedata.normalize("NFKC", text)
    t = re.sub(r"(?<=\d),(?=\d{3})", "", t)
    t = re.sub(r"\s+", "", t)
    t = t.replace("〜", "~").replace("～", "~")
    return t


def tokens(text: str) -> set[str]:
    """文字列から「数字と単位」を取り出し、表記をそろえた印にして返す。"""
    t = normalize(text)
    found: set[str] = set()

    def take(pattern: str, make) -> None:
        nonlocal t
        for m in re.finditer(pattern, t):
            tok = make(m)
            if tok:
                found.add(tok)
        t = re.sub(pattern, "〓", t)

    # 分数(補助率)。「2分の1」「二分の一」「1/2」→ ratio:1/2
    for k, d in _KANJI_DIGIT.items():
        t = re.sub(rf"{k}(?=分の)", d, t)
        t = re.sub(rf"(?<=分の){k}", d, t)
    take(r"(\d+)分の(\d+)", lambda m: f"ratio:{m.group(2)}/{m.group(1)}")
    take(r"(?<![\d/])(\d+)/(\d+)(?![\d/])", lambda m: f"ratio:{m.group(1)}/{m.group(2)}")

    # 金額 → 円の整数
    def man(m: re.Match) -> str:
        value = float(m.group(1)) * 10000
        if m.group(2):
            rest = m.group(2)
            value += int(rest[:-1]) * 1000 if rest.endswith("千") else int(rest)
        return f"yen:{int(round(value))}"

    take(r"(\d+(?:\.\d+)?)万(\d+千?)?円", man)
    take(r"(\d+)千円", lambda m: f"yen:{int(m.group(1)) * 1000}")
    take(r"(\d+)円", lambda m: f"yen:{int(m.group(1))}")

    # 年 → 西暦
    def era(m: re.Match) -> str:
        n = 1 if m.group(2) == "元" else int(m.group(2))
        return f"year:{_ERA_BASE[m.group(1)] + n}"

    take(r"(令和|平成|昭和)(\d+|元)年度?", era)
    take(r"(?<!\d)((?:19|20)\d\d)年度?", lambda m: f"year:{m.group(1)}")

    # 月日
    take(r"(\d+)月(\d+)日", lambda m: f"md:{int(m.group(1))}-{int(m.group(2))}")
    take(r"(?<!\d)(\d{1,2})月(?!額)", lambda m: f"month:{int(m.group(1))}")

    # そのほかの「数字+単位」
    unit_alt = "|".join(re.escape(u) for u in _UNITS)
    for m in re.finditer(rf"(\d+(?:\.\d+)?)({unit_alt}|年)", t):
        unit = m.group(2)
        if unit in ("ヶ月", "カ月", "ケ月", "箇月"):
            unit = "か月"
        found.add(f"n:{m.group(1)}{unit}")
    return found


# 照合する項目。備考は自由記述なので対象にしない。
CHECK_FIELDS = ("金額", "対象", "開始", "根拠の箇所")


def _source2_fields(row: dict[str, str]) -> set[str]:
    return {x.strip() for x in (row.get("出典2の項目") or "").split("|") if x.strip()}


def record_tokens(row: dict[str, str], part: int = 1) -> set[str]:
    """照合で見る数字の印。

    第2の出典(出典URL_2)があるとき、「出典2の項目」に挙げた項目は第2の出典のページで、
    それ以外の項目は出典のページで見る。part=1 は出典、part=2 は第2の出典。
    """
    in2 = _source2_fields(row)
    basis_key = "根拠の箇所" if part == 1 else "根拠の箇所_2"
    want: set[str] = set()
    for key in CHECK_FIELDS:
        if key == "根拠の箇所":
            want |= tokens(row.get(basis_key, "") or "")
        elif (key in in2) == (part == 2):
            want |= tokens(row.get(key, "") or "")
    if (row.get("上限額_円") or "").strip() and (("上限額_円" in in2) == (part == 2)):
        want.add(f"yen:{int(row['上限額_円'])}")
    if (row.get("補助率") or "").strip() and (("補助率" in in2) == (part == 2)):
        want.add(f"ratio:{row['補助率'].strip()}")
    return want


def note_tokens_missing(row: dict[str, str], *page_texts: str) -> list[str]:
    """備考の「数字と単位」のうち、どのページにも無いもの(弱い所5)。

    shougou(fetch.run)では、ここに挙がる数字があれば不一致にする。第2の出典があれば、両方のページを合わせて見る。
    定期的な取り直し(torinaoshi)は出典ごとに照合するので、備考の数字は見ない(ページの文字の変化で気づく)。
    """
    have: set[str] = set()
    for t in page_texts:
        have |= tokens(t)
    return sorted(tokens(row.get("備考", "") or "") - have)


def name_parts_missing(name: str, page_norm: str) -> list[str]:
    """制度名を括弧や中点で区切り、ページに無い部分を返す。

    制度名は読む側がまとめて付けることがあるので、合否には使わない。
    人が見るときの手がかりとして結果に出す。
    """
    parts = [x for x in re.split(r"[()「」『』・、\s]+", unicodedata.normalize("NFKC", name)) if x]
    return [x for x in parts if normalize(x) not in page_norm]


def collate(row: dict[str, str], page_text: str, part: int = 1) -> dict:
    """1件を、出典のページの文字列と照合する。

    part=2 は第2の出典(出典URL_2)のページとの照合。根拠の箇所_2 と、「出典2の項目」に挙げた項目の数字を見る。
    制度名が「出典2の項目」にあれば、名前の部分(合否には使わない)も第2の出典のページで見る。
    """
    page_norm = normalize(page_text)
    basis = normalize(row.get("根拠の箇所" if part == 1 else "根拠の箇所_2", "") or "")
    literal_ok = bool(basis) and basis in page_norm
    missing = sorted(record_tokens(row, part) - tokens(page_text))
    name_here = ("制度名" in _source2_fields(row)) == (part == 2)
    return {
        "id": row.get("id", ""),
        "根拠の箇所がページにある": literal_ok,
        "ページに無い数字": missing,
        "ページに無い名前の部分": name_parts_missing(row.get("制度名", "") or "", page_norm) if name_here else [],
        "一致": literal_ok and not missing,
    }


PREFECTURE = "福岡県"


def collate_absence(row: dict[str, str], page_text: str) -> dict:
    """「なし」の照合。出典が、設置校などを並べた公式の一覧であるときに使う。

    1. 根拠の箇所がページにある(狙った一覧のページであることの確認)
    2. 市町村が管理する学校の印(「市町村名+立」「市町村名+教育委員会」)がページに無い
    3. 「県名+市町村名」(設置場所)がページに出てこない。
       ただし、根拠の箇所に市町村以外が設置する学校の名前(「県立」を含む)を挙げたときは、
       その学校の分の1回だけ出てよい(例: 小郡市には県立高校のコースがある)
    の3つがそろえば一致。一覧に載っていないことしか分からない点に注意する。
    """
    page_norm = normalize(page_text)
    basis = normalize(row.get("根拠の箇所", "") or "")
    literal_ok = bool(basis) and basis in page_norm
    town = normalize(row.get("市町村", "") or "")
    own = bool(town) and any(normalize(town + mark) in page_norm for mark in ("立", "教育委員会"))
    place = normalize(PREFECTURE) + town
    allowed = 1 if (literal_ok and "県立" in basis) else 0
    place_count = page_norm.count(place)
    problems = []
    if own:
        problems.append("一覧に市町村が管理する学校の印がある")
    if place_count > allowed:
        problems.append("一覧に市町村名がある")
    return {
        "id": row.get("id", ""),
        "根拠の箇所がページにある": literal_ok,
        "ページに無い数字": problems,
        "ページに無い名前の部分": [],
        "一致": literal_ok and not problems,
    }
