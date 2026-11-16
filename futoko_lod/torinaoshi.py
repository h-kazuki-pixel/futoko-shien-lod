"""定期的な取り直し。出典のページと、探した場所のページを取り直し、前回から変わった所を残す。

GitHub Actions の `torinaoshi` で週1回まわす。やることは3つ。
1. 「あり」「予定」と、出典のある「なし」は、出典を取り直して照合する(shougou と同じ照合)
2. 「確認できず」は、探した場所のページを取り直す(制度が載ったかもしれないページを見逃さないため)
3. 前回の記録と比べ、変わった所を1行ずつ足す

残すもの(ページの本文は残さない。残すのは、文字列をそろえてから取った印と、データの側の語句・数字がページにあったかだけ):
  data/torinaoshi/saishin.csv  いちばん新しい取り直しの結果。行(id)とページ(URL)の組ごとに1行
  data/torinaoshi/sabun.csv    変わった所。足していくだけで、消さない

何が変わったか(弱い所 取2): 出典では、照合に使う語句と数字(根拠の箇所、金額・対象・開始・備考の数字)の一つ一つが
ページにまだあるかを毎回残す。探した場所では、種類の語(「教育支援センター」「出席扱い」など)がページに何回出るかを残す。
本文は残さないので、ページのどの文が変わったかまでは分からない。分かるのは、データの側の語句・数字が消えたか・戻ったかと、
種類の語が増えたか・減ったかまで。

変わった所は2つの重さに分ける。
  要確認    照合が一致でなくなった / 取得できなくなった(2回試して2回とも) / 「確認できず」の行の探した場所で、その行の種類の語が増えた
  記録のみ  ページの文字が変わった(照合は一致のまま) / 合わない語句・数字が変わった / 探した場所のページの文字や種類の語の数が変わった / 元に戻った
公開データ(data/seido.csv)は、ここでは書き換えない。直すかどうかは、人が出典を見て決める。

使い方: python -m futoko_lod.torinaoshi [--issue 知らせの文面を書き出すファイル] [--summary まとめのファイル]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import re
import time
from pathlib import Path
from typing import Callable

from . import collate as collate_mod
from . import fetch as fetch_mod
from . import schema

DIR = Path("data/torinaoshi")
SAISHIN = DIR / "saishin.csv"
SABUN = DIR / "sabun.csv"
SAISHIN_COLUMNS = ["id", "役割", "URL", "取得日時", "取得", "判定", "本文の印", "照合で見たもの", "合わなかったもの", "種類の語の数"]
SABUN_COLUMNS = ["日付", "重さ", "変わった所", "id", "役割", "URL", "前", "後"]
RETRY_WAIT_SEC = 30

SOURCE, SOURCE2, PLACE = "出典", "出典2", "探した場所"
HEAVY, LIGHT = "要確認", "記録のみ"
LIST_SEP = " | "

BASIS = "根拠の箇所"
# 「なし」の照合(collate_absence)で見るもの
ABSENCE_ITEMS = (BASIS, "一覧に市町村が管理する学校の印が無い", "一覧に県名+市町村名が無い")
ABSENCE_PROBLEMS = {"一覧に市町村が管理する学校の印がある": ABSENCE_ITEMS[1], "一覧に市町村名がある": ABSENCE_ITEMS[2]}

# 探した場所で数える、種類の語。制度が載ったかもしれないことの手がかり(載ったと言えるのは、人が見てから)
KIND_WORDS = {
    "fs-hojo": ("フリースクール", "民間施設"),
    "shien-center": ("教育支援センター", "適応指導教室"),
    "tayouka": ("学びの多様化学校", "不登校特例校"),
    "online": ("オンライン", "メタバース"),
    "shusseki": ("出席扱い",),
}
ALL_KIND_WORDS = tuple(dict.fromkeys(w for ws in KIND_WORDS.values() for w in ws))


def token_label(tok: str) -> str:
    """照合の数字の印を、人が読める形にする(yen:10000 → 10000円)。"""
    kind, _, value = tok.partition(":")
    if kind == "yen":
        return f"{value}円"
    if kind == "ratio":
        return value
    if kind == "year":
        return f"{value}年"
    if kind == "md":
        m, d = value.split("-")
        return f"{m}月{d}日"
    if kind == "month":
        return f"{value}月"
    if kind == "n":
        return value
    return tok


def collation_items(row: dict[str, str], role: str, page_text: str) -> tuple[list[str], list[str]]:
    """照合で見たものと、そのうち合わなかったもの。データの側の語句・数字だけで、ページの文は入らない。"""
    if role == SOURCE and row["状態"] == "なし":
        c = collate_mod.collate_absence(row, page_text)
        missing = ([BASIS] if not c["根拠の箇所がページにある"] else []) + [ABSENCE_PROBLEMS.get(x, x) for x in c["ページに無い数字"]]
        return list(ABSENCE_ITEMS), missing
    part = 1 if role == SOURCE else 2
    c = collate_mod.collate(row, page_text, part=part)
    nums = sorted(collate_mod.record_tokens(row, part))
    items = [BASIS] + [token_label(x) for x in nums]
    missing = ([BASIS] if not c["根拠の箇所がページにある"] else []) + [token_label(x) for x in c["ページに無い数字"]]
    return items, missing


def kind_word_counts(page_text: str) -> str:
    norm = collate_mod.normalize(page_text)
    return LIST_SEP.join(f"{w}:{norm.count(collate_mod.normalize(w))}" for w in ALL_KIND_WORDS)


def parse_counts(text: str) -> dict[str, int]:
    out = {}
    for part in filter(None, (x.strip() for x in text.split(LIST_SEP.strip()))):
        w, _, n = part.rpartition(":")
        out[w] = int(n)
    return out


def split_list(text: str) -> list[str]:
    return [x.strip() for x in (text or "").split(LIST_SEP.strip()) if x.strip()]


def text_mark(text: str) -> str:
    """ページの文字列の印。空白や全角半角のゆれをそろえてから取る。本文そのものは残さない。"""
    return hashlib.sha256(collate_mod.normalize(text).encode("utf-8")).hexdigest()[:16]


def targets(rows: list[dict[str, str]]) -> list[tuple[dict[str, str], str, str]]:
    """取り直す(行, 役割, URL)の並び。"""
    out = []
    for row in rows:
        if row["出典URL"]:
            out.append((row, SOURCE, row["出典URL"]))
        if (row.get("出典URL_2") or "").strip():
            out.append((row, SOURCE2, row["出典URL_2"].strip()))
        for place in (p.strip() for p in row["探した場所"].split(schema.SEP.strip())):
            if place:
                out.append((row, PLACE, place))
    return out


def collect(
    rows: list[dict[str, str]],
    fetcher: Callable[[str], dict] = fetch_mod.fetch,
    interval: float = fetch_mod.INTERVAL_SEC,
    retry_wait: float = RETRY_WAIT_SEC,
) -> list[dict[str, str]]:
    pages: dict[str, dict] = {}
    results = []
    for row, role, url in targets(rows):
        if url not in pages:
            if pages:
                time.sleep(interval)
            page = fetcher(url)
            # たまたまの失敗で騒がないよう、取得できないときは1回だけ間をあけて試し直す(robots.txt の禁止は試し直さない)
            if page["text"] is None and page.get("結果", "").startswith("取得できず"):
                time.sleep(retry_wait)
                page = fetcher(url)
            pages[url] = page
        page = pages[url]
        entry = {
            "id": row["id"], "役割": role, "URL": url,
            "取得日時": page.get("取得日時", ""), "取得": page.get("結果", ""),
            "判定": "", "本文の印": "", "照合で見たもの": "", "合わなかったもの": "", "種類の語の数": "",
        }
        if page["text"] is not None:
            entry["本文の印"] = text_mark(page["text"])
            if role in (SOURCE, SOURCE2):
                items, missing = collation_items(row, role, page["text"])
                entry["判定"] = "不一致" if missing else "一致"
                entry["照合で見たもの"] = LIST_SEP.join(items)
                entry["合わなかったもの"] = LIST_SEP.join(missing)
            else:
                entry["種類の語の数"] = kind_word_counts(page["text"])
        results.append(entry)
    _add_note_items(rows, results, pages)
    return results


NOTE_PREFIX = "備考の"


def _add_note_items(rows: list[dict[str, str]], results: list[dict[str, str]], pages: dict[str, dict]) -> None:
    """備考の数字(指定年など)も、照合で見たものに足す(弱い所5・29)。shougou と同じく、出典と第2の出典の
    どちらかのページにあればよい。両方とも取得できたときだけ見る(片方しか無いと、無いと言えない)。
    数字は、備考を裏付ける出典(「出典2の項目」に備考があれば第2の出典、無ければ出典)の行に付け、無ければ不一致にする。"""
    by_key = {(r["id"], r["役割"]): r for r in results}
    for row in rows:
        if row["状態"] == "なし" or not collate_mod.tokens(row.get("備考", "") or ""):
            continue
        urls = [u for u in (row["出典URL"], (row.get("出典URL_2") or "").strip()) if u]
        texts = [pages[u]["text"] for u in urls if u in pages]
        if not urls or len(texts) != len(urls) or any(t is None for t in texts):
            continue
        role = SOURCE2 if "備考" in schema.source2_fields(row) and len(urls) == 2 else SOURCE
        entry = by_key.get((row["id"], role))
        if entry is None:
            continue
        items = [NOTE_PREFIX + token_label(x) for x in sorted(collate_mod.tokens(row["備考"]))]
        missing = [NOTE_PREFIX + token_label(x) for x in collate_mod.note_tokens_missing(row, *texts)]
        entry["照合で見たもの"] = LIST_SEP.join(split_list(entry["照合で見たもの"]) + items)
        entry["合わなかったもの"] = LIST_SEP.join(split_list(entry["合わなかったもの"]) + missing)
        if missing:
            entry["判定"] = "不一致"


def _compare_items(p: dict[str, str], c: dict[str, str]) -> tuple[list[str], list[str], list[str]] | None:
    """前回と今回の「合わなかったもの」を、両方の回で見たものだけに絞って返す(前, 後, 今回だけ見て合わなかったもの)。
    前回の記録に項目が無い(古い形の記録)ときは None。データの側を直したり、第2の出典が取れずに備考の数字を
    見なかったりして、見るものが回ごとに違うことがある。両方で見たものだけを比べれば、取得の成否で結果が揺れない。"""
    if not p.get("照合で見たもの") or not c.get("照合で見たもの"):
        return None
    common = set(split_list(p["照合で見たもの"])) & set(split_list(c["照合で見たもの"]))
    before = [x for x in split_list(p.get("合わなかったもの", "")) if x in common]
    after = [x for x in split_list(c.get("合わなかったもの", "")) if x in common]
    only_now = [x for x in split_list(c.get("合わなかったもの", "")) if x not in common]
    return before, after, only_now


def _with_missing(judge: str, missing: str) -> str:
    return f"{judge}(合わない: {missing})" if missing else judge


def diff(prev: list[dict[str, str]], cur: list[dict[str, str]], date: str,
         statuses: dict[str, str] | None = None) -> list[dict[str, str]]:
    """前回と今回を比べる。前回に無い組(新しい行)は、変わった所に数えない。

    statuses は id → 状態。探した場所に種類の語が新しく出たとき、要確認にするのは「確認できず」の行の種類の語だけ
    (「あり」の行の探した場所は、制度がもう見つかっているので)。渡されなければ、すべての行を「確認できず」とみなす。
    """
    before = {(p["id"], p["役割"], p["URL"]): p for p in prev}
    changes: list[dict[str, str]] = []
    text_changed: dict[tuple[str, str], list[dict[str, str]]] = {}
    words_changed: dict[str, list[tuple[dict[str, str], dict[str, str]]]] = {}

    def add(weight: str, what: str, c: dict[str, str], old: str, new: str, ids: str = "") -> None:
        changes.append({"日付": date, "重さ": weight, "変わった所": what, "id": ids or c["id"],
                        "役割": c["役割"], "URL": c["URL"], "前": old, "後": new})

    for c in cur:
        p = before.get((c["id"], c["役割"], c["URL"]))
        if p is None:
            continue
        got_before, got_now = p["取得"] == "取得", c["取得"] == "取得"
        if got_before and not got_now:
            add(HEAVY, "取得できなくなった", c, p["取得"], c["取得"])
        elif not got_before and got_now:
            add(LIGHT, "取得できるようになった", c, p["取得"], c["取得"])
        elif not got_before and p["取得"] != c["取得"]:
            add(LIGHT, "取得できない理由が変わった", c, p["取得"], c["取得"])
        if not (got_before and got_now):
            continue
        cmp = _compare_items(p, c)
        if cmp is not None and cmp[0] != cmp[1]:
            before_m, after_m = cmp[0], cmp[1]
            if not before_m:
                add(HEAVY, "照合の結果が変わった", c, "一致", _with_missing("不一致", LIST_SEP.join(after_m)))
            elif not after_m:
                add(LIGHT, "照合の結果が変わった", c, _with_missing("不一致", LIST_SEP.join(before_m)), "一致")
            else:
                add(LIGHT, "合わない語句・数字が変わった(照合は不一致のまま)", c,
                    LIST_SEP.join(before_m), LIST_SEP.join(after_m))
        elif cmp is not None and cmp[2]:
            # 前回は見なかったもの(データを直した、前回は第2の出典が取れなかった など)が、今回は合わない
            add(LIGHT, "前回は見なかった語句・数字が、今回は合わない", c, "見ていない", LIST_SEP.join(cmp[2]))
        elif cmp is None and p["判定"] != c["判定"]:
            # 古い形の記録との比べ合い。何が合わなくなったかは、今回の分だけ添える
            add(HEAVY if c["判定"] == "不一致" else LIGHT, "照合の結果が変わった", c,
                p["判定"], _with_missing(c["判定"], c.get("合わなかったもの", "")))
        elif cmp is None and c["役割"] == PLACE and p.get("種類の語の数") and c.get("種類の語の数") and p["種類の語の数"] != c["種類の語の数"]:
            words_changed.setdefault(c["URL"], []).append((p, c))
        elif p["本文の印"] != c["本文の印"]:
            # 同じページを出典にする行が多い(文部科学省の一覧など)。ページごとに1行にまとめる
            text_changed.setdefault((c["役割"], c["URL"]), []).append(c)
            text_changed[(c["役割"], c["URL"])][0].setdefault("_前", p["本文の印"])
            text_changed[(c["役割"], c["URL"])][0].setdefault("_語を比べた", bool(p.get("種類の語の数") and c.get("種類の語の数")))
    for (role, _), group in text_changed.items():
        first = group[0]
        if role in (SOURCE, SOURCE2):
            judged = {g["判定"] for g in group}
            what = ("ページの文字が変わった(照合で見た語句と数字は、すべてまだある)" if judged == {"一致"}
                    else "ページの文字が変わった(合わない語句・数字は前と同じ)")
        else:
            what = "探した場所のページの文字が変わった(種類の語の数は同じ)" if first.get("_語を比べた") else "探した場所のページの文字が変わった"
        first.pop("_語を比べた", None)
        add(LIGHT, what, first, first.pop("_前"), first["本文の印"], " ".join(g["id"] for g in group))
    for url, pairs in words_changed.items():
        p, c = pairs[0]
        old, new = parse_counts(p["種類の語の数"]), parse_counts(c["種類の語の数"])
        both = set(old) & set(new)  # 数える語を足したり減らしたりした回に、誤って「増えた」と言わない
        moved = sorted(w for w in both if old[w] != new[w])
        if not moved:
            if p["本文の印"] != c["本文の印"]:
                add(LIGHT, "探した場所のページの文字が変わった", c, p["本文の印"], c["本文の印"],
                    " ".join(cc["id"] for _, cc in pairs))
            continue
        # 「確認できず」の行の種類の語が増えたら(0回から出たときも、もともと出ていて増えたときも)、
        # 制度が載ったかもしれない(要確認)。減ったとき、ほかの種類の語のときは記録のみ
        own = {w for _, cc in pairs if (statuses or {}).get(cc["id"], "確認できず") == "確認できず"
               for w in KIND_WORDS.get(_kind_of(cc["id"]), ())}
        heavy = any(new[w] > old[w] for w in moved if w in own)
        what = "探した場所で、その行の種類の語が増えた" if heavy else "探した場所のページで、種類の語の数が変わった"
        add(HEAVY if heavy else LIGHT, what, c,
            LIST_SEP.join(f"{w}:{old[w]}" for w in moved), LIST_SEP.join(f"{w}:{new[w]}" for w in moved),
            " ".join(cc["id"] for _, cc in pairs))
    return changes


def _kind_of(rid: str) -> str:
    """id の後半(種類)。id は「市町村コード-種類」(同じ種類が複数あれば -2 など)。"""
    m = re.fullmatch(r"\d{5}-(.+?)(-\d+)?", rid)
    return m.group(1) if m else ""


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def summary_markdown(cur: list[dict[str, str]], changes: list[dict[str, str]], first_run: bool, date: str) -> str:
    urls = {c["URL"]: c for c in cur}
    got = sum(c["取得"] == "取得" for c in urls.values())
    src = [c for c in cur if c["役割"] == SOURCE]
    src2 = [c for c in cur if c["役割"] == SOURCE2]
    items = sum(len(split_list(c.get("照合で見たもの", ""))) for c in src + src2)
    missing = sum(len(split_list(c.get("合わなかったもの", ""))) for c in src + src2)
    lines = [
        f"## 定期的な取り直し({date})", "",
        "| | 件数 | 数え方 |", "|---|---|---|",
        f"| 取りに行ったページ | {len(urls)} | 出典と、探した場所の URL(重なりは1つに数える) |",
        f"| うち 取得できた | {got} | |",
        f"| うち 取得できなかった | {len(urls) - got} | robots.txt による禁止、接続できない、文字の無い PDF など |",
        f"| 出典と照合した行 | {len(src)} | 一致 {sum(c['判定'] == '一致' for c in src)}、"
        f"不一致 {sum(c['判定'] == '不一致' for c in src)}、取得できず {sum(c['判定'] == '' for c in src)} |",
        f"| 第2の出典と照合した行 | {len(src2)} | 一致 {sum(c['判定'] == '一致' for c in src2)}、"
        f"不一致 {sum(c['判定'] == '不一致' for c in src2)}、取得できず {sum(c['判定'] == '' for c in src2)} |",
        f"| 照合に使った語句と数字 | {items} | 出典ごとに数えた。うち ページに無かった {missing} |",
        "",
    ]
    if first_run:
        lines.append("初回なので、比べる相手が無い。変わった所は次回から出る。")
    elif not changes:
        lines.append("前回から変わった所は無い。")
    else:
        heavy = [c for c in changes if c["重さ"] == HEAVY]
        lines.append(f"前回から変わった所は {len(changes)} 件(要確認 {len(heavy)}、記録のみ {len(changes) - len(heavy)})。")
        lines += ["", "| 重さ | 変わった所 | id | 役割 | URL | 前 | 後 |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {c['重さ']} | {c['変わった所']} | {c['id']} | {c['役割']} | {c['URL']} | {c['前']} | {c['後']} |"
                  for c in sorted(changes, key=lambda c: c["重さ"] != HEAVY)]
    missing = sorted({(c["URL"], c["取得"]) for c in cur if c["取得"] != "取得"})
    if missing:
        lines += ["", "### 取得できなかったページ", "", "| URL | 理由 |", "|---|---|"]
        lines += [f"| {u} | {why} |" for u, why in missing]
    return "\n".join(lines) + "\n"


def issue_markdown(changes: list[dict[str, str]], date: str) -> str:
    """知らせ(Issue)の文面。要確認が無ければ空。"""
    heavy = [c for c in changes if c["重さ"] == HEAVY]
    if not heavy:
        return ""
    lines = [
        f"定期的な取り直し({date})で、要確認が {len(heavy)} 件ある"
        "(出典のページとデータが合わなくなった、出典を取得できなくなった、「確認できず」の行の探した場所で種類の語が増えた)。",
        "", "公開データは書き換えていない。出典のページを人が見て、直すかどうかを決める。"
        "「前」「後」の「合わない:」は、データの側の語句・数字のうち、ページに見つからなかったもの(前回と今回の両方で見たものだけを比べる)。"
        "「備考の」が付く数字は、出典か第2の出典のどちらかのページにあればよいので、両方のページを見てほしい。", "",
        "| 変わった所 | id | URL | 前 | 後 |", "|---|---|---|---|---|",
    ]
    lines += [f"| {c['変わった所']} | {c['id']} | {c['URL']} | {c['前']} | {c['後']} |" for c in heavy]
    lines += ["", "見るもの: 制度が変わったのか、ページの場所が替わったのか(年度入りの資料は、年度が替わると URL が替わる)、"
              "一時的に届かなかっただけか。種類の語が出たときは、制度が載ったのか、関係の無い記事なのか。"
              "記録は `data/torinaoshi/sabun.csv`。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/seido.csv")
    ap.add_argument("--issue", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--interval", type=float, default=fetch_mod.INTERVAL_SEC)
    args = ap.parse_args()

    date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    prev = read(SAISHIN)
    rows = schema.load(args.path)
    cur = collect(rows, interval=args.interval)
    changes = diff(prev, cur, date, {r["id"]: r["状態"] for r in rows})
    write(SAISHIN, cur, SAISHIN_COLUMNS)
    write(SABUN, read(SABUN) + changes, SABUN_COLUMNS)

    md = summary_markdown(cur, changes, first_run=not prev, date=date)
    print(md)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    if args.issue:
        Path(args.issue).write_text(issue_markdown(changes, date), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
