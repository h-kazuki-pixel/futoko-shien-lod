"""不登校支援制度LOD の使い方の例。

公開している Turtle を読み、SPARQL で問い合わせる。必要なのは rdflib だけ(pip install rdflib)。

    python examples/tsukaikata.py                 # 公開のサイトから読む
    python examples/tsukaikata.py 大野城市         # 市町村を選ぶ
    python examples/tsukaikata.py 大野城市 --dir _site   # 手元で作ったサイトから読む

出すもの:
  1. 選んだ市町村の、種類ごとの状態と出典
  2. 状態ごとの件数(「なし」と「確認できず」を分けて数える)
  3. 「確認できず」の行と、探したページの数

制度は変わる。使う前に、必ず市町村の窓口で確かめること。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rdflib import Graph

SITE = "https://h-kazuki-pixel.github.io/futoko-shien-lod/"

PREFIXES = """
PREFIX schema: <https://schema.org/>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX fsl: <https://h-kazuki-pixel.github.io/futoko-shien-lod/ns#>
"""

# 1. ある市町村の、種類ごとの状態と出典
Q_SHICHOSON = PREFIXES + """
SELECT ?kindLabel ?statusLabel ?name ?source ?checked WHERE {
  ?r a fsl:Record ;
     schema:areaServed ?area ;
     fsl:kind ?kind ;
     fsl:status ?status ;
     fsl:dateChecked ?checked .
  ?area schema:name ?areaName .
  FILTER(STR(?areaName) = ?want)
  ?kind skos:prefLabel ?kindLabel .
  ?status skos:prefLabel ?statusLabel .
  OPTIONAL { ?r schema:name ?name }
  OPTIONAL { ?r dct:source ?source }
}
ORDER BY ?kindLabel
"""

# 2. 状態ごとの件数
Q_KAZU = PREFIXES + """
SELECT ?statusLabel (COUNT(?r) AS ?n) WHERE {
  ?r a fsl:Record ; fsl:status ?status .
  ?status skos:prefLabel ?statusLabel .
}
GROUP BY ?statusLabel
ORDER BY DESC(?n)
"""

# 3. 「確認できず」の行と、探したページの数。制度とは型が分かれている(schema:GovernmentService ではない)
Q_KAKUNIN_DEKIZU = PREFIXES + """
SELECT ?areaName ?kindLabel (COUNT(?place) AS ?places) WHERE {
  ?r fsl:status fsl:status-kakunin-dekizu ;
     schema:areaServed/schema:name ?areaName ;
     fsl:kind/skos:prefLabel ?kindLabel ;
     fsl:searchedAt ?place .
  FILTER NOT EXISTS { ?r a schema:GovernmentService }
}
GROUP BY ?areaName ?kindLabel
ORDER BY ?areaName ?kindLabel
"""


def load(local_dir: str | None) -> Graph:
    """全件の Turtle と、語彙(種類・状態の名前)を読む。"""
    g = Graph()
    for name in ("seido.ttl", "ns.ttl"):
        if local_dir:
            g.parse(Path(local_dir) / name, format="turtle")
        else:
            g.parse(SITE + name, format="turtle")
    return g


def shichoson(g: Graph, name: str) -> list[tuple[str, ...]]:
    return [tuple(str(x) if x is not None else "" for x in row)
            for row in g.query(Q_SHICHOSON, initBindings={"want": _lit(name)})]


def kazu(g: Graph) -> dict[str, int]:
    return {str(s): int(n) for s, n in g.query(Q_KAZU)}


def kakunin_dekizu(g: Graph) -> list[tuple[str, str, int]]:
    return [(str(a), str(k), int(n)) for a, k, n in g.query(Q_KAKUNIN_DEKIZU)]


def _lit(text: str):
    from rdflib import Literal
    return Literal(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("shichoson", nargs="?", default="大野城市", help="市町村の名前(例: 大野城市)")
    ap.add_argument("--dir", help="手元で作ったサイトのフォルダ(python -c 'from futoko_lod import publish; publish.write_site(\"_site\")')")
    a = ap.parse_args(argv)
    g = load(a.dir)

    print(f"## {a.shichoson}")
    rows = shichoson(g, a.shichoson)
    if not rows:
        print("(このデータに無い市町村。福岡都市圏の17市町は5種類、ほかの市町村は学びの多様化学校だけを持つ)")
    for kind, status, name, source, checked in rows:
        print(f"- {kind}: {status}" + (f"(確認日 {checked})" if checked else ""))
        if name:
            print(f"    {name}")
        if source:
            print(f"    出典 {source}")

    print("\n## 状態ごとの件数")
    for status, n in kazu(g).items():
        print(f"- {status}: {n}")

    print("\n## 「確認できず」の行(探したページの数)")
    for area, kind, n in kakunin_dekizu(g):
        print(f"- {area} / {kind}: {n}ページ")
    print("\n「確認できず」は、制度が無いという意味ではない。使う前に、必ず市町村の窓口で確かめてください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
