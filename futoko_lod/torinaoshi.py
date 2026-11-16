"""定期的な取り直し。出典のページと、探した場所のページを取り直し、前回から変わった所を残す。

GitHub Actions の `torinaoshi` で週1回まわす。やることは3つ。
1. 「あり」「予定」と、出典のある「なし」は、出典を取り直して照合する(shougou と同じ照合)
2. 「確認できず」は、探した場所のページを取り直す(制度が載ったかもしれないページを見逃さないため)
3. 前回の記録と比べ、変わった所を1行ずつ足す

残すもの(ページの本文は残さない。残すのは、文字列をそろえてから取った印と、データの側の語句・数字がページにあったかだけ):
  data/torinaoshi/saishin.csv  いちばん新しい取り直しの結果。行(id)とページ(URL)の組ごとに1行
  data/torinaoshi/sabun.csv    変わった所。足していくだけで、消さない

何が変わったか(弱い所 取2): 出典では、照合に使う語句と数字(根拠の箇所、金額・対象・開始の数字)の一つ一つが
ページにまだあるかを毎回残す。探した場所では、種類の語(「教育支援センター」「出席扱い」など)がページに何回出るかを残す。
本文は残さないので、ページのどの文が変わったかまでは分からない。分かるのは、データの側の語句・数字が消えたか・戻ったかと、
種類の語が増えたか・減ったかまで。

変わった所は2つの重さに分ける。
  要確認    照合が一致でなくなった / 取得できなくなった(2回試して2回とも) / 探した場所に、その行の種類の語が新しく出た
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
    return results


def _missing_change(p: dict[str, str], c: dict[str, str]) -> tuple[list[str], list[str]] | None:
    """前回と今回で、合わなかったものが変わったか。前回の記録に項目が無い(古い形の記録)ときは None。
    データの側を直して見るものが変わったときは、両方で見たものだけを比べる。"""
    if not p.get("照合で見たもの") or not c.get("照合で見たもの"):
        return None
    common = set(split_list(p["照合で見たもの"])) & set(split_list(c["照合で見たもの"]))
    before = [x for x in split_list(p.get("合わなかったもの", "")) if x in common]
    after = [x for x in split_list(c.get("合わなかったもの", "")) if x in common]
    return (before, after) if before != after else None


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
        moved = _missing_change(p, c)
        if p["判定"] != c["判定"]:
            # 何が合わなくなったか(戻ったか)を、前と後に添える
            add(HEAVY if c["判定"] == "不一致" else LIGHT, "照合の結果が変わった", c,
                _with_missing(p["判定"], p.get("合わなかったもの", "")), _with_missing(c["判定"], c.get("合わなかったもの", "")))
        elif moved is not None:
            add(LIGHT, "合わない語句・数字が変わった(照合は不一致のまま)", c,
                LIST_SEP.join(moved[0]) or "無し", LIST_SEP.join(moved[1]) or "無し")
        elif c["役割"] == PLACE and p.get("種類の語の数") and c.get("種類の語の数") and p["種類の語の数"] != c["種類の語の数"]:
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
            what = ("ページの文字が変わった(照合に使う語句と数字は、すべてまだある)" if judged == {"一致"}
                    else "ページの文字が変わった(合わない語句・数字は前と同じ)")
        else:
            what = "探した場所のページの文字が変わった(種類の語の数は同じ)" if first.get("_語を比べた") else "探した場所のページの文字が変わった"
        first.pop("_語を比べた", None)
        add(LIGHT, what, first, first.pop("_前"), first["本文の印"], " ".join(g["id"] for g in group))
    for url, pairs in words_changed.items():
        p, c = pairs[0]
        old, new = parse_counts(p["種類の語の数"]), parse_counts(c["種類の語の数"])
        appeared = {w for w, n in new.items() if n > 0 and old.get(w, 0) == 0}
        # その行の種類の語が新しく出たら、制度が載ったかもしれない(要確認)。ほかの種類の語なら記録のみ
        own = {w for _, cc in pairs if (statuses or {}).get(cc["id"], "確認できず") == "確認できず"
               for w in KIND_WORDS.get(_kind_of(cc["id"]), ())}
        heavy = bool(appeared & own)
        moved = sorted(w for w in set(old) | set(new) if old.get(w, 0) != new.get(w, 0))
        what = "探した場所に、その行の種類の語が新しく出た" if heavy else "探した場所のページで、種類の語の数が変わった"
        add(HEAVY if heavy else LIGHT, what, c,
            LIST_SEP.join(f"{w}:{old.get(w, 0)}" for w in moved), LIST_SEP.join(f"{w}:{new.get(w, 0)}" for w in moved),
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
        "(出典のページとデータが合わなくなった、出典を取得できなくなった、「確認できず」の行の探した場所に種類の語が新しく出た)。",
        "", "公開データは書き換えていない。出典のページを人が見て、直すかどうかを決める。"
        "「前」「後」の「合わない:」は、データの側の語句・数字のうち、ページに見つからなかったもの。", "",
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
