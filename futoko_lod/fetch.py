"""出典のページを取りに行き、照合する。GitHub Actions で回す前提。

- robots.txt に従う。禁止されていれば取りに行かない
- 1件ずつ間隔をあける
- 取得した日時と URL を記録する
- ページの本文は保存しない(照合の結果だけを残す)

使い方: python -m futoko_lod.fetch data/seido.csv --out shougou.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from urllib.parse import urlparse

from . import collate as collate_mod
from . import schema

USER_AGENT = "futoko-shien-lod/0.1 (+https://github.com/h-kazuki-pixel/futoko-shien-lod)"
INTERVAL_SEC = 5
TIMEOUT_SEC = 30


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextOnly()
    p.feed(html)
    return " ".join(p.parts)


def decode(body: bytes, content_type: str) -> str:
    candidates = []
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if m:
        candidates.append(m.group(1))
    m = re.search(rb"charset=[\"']?([\w-]+)", body[:4096], re.I)
    if m:
        candidates.append(m.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp932", "euc_jp"]
    for enc in candidates:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def pdf_to_text(body: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(io.BytesIO(body))
    return " ".join((page.extract_text() or "") for page in reader.pages)


_robots: dict[str, tuple[urllib.robotparser.RobotFileParser | None, str]] = {}


def robots_decision(url: str) -> tuple[bool, str]:
    """robots.txt を読んで、取りに行ってよいかを返す。(よいか, 判断の理由)"""
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
                rp.parse(decode(res.read(), res.headers.get("Content-Type", "")).splitlines())
            _robots[root] = (rp, "robots.txt を読んだ")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                rp.parse(["User-agent: *", "Disallow: /"])
                _robots[root] = (rp, f"robots.txt が HTTP {e.code}。禁止として扱う")
            elif 400 <= e.code < 500:
                _robots[root] = (None, f"robots.txt は無い(HTTP {e.code})。制限なし")
            else:
                rp.parse(["User-agent: *", "Disallow: /"])
                _robots[root] = (rp, f"robots.txt を確かめられず(HTTP {e.code})。取りに行かない")
        except Exception as e:
            rp.parse(["User-agent: *", "Disallow: /"])
            _robots[root] = (rp, f"robots.txt を確かめられず({type(e).__name__})。取りに行かない")
        time.sleep(1)
    rp, note = _robots[root]
    return (True if rp is None else rp.can_fetch(USER_AGENT, url)), note


def allowed_by_robots(url: str) -> bool:
    return robots_decision(url)[0]


def fetch(url: str) -> dict:
    """1つの URL を取りに行く。本文の文字列と、記録を返す。"""
    record = {"url": url, "取得日時": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    ok, note = robots_decision(url)
    record["robots"] = note
    if not ok:
        return {**record, "結果": "robots.txt により取得しない", "text": None}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            body = res.read()
            ctype = res.headers.get("Content-Type", "")
            record["HTTP"] = res.status
    except urllib.error.HTTPError as e:
        return {**record, "HTTP": e.code, "結果": f"取得できず(HTTP {e.code})", "text": None}
    except Exception as e:  # 接続できない、時間切れなど
        return {**record, "結果": f"取得できず({type(e).__name__})", "text": None}

    record["sha256"] = hashlib.sha256(body).hexdigest()
    if "pdf" in ctype.lower() or body[:5] == b"%PDF-":
        text = pdf_to_text(body)
        if text is None:
            return {**record, "結果": "PDF を読む道具が無い", "text": None}
        if not text.strip():
            return {**record, "結果": "PDF から文字を取り出せず(画像の可能性)", "text": None}
    else:
        text = html_to_text(decode(body, ctype))
    return {**record, "結果": "取得", "text": text}


def run(path: str, interval: float = INTERVAL_SEC) -> list[dict]:
    rows = schema.load(path)
    pages: dict[str, dict] = {}
    results = []
    for row in rows:
        if row["状態"] not in ("あり", "予定"):
            results.append({"id": row["id"], "状態": row["状態"], "判定": "照合の対象外"})
            continue
        url = row["出典URL"]
        if url not in pages:
            if pages:
                time.sleep(interval)
            pages[url] = fetch(url)
        page = pages[url]
        entry = {"id": row["id"], "状態": row["状態"], **{k: v for k, v in page.items() if k != "text"}}
        if page["text"] is None:
            entry["判定"] = "取得できず"
        else:
            c = collate_mod.collate(row, page["text"])
            entry.update({k: v for k, v in c.items() if k != "id"})
            entry["判定"] = "一致" if c["一致"] else "不一致"
        results.append(entry)
    return results


def summary_markdown(results: list[dict], title: str = "出典との照合") -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["判定"]] = counts.get(r["判定"], 0) + 1
    lines = [f"## {title}", "", "| 判定 | 件数 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(counts.items())]
    lines += ["", "| id | 判定 | 取得 | robots | 根拠の箇所 | ページに無い数字 | ページに無い名前の部分(合否には使わない) |", "|---|---|---|---|---|---|---|"]
    for r in results:
        if r["判定"] == "照合の対象外":
            continue
        basis = {True: "ある", False: "無い"}.get(r.get("根拠の箇所がページにある"), "—")
        missing = ", ".join(r.get("ページに無い数字", [])) or "—"
        names = ", ".join(r.get("ページに無い名前の部分", [])) or "—"
        lines.append(
            f"| {r['id']} | {r['判定']} | {r.get('結果', '')} | {r.get('robots', '')} | {basis} | {missing} | {names} |"
        )
    matched = [r["id"] for r in results if r["判定"] == "一致"]
    lines += ["", "一致した id: " + ",".join(matched)]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default="data/seido.csv")
    ap.add_argument("--out", default="shougou.json")
    ap.add_argument("--summary", default="")
    ap.add_argument("--interval", type=float, default=INTERVAL_SEC)
    args = ap.parse_args()
    results = run(args.path, args.interval)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    md = summary_markdown(results, f"出典との照合({args.path})")
    print(md)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    # 不一致や取得できずがあっても、ここでは失敗にしない(結果を読んで人が判断する)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
