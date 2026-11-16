"""定期的な取り直し。出典のページと、探した場所のページを取り直し、前回から変わった所を残す。

GitHub Actions の `torinaoshi` で週1回まわす。やることは3つ。
1. 「あり」「予定」と、出典のある「なし」は、出典を取り直して照合する(shougou と同じ照合)
2. 「確認できず」は、探した場所のページを取り直す(制度が載ったかもしれないページを見逃さないため)
3. 前回の記録と比べ、変わった所を1行ずつ足す

残すもの(ページの本文は残さない。残すのは、文字列をそろえてから取った印だけ):
  data/torinaoshi/saishin.csv  いちばん新しい取り直しの結果。行(id)とページ(URL)の組ごとに1行
  data/torinaoshi/sabun.csv    変わった所。足していくだけで、消さない

変わった所は2つの重さに分ける。
  要確認    照合が一致でなくなった / 取得できなくなった(2回試して2回とも)
  記録のみ  ページの文字が変わった(照合は一致のまま) / 探した場所のページの文字が変わった / 元に戻った
公開データ(data/seido.csv)は、ここでは書き換えない。直すかどうかは、人が出典を見て決める。

使い方: python -m futoko_lod.torinaoshi [--issue 知らせの文面を書き出すファイル] [--summary まとめのファイル]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import time
from pathlib import Path
from typing import Callable

from . import collate as collate_mod
from . import fetch as fetch_mod
from . import schema

DIR = Path("data/torinaoshi")
SAISHIN = DIR / "saishin.csv"
SABUN = DIR / "sabun.csv"
SAISHIN_COLUMNS = ["id", "役割", "URL", "取得日時", "取得", "判定", "本文の印"]
SABUN_COLUMNS = ["日付", "重さ", "変わった所", "id", "役割", "URL", "前", "後"]
RETRY_WAIT_SEC = 30

SOURCE, SOURCE2, PLACE = "出典", "出典2", "探した場所"
HEAVY, LIGHT = "要確認", "記録のみ"


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
            "判定": "", "本文の印": "",
        }
        if page["text"] is not None:
            entry["本文の印"] = text_mark(page["text"])
            if role == SOURCE:
                absence = row["状態"] == "なし"
                c = (collate_mod.collate_absence if absence else collate_mod.collate)(row, page["text"])
                entry["判定"] = "一致" if c["一致"] else "不一致"
            elif role == SOURCE2:
                c = collate_mod.collate(row, page["text"], part=2)
                entry["判定"] = "一致" if c["一致"] else "不一致"
        results.append(entry)
    return results


def diff(prev: list[dict[str, str]], cur: list[dict[str, str]], date: str) -> list[dict[str, str]]:
    """前回と今回を比べる。前回に無い組(新しい行)は、変わった所に数えない。"""
    before = {(p["id"], p["役割"], p["URL"]): p for p in prev}
    changes: list[dict[str, str]] = []
    text_changed: dict[tuple[str, str], list[dict[str, str]]] = {}

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
        if p["判定"] != c["判定"]:
            add(HEAVY if c["判定"] == "不一致" else LIGHT, "照合の結果が変わった", c, p["判定"], c["判定"])
        elif p["本文の印"] != c["本文の印"]:
            # 同じページを出典にする行が多い(文部科学省の一覧など)。ページごとに1行にまとめる
            text_changed.setdefault((c["役割"], c["URL"]), []).append(c)
            text_changed[(c["役割"], c["URL"])][0].setdefault("_前", p["本文の印"])
    for (role, _), group in text_changed.items():
        first = group[0]
        what = "ページの文字が変わった(照合は一致のまま)" if role in (SOURCE, SOURCE2) else "探した場所のページの文字が変わった"
        add(LIGHT, what, first, first.pop("_前"), first["本文の印"], " ".join(g["id"] for g in group))
    return changes


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
        f"定期的な取り直し({date})で、出典のページとデータが合わなくなった行、または出典を取得できなくなった行が {len(heavy)} 件ある。",
        "", "公開データは書き換えていない。出典のページを人が見て、直すかどうかを決める。", "",
        "| 変わった所 | id | URL | 前 | 後 |", "|---|---|---|---|---|",
    ]
    lines += [f"| {c['変わった所']} | {c['id']} | {c['URL']} | {c['前']} | {c['後']} |" for c in heavy]
    lines += ["", "見るもの: 制度が変わったのか、ページの場所が替わったのか(年度入りの資料は、年度が替わると URL が替わる)、"
              "一時的に届かなかっただけか。記録は `data/torinaoshi/sabun.csv`。"]
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
    cur = collect(schema.load(args.path), interval=args.interval)
    changes = diff(prev, cur, date)
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
