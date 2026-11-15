"""data/seido.csv から data/seido.jsonld を作る。

URI の土台(BASE)は GitHub Pages の公開の場所(2026-11-15 に決定。変えない)。置き場所の決まりは docs/公開の形.md。
文字列には言語(ja)を付ける。id と補助率は、言語を付けない。
1件は「確かめた記録」(fsl:Record)。制度があると確かめた行(あり・予定)だけ、schema.org の GovernmentService でもある。
市町村は e-Stat 統計LOD の標準地域コード(時期を持たないコード)につなぐ。DBpedia Japanese の資源にもつなぐ(コードが合うことを確かめたものだけ)。書式の出典と、
実際に引いて確かめる手順は links.py にある。e-Gov 法令・学校コードへのリンクはまだ入れていない。

使い方: python -m futoko_lod.build          (作り直す)
        python -m futoko_lod.build --check  (作り直した結果と今のファイルが同じか確かめる)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import schema

BASE = "https://h-kazuki-pixel.github.io/futoko-shien-lod/"
SAC = "http://data.e-stat.go.jp/lod/sac/C"  # e-Stat 統計LOD 標準地域コード

CONTEXT = {
    "schema": "https://schema.org/",
    "dct": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "fsl": BASE + "ns#",
    "@language": "ja",
    "identifier": {"@id": "schema:identifier", "@language": None},
    "name": "schema:name",
    "areaServed": "schema:areaServed",
    "sameAs": {"@id": "schema:sameAs", "@type": "@id"},
    "kind": {"@id": "fsl:kind", "@type": "@id"},
    "status": {"@id": "fsl:status", "@type": "@id"},
    "paymentForm": {"@id": "fsl:paymentForm", "@type": "@id"},
    "eligibility": "fsl:eligibility",
    "amountText": "fsl:amountText",
    "amountMaxYen": {"@id": "fsl:amountMaxYen", "@type": "xsd:integer"},
    "subsidyRate": {"@id": "fsl:subsidyRate", "@language": None},
    "startText": "fsl:startText",
    "source": {"@id": "dct:source", "@type": "@id"},
    "sourceName": "fsl:sourceName",
    "basisPhrase": "fsl:basisPhrase",
    "guidelineState": "fsl:guidelineState",
    "guideline": {"@id": "fsl:guideline", "@type": "@id"},
    "searchedAt": {"@id": "fsl:searchedAt", "@type": "@id"},
    "noneBasis": "fsl:noneBasis",
    "note": "fsl:note",
    "dateChecked": {"@id": "fsl:dateChecked", "@type": "xsd:date"},
    "checkMethod": {"@id": "fsl:checkMethod", "@type": "@id"},
}


_dbpedia: dict[str, str] | None = None


def dbpedia_uris(path: str = "data/dbpedia.csv") -> dict[str, str]:
    """市町村コード → DBpedia Japanese の URI。確かめて「一致」になったものだけ(dbpedia.py が作る)。"""
    global _dbpedia
    if _dbpedia is None:
        p = Path(path)
        _dbpedia = {r["市町村コード"]: r["DBpediaのURI"] for r in schema.read_csv(p) if r["判定"] == "一致"} if p.exists() else {}
    return _dbpedia


def to_node(row: dict[str, str]) -> dict:
    def v(key: str) -> str:
        return (row.get(key) or "").strip()

    node: dict = {
        "@id": f"{BASE}id/{v('id')}",
        # どの行も「確かめた記録」。制度そのものと言えるのは、あり・予定の行だけ
        "@type": ["fsl:Record", "schema:GovernmentService"] if v("状態") in ("あり", "予定") else ["fsl:Record"],
        "identifier": v("id"),
        "areaServed": {
            "@id": SAC + v("市町村コード"),
            "@type": "schema:AdministrativeArea",
            "name": v("市町村"),
            "identifier": v("市町村コード"),
        },
        "kind": f"fsl:kind-{schema.KIND_BY_LABEL[v('制度の種類')]}",
        "status": f"fsl:status-{schema.STATUSES[v('状態')]}",
        "dateChecked": v("確認日"),
        "checkMethod": f"fsl:method-{schema.METHODS[v('確認方法')]}",
    }
    if v("市町村コード") in dbpedia_uris():
        # 同じ市町村を表す、DBpedia Japanese の資源。e-Stat の URI は地域コードで、DBpedia の資源は自治体そのもの。
        # 厳密に同じものとは言い切らず(owl:sameAs は使わない)、schema.org の sameAs(同じものを指す参照先)で持つ
        node["areaServed"]["sameAs"] = dbpedia_uris()[v("市町村コード")]
    optional = {
        "name": v("制度名"),
        "paymentForm": f"fsl:form-{schema.FORMS[v('補助の形')]}" if v("補助の形") else "",
        "eligibility": v("対象"),
        "amountText": v("金額"),
        "amountMaxYen": v("上限額_円"),
        "subsidyRate": v("補助率"),
        "startText": v("開始"),
        "source": v("出典URL"),
        "sourceName": v("出典名"),
        "basisPhrase": v("根拠の箇所"),
        "guidelineState": v("要綱の状況"),
        "guideline": v("要綱URL"),
        "noneBasis": v("なしの根拠"),
        "note": v("備考"),
    }
    node.update({k: val for k, val in optional.items() if val})
    places = [p.strip() for p in v("探した場所").split(schema.SEP.strip()) if p.strip()]
    if places:
        node["searchedAt"] = places
    return node


def build(csv_path: str = "data/seido.csv") -> str:
    rows = schema.load(csv_path)
    doc = {"@context": CONTEXT, "@graph": [to_node(r) for r in rows]}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    out = Path("data/seido.jsonld")
    text = build()
    if "--check" in sys.argv:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            print("data/seido.jsonld が data/seido.csv と合っていない。python -m futoko_lod.build を回す")
            return 1
        print("data/seido.jsonld は最新")
        return 0
    out.write_text(text, encoding="utf-8")
    print(f"{out} を書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
