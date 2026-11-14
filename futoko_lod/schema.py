"""データの形(スキーマ)と、読み込み時の検査。

1件 = 1市町村の1制度。検査に通らない行があれば、読み込み全体を失敗させる。
決まりの説明は docs/データの項目.md にある。
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

COLUMNS = [
    "id",
    "市町村コード",
    "市町村",
    "制度の種類",
    "補助の形",
    "状態",
    "制度名",
    "対象",
    "金額",
    "上限額_円",
    "補助率",
    "開始",
    "出典URL",
    "出典名",
    "根拠の箇所",
    "要綱の状況",
    "要綱URL",
    "探した場所",
    "なしの根拠",
    "備考",
    "確認日",
    "確認方法",
]

# 制度の種類。キーは id の後半に使う。
KINDS = {
    "fs-hojo": "フリースクール等の利用料の補助(保護者向け)",
    "shien-center": "教育支援センター(校外)",
    "tayouka": "学びの多様化学校",
    "online": "オンラインでの公的な支援",
    "shusseki": "出席扱いの要綱・施設一覧の公表",
    "fs-unei": "施設への補助(設置者向け)",
}
KIND_BY_LABEL = {label: slug for slug, label in KINDS.items()}

# 保護者向けの制度ではない種類。都道府県の行にだけ使う。
PREF_ONLY_KINDS = {"fs-unei"}

STATUSES = {
    "あり": "ari",
    "予定": "yotei",
    "なし": "nashi",
    "確認できず": "kakunin-dekizu",
}

# 補助の形。毎月の補助と1回きりの補助を取り違えないために持つ。
FORMS = {
    "毎月": "maitsuki",
    "利用開始時の1回": "kaishiji-1kai",
    "年度ごと": "nendo-goto",
    "その他": "sonota",
}

METHODS = {
    "機械の読み取り": "kikai",
    "人の読み取り": "hito-yomitori",  # 人が公式ページを見て項目にした(機械の読み取りを経ていない)
    "人の再確認": "hito",  # 機械の読み取りを、人が公式ページと見比べた
    "問い合わせ": "toiawase",
}

GUIDELINE_STATES = {"", "取得済み", "リンクあり・URL未取得", "ページにリンクなし"}

SEP = " | "  # 「探した場所」に URL を複数書くときの区切り

MAX_BASIS = 40  # 根拠の箇所は短い語句だけ(文章を写さない)
MAX_TEXT = 140  # 対象・金額・備考などの上限

# 地方公共団体・国の公式サイトとみなすドメイン。
# 1) lg.jp / go.jp  2) 福岡県内の地域型ドメイン(city.◯◯.fukuoka.jp など)
# これに当てはまらない公式サイトは data/koushiki_domain.csv に、確かめた根拠つきで足す。
_OFFICIAL_SUFFIX = (".lg.jp", ".go.jp")
_REGIONAL = re.compile(r"(^|\.)(pref|city|town|vill)\.([a-z0-9-]+\.)?fukuoka\.jp$")


@dataclass(frozen=True)
class Problem:
    id: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"[{self.id}] {self.rule}: {self.message}"


class DataError(Exception):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


def is_official_url(url: str, extra_domains: frozenset[str] = frozenset()) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host.endswith(_OFFICIAL_SUFFIX):
        return True
    if _REGIONAL.search(host):
        return True
    return any(host == d or host.endswith("." + d) for d in extra_domains)


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def check_row(row: dict[str, str], extra_domains: frozenset[str] = frozenset()) -> list[Problem]:
    """1行の検査。問題の一覧を返す(空なら合格)。"""
    rid = row.get("id", "") or "(idなし)"
    out: list[Problem] = []

    def bad(rule: str, message: str) -> None:
        out.append(Problem(rid, rule, message))

    def v(key: str) -> str:
        return (row.get(key) or "").strip()

    missing_cols = [c for c in COLUMNS if c not in row]
    if missing_cols:
        bad("列", f"列が足りない: {missing_cols}")
        return out

    code, kind_label, status = v("市町村コード"), v("制度の種類"), v("状態")

    if not re.fullmatch(r"40\d{3}", code):
        bad("市町村コード", f"福岡県の5桁のコードではない: {code!r}")
    if not v("市町村"):
        bad("市町村", "名前が空")

    slug = KIND_BY_LABEL.get(kind_label)
    if slug is None:
        bad("制度の種類", f"決めた種類にない: {kind_label!r}")
    else:
        if not re.fullmatch(rf"{re.escape(code)}-{re.escape(slug)}(-\d+)?", v("id")):
            bad("id", f"id は「{code}-{slug}」(同じ種類が複数あれば -2 など)にする")
        is_pref = code == "40000"
        if slug in PREF_ONLY_KINDS and not is_pref:
            bad("制度の種類", "設置者向けの補助は県の行にだけ使う。保護者向けと混ぜない")

    if status not in STATUSES:
        bad("状態", f"あり/予定/なし/確認できず のどれかにする: {status!r}")

    if v("確認方法") not in METHODS:
        bad("確認方法", f"機械の読み取り/人の読み取り/人の再確認/問い合わせ のどれかにする: {v('確認方法')!r}")
    if not _valid_date(v("確認日")):
        bad("確認日", f"YYYY-MM-DD で書く: {v('確認日')!r}")

    form = v("補助の形")
    if form and form not in FORMS:
        bad("補助の形", f"決めた形にない: {form!r}")

    # --- 状態ごとの決まり(この作品の核) ---
    if status in ("あり", "予定"):
        for key in ("出典URL", "根拠の箇所", "確認日", "制度名"):
            if not v(key):
                bad("出典の必須", f"「{status}」なのに {key} が空。出典・根拠の箇所・確認日がそろわないと保存できない")
        if slug == "fs-hojo" and not form:
            bad("補助の形", "利用料の補助は、毎月か1回きりかを必ず書く")
    elif status == "なし":
        if not v("なしの根拠"):
            bad("なしの根拠", "「なし」は、市町村が無いと答えた記録か公式の資料がある場合だけ。見つからなかっただけなら「確認できず」")
        if v("確認方法") == "機械の読み取り" and not (v("出典URL") and v("根拠の箇所")):
            bad("なしの根拠", "機械の読み取りで「なし」とするなら、無いと分かる公式の資料の URL と、その資料を示す根拠の箇所が要る")
        for key in ("制度名", "金額", "上限額_円", "補助率", "開始"):
            if v(key):
                bad("なし", f"「なし」なのに {key} に中身がある")
    elif status == "確認できず":
        if not v("探した場所"):
            bad("探した場所", "「確認できず」は、どこを探したかを書く")
        for key in ("制度名", "金額", "上限額_円", "補助率", "開始", "出典URL", "根拠の箇所"):
            if v(key):
                bad("確認できず", f"「確認できず」なのに {key} に中身がある")

    # --- 出典は公式サイトだけ ---
    for key in ("出典URL", "要綱URL"):
        if v(key) and not is_official_url(v(key), extra_domains):
            bad("公式サイト", f"{key} が公式サイトのドメインではない: {v(key)}")
    for place in filter(None, (p.strip() for p in v("探した場所").split(SEP.strip()))):
        if place.startswith("http") and not is_official_url(place, extra_domains):
            bad("公式サイト", f"探した場所が公式サイトのドメインではない: {place}")

    # --- 要綱 ---
    gstate = v("要綱の状況")
    if gstate not in GUIDELINE_STATES:
        bad("要綱の状況", f"決めた値にない: {gstate!r}")
    if (gstate == "取得済み") != bool(v("要綱URL")):
        bad("要綱の状況", "「取得済み」と 要綱URL は、両方あるか両方ないかにする")

    # --- 項目の形 ---
    if v("上限額_円") and not re.fullmatch(r"[1-9]\d*", v("上限額_円")):
        bad("上限額_円", f"円の整数で書く(カンマなし): {v('上限額_円')!r}")
    if v("補助率") and not re.fullmatch(r"[1-9]\d*/[1-9]\d*", v("補助率")):
        bad("補助率", f"1/2 のように書く: {v('補助率')!r}")
    if status in ("あり", "予定") and v("上限額_円") and v("根拠の箇所"):
        # 金額の数字そのものを根拠の箇所に含める。別の数字を上限額と取り違えにくくする
        from .collate import tokens

        if f"yen:{v('上限額_円')}" not in tokens(v("根拠の箇所")):
            bad("上限額_円", "上限額の数字が根拠の箇所の中に無い。金額そのものを含む語句を根拠にする")
    if len(v("根拠の箇所")) > MAX_BASIS:
        bad("根拠の箇所", f"{MAX_BASIS}字まで。公式ページの文章を写さない")
    for key in ("対象", "金額", "開始", "備考"):
        if len(v(key)) > MAX_TEXT:
            bad(key, f"{MAX_TEXT}字まで。文章を写さず、項目に直す")

    return out


def check_rows(
    rows: list[dict[str, str]],
    extra_domains: frozenset[str] = frozenset(),
    areas: dict[str, str] | None = None,
) -> list[Problem]:
    """areas は市町村の台帳(コード→名前)。渡されたら、コードと名前が台帳と合うかも見る。"""
    problems: list[Problem] = []
    seen: set[str] = set()
    for row in rows:
        problems.extend(check_row(row, extra_domains))
        rid = row.get("id", "")
        if areas is not None:
            code, name = (row.get("市町村コード") or "").strip(), (row.get("市町村") or "").strip()
            if code not in areas:
                problems.append(Problem(rid, "市町村の台帳", f"コード {code} が data/shichoson.csv に無い"))
            elif areas[code] != name:
                problems.append(Problem(rid, "市町村の台帳", f"コード {code} の名前は台帳では {areas[code]}。データは {name}"))
        if rid in seen:
            problems.append(Problem(rid, "id", "同じ id が2回ある"))
        seen.add(rid)
    return problems


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_csv(path: str | Path, rows: list[dict[str, str]], columns: list[str] = COLUMNS) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in columns})


def load_extra_domains(path: str | Path = "data/koushiki_domain.csv") -> frozenset[str]:
    p = Path(path)
    if not p.exists():
        return frozenset()
    return frozenset(r["ドメイン"].strip().lower() for r in read_csv(p) if r.get("ドメイン"))


def load_areas(path: str | Path = "data/shichoson.csv") -> dict[str, str] | None:
    p = Path(path)
    if not p.exists():
        return None
    return {r["市町村コード"].strip(): r["市町村"].strip() for r in read_csv(p)}


def load(path: str | Path, extra_domains: frozenset[str] | None = None) -> list[dict[str, str]]:
    """データを読む。1件でも検査に落ちれば DataError。"""
    rows = read_csv(path)
    if extra_domains is None:
        extra_domains = load_extra_domains(Path(path).parent / "koushiki_domain.csv")
    problems = check_rows(rows, extra_domains, load_areas(Path(path).parent / "shichoson.csv"))
    if problems:
        raise DataError(problems)
    return rows


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    path = args[0] if args else "data/seido.csv"
    try:
        rows = load(path)
    except DataError as e:
        print(f"検査に落ちた({len(e.problems)}件の問題):")
        print(e)
        return 1
    print(f"{path}: {len(rows)}件、検査に通った")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
