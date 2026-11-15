"""DBpedia Japanese の市町村の URI を、推測で書かずに確かめる。LODチャレンジ2026 のパートナーの資源(http://ja.dbpedia.org)。

名前から URI を作ると、同じ名前の町(ほかの県)を指す恐れがある。そこで、実際に引いて、
その資源が持つ地方公共団体コードがこちらのコードと合うものだけを採る。GitHub Actions で回す。

使い方: python -m futoko_lod.dbpedia --probe 大野城市 40219
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

ENDPOINT = "http://ja.dbpedia.org/sparql"
RESOURCE = "http://ja.dbpedia.org/resource/"
INTERVAL_SEC = 3


def sparql(query: str, timeout: int = 90) -> list[dict[str, str]]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        doc = json.loads(res.read().decode("utf-8"))
    time.sleep(INTERVAL_SEC)
    return [{k.lower(): v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


def show(title: str, query: str, limit: int = 40) -> list[dict[str, str]]:
    print(f"\n### {title}\n{query.strip()}")
    try:
        rows = sparql(query)
    except Exception as e:
        print(f"失敗: {type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"{len(rows)} 行")
    for r in rows[:limit]:
        print("  " + " | ".join(f"{k}={v[:100]}" for k, v in r.items()))
    return rows


def probe(name: str, code: str) -> None:
    uri = RESOURCE + name
    show("この名前の資源が持つもののうち、コードらしい値と、型・転送", f"""select ?p ?o where {{ <{uri}> ?p ?o .
  filter(contains(str(?o), "{code}") || ?p = <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
         || contains(str(?p), "wikiPageRedirects") || contains(str(?p), "wikiPageDisambiguates") || contains(str(?p), "sameAs")) }} limit 60""")
    show("コードの値からさかのぼる(同じコードを持つ資源)", f"""select ?s ?p where {{ ?s ?p ?o . filter(str(?o) in ("{code}", "{code}0", "{code[:2]}{code[2:]}")) }} limit 40""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs=2, metavar=("名前", "コード"))
    args = ap.parse_args()
    if args.probe:
        probe(*args.probe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
