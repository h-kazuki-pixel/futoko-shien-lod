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


CODE_PROP = "http://ja.dbpedia.org/property/コード"  # --probe で、大野城市が 40219 を持つことを確かめた(2026-11-16)
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
REDIRECT = "http://dbpedia.org/ontology/wikiPageRedirects"
CSV_PATH = "data/dbpedia.csv"
CSV_COLUMNS = ["市町村コード", "市町村", "DBpediaのURI", "DBpediaでの名前", "判定", "確かめた日"]


def verify_query(codes: list[str]) -> str:
    """地方公共団体コードがこちらのコードと合う資源を引く。名前からは URI を作らない。"""
    inlist = ", ".join(f'"{c}"' for c in codes)
    return f"""select ?s ?c ?label ?redirect where {{
  ?s <{CODE_PROP}> ?c . filter(str(?c) in ({inlist}))
  optional {{ ?s <{LABEL}> ?label }}
  optional {{ ?s <{REDIRECT}> ?redirect }}
}}"""


def judge(areas: dict[str, str], rows: list[dict[str, str]], date: str) -> list[dict[str, str]]:
    """コードごとに、採ってよい URI が1つに決まるかを判定する。

    採るのは「一致」だけ: そのコードを持つ資源(転送でないもの)がちょうど1つで、名前がこちらの名前で始まる
    (「川崎町 (福岡県)」のような、かっこ付きの名前を許す)。
    """
    by_code: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.get("redirect"):
            continue
        by_code.setdefault(r["c"].strip(), {})[r["s"]] = r.get("label", "")
    out = []
    for code, name in areas.items():
        found = by_code.get(code, {})
        row = {"市町村コード": code, "市町村": name, "DBpediaのURI": "", "DBpediaでの名前": "", "判定": "", "確かめた日": date}
        if not found:
            row["判定"] = "このコードを持つ資源が返らなかった"
        elif len(found) > 1:
            row["判定"] = "同じコードを持つ資源が複数(" + " ".join(sorted(found)) + ")"
        else:
            (uri, label), = found.items()
            row["DBpediaでの名前"] = label
            if label == name or label.startswith(name + " ("):
                row["DBpediaのURI"], row["判定"] = uri, "一致"
            else:
                row["判定"] = f"名前が違う({uri})"
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs=2, metavar=("名前", "コード"))
    ap.add_argument("--verify", nargs="?", const="show", choices=["show", "write"])
    args = ap.parse_args()
    if args.probe:
        probe(*args.probe)
    if args.verify:
        import csv
        import datetime as dt
        from pathlib import Path
        from . import schema
        areas = {a["市町村コード"]: a["市町村"] for a in schema.read_csv("data/shichoson.csv")}
        rows = show("コードが合う資源", verify_query(list(areas)), limit=5)
        if not rows:
            print("1行も返らなかった。書き出さない")
            return 1
        out = judge(areas, rows, dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat())
        for r in out:
            if r["判定"] != "一致":
                print("| " + " | ".join(r[c] for c in CSV_COLUMNS) + " |")
        print(f"一致 {sum(r['判定'] == '一致' for r in out)} / {len(out)}")
        if args.verify == "write":
            Path(CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
                w.writeheader()
                w.writerows(out)
            print(f"{CSV_PATH} を書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
