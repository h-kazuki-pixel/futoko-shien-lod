"""つなぐ先の確認。推測で URI を書かないために、実際に引いて確かめる。

1. e-Stat 統計LOD の標準地域コード
   書式は http://data.e-stat.go.jp/lod/sac/C{5桁} (時期を持たないコード)。
   出典: 統計LOD「Common codes」 https://data.e-stat.go.jp/lodw/en/node/34
   データにある市町村コードごとに引き、返ってきた中身に市町村の名前があるかを見る。
2. e-Gov 法令検索の法令ID
   書式の出典: https://laws.e-gov.go.jp/file/LawIdNamingConvention.pdf
   法令API https://laws.e-gov.go.jp/api/1/lawdata/{法令ID} を引き、法律の名前が返るかを見る。

GitHub Actions で回す。使い方: python -m futoko_lod.links
"""

from __future__ import annotations

import argparse
import html
import re
import time
import urllib.error
import urllib.request

from . import schema
from .fetch import USER_AGENT, decode

SAC = "http://data.e-stat.go.jp/lod/sac/C{code}"
LAW_ID = "428AC1000000105"
LAW_NAME = "義務教育の段階における普通教育に相当する教育の機会の確保等に関する法律"
LAW_API = "https://laws.e-gov.go.jp/api/1/lawdata/{id}"
LAW_PAGE = "https://laws.e-gov.go.jp/law/{id}"  # 公式の説明に書式の記載は見つかっていない。届くかだけ見る


def get(url: str, accept: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            body = res.read()
            return {
                "HTTP": res.status,
                "行き先": res.geturl(),
                "形式": res.headers.get("Content-Type", ""),
                "text": decode(body, res.headers.get("Content-Type", "")),
            }
    except urllib.error.HTTPError as e:
        return {"HTTP": e.code, "行き先": url, "形式": "", "text": ""}
    except Exception as e:
        return {"HTTP": type(e).__name__, "行き先": url, "形式": "", "text": ""}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", default="")
    args = ap.parse_args()

    areas: dict[str, str] = dict(schema.load_areas() or {})
    for path in ("data/seido.csv", "data/horyu.csv"):
        for row in schema.read_csv(path):
            areas.setdefault(row["市町村コード"], row["市町村"])

    lines = ["## つなぐ先の確認", "", "### e-Stat 統計LOD(標準地域コード)", ""]
    lines += ["| コード | 名前 | URI | HTTP | 形式 | 中身に名前がある |", "|---|---|---|---|---|---|"]
    accept = "text/turtle, application/rdf+xml;q=0.9, */*;q=0.5"
    # 最後の1件は、存在しないはずのコード(引けてしまわないかの対照)
    for code, name in sorted(areas.items()) + [("40999", "(存在しないコードの対照)")]:
        url = SAC.format(code=code)
        r = get(url, accept)
        text = html.unescape(r["text"])
        where = "時期なしのコード" if name in text else ""
        if not where:
            # 名前は時期つきのコードの側にある。最新のコード(sacs:latestCode)を辿る
            m = re.search(r"latestCode[^>]*?resource=\"([^\"]+)\"", text)
            if m:
                time.sleep(2)
                r2 = get(m.group(1), accept)
                if name in html.unescape(r2["text"]):
                    where = f"最新のコード {m.group(1).rsplit('/', 1)[-1]}"
        lines.append(
            f"| {code} | {name} | {url} | {r['HTTP']} | {r['形式'].split(';')[0]} | {where or '無い'} ({len(text)}字) |"
        )
        time.sleep(2)

    lines += ["", "### e-Gov 法令検索", "", "| 引いた先 | HTTP | 形式 | 中身に法律の名前がある |", "|---|---|---|---|"]
    for url in (LAW_API.format(id=LAW_ID), LAW_PAGE.format(id=LAW_ID)):
        r = get(url, "*/*")
        found = "ある" if LAW_NAME in r["text"] else "無い"
        lines.append(f"| {url} | {r['HTTP']} | {r['形式'].split(';')[0]} | {found} |")
        time.sleep(2)

    md = "\n".join(lines) + "\n"
    print(md)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
