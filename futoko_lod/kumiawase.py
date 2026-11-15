"""組み合わせの例。このデータを、e-Stat 統計LOD の統計と、標準地域コードの URI で並べる。

e-Stat 統計LOD の SPARQL エンドポイントの使い方は、公式の説明による:
  https://data.e-stat.go.jp/lodw/index.php/en/sparqlendpoint/api
  (http://data.e-stat.go.jp/lod/sparql/alldata/query に、query という名前で問い合わせを POST する)
項目の名前(述語)は推測で書かず、--probe で実際に引いて確かめてから使う。GitHub Actions で回す。

使い方: python -m futoko_lod.kumiawase --probe [コード]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

ENDPOINT = "http://data.e-stat.go.jp/lod/sparql/alldata/query"
SAC = "http://data.e-stat.go.jp/lod/sac/C"
INTERVAL_SEC = 3


def sparql(query: str, timeout: int = 90) -> list[dict[str, str]]:
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        doc = json.loads(res.read().decode("utf-8"))
    time.sleep(INTERVAL_SEC)
    # 変数の名前は大文字で返ってくることがある(2026-11-16 に確かめた)。小文字にそろえる
    return [{k.lower(): v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


def show(title: str, query: str) -> list[dict[str, str]]:
    print(f"\n### {title}\n```\n{query.strip()}\n```")
    try:
        rows = sparql(query)
    except Exception as e:  # 届かない、時間切れ、書き方の誤り
        print(f"失敗: {type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"{len(rows)} 行")
    for r in rows[:60]:
        print("  " + " | ".join(f"{k}={v[:110]}" for k, v in r.items()))
    return rows


def probe(code: str) -> None:
    area = SAC + code
    rows = show("時期なしのコードが持つもの", f"select ?p ?o where {{ <{area}> ?p ?o }} limit 60")
    dated = [r["o"] for r in rows if "/lod/sac/C" in r["o"] and r["o"] != area]
    for uri in [area] + dated[-2:]:
        ps = show(f"{uri} を指している述語", f"select ?p (count(?s) as ?n) where {{ ?s ?p <{uri}> }} group by ?p order by desc(?n) limit 20")
        for p in [r["p"] for r in ps if "Area" in r["p"] or "area" in r["p"]][:1]:
            show("それを指す観測値が属するデータセット",
                 f"select ?ds (count(?s) as ?n) where {{ ?s <{p}> <{uri}> ; <http://purl.org/linked-data/cube#dataSet> ?ds }} group by ?ds order by desc(?n) limit 40")
            obs = show("観測値の見本", f"select ?s where {{ ?s <{p}> <{uri}> }} limit 2")
            for o in obs[:2]:
                show("見本の中身", f"select ?p ?o where {{ <{o['s']}> ?p ?o }} limit 40")


REF_AREA = "http://purl.org/linked-data/sdmx/2009/dimension#refArea"
DATASET = "http://purl.org/linked-data/cube#dataSet"
SSDS = "http://data.e-stat.go.jp/lod/dataset/g00200502/"  # 社会・人口統計体系(市区町村)。--probe で見つけた
INDICATOR = "http://data.e-stat.go.jp/lod/ontology/g00200502/dimension/indicator"
TIME = "http://data.e-stat.go.jp/lod/ontology/crossDomain/dimension/timePeriod"


def indicators(code: str, part: str) -> None:
    """社会・人口統計体系の1つの分野(am=人口、em=教育 など)に、その市町村のどんな指標が、何年まであるか。"""
    q = f"""select ?ind ?label (min(?t) as ?from) (max(?t) as ?to) (count(?s) as ?n) where {{
  <{SAC}{code}> <http://data.e-stat.go.jp/lod/terms/sacs#latestCode> ?area .
  ?s <{REF_AREA}> ?area ; <{DATASET}> <{SSDS}d00200502{part}> ; <{INDICATOR}> ?ind ; <{TIME}> ?t .
  optional {{ ?ind <http://www.w3.org/2000/01/rdf-schema#label> ?label . filter(lang(?label) = "ja") }}
}} group by ?ind ?label order by ?ind limit 200"""
    show(f"分野 {part} の指標(最新のコードの分)", q)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="?", const="40219")
    ap.add_argument("--indicators", nargs="+", metavar="コード 分野...")
    args = ap.parse_args()
    if args.probe:
        probe(args.probe)
    if args.indicators:
        for part in args.indicators[1:]:
            indicators(args.indicators[0], part)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
