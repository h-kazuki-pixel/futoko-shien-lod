import json
from pathlib import Path

import pytest

from futoko_lod import build, schema


def test_jsonld_is_up_to_date():
    assert Path("data/seido.jsonld").read_text(encoding="utf-8") == build.build()


def test_jsonld_has_every_row():
    rows = schema.load("data/seido.csv")
    doc = json.loads(build.build())
    assert [n["identifier"] for n in doc["@graph"]] == [r["id"] for r in rows]


def test_kakunin_dekizu_has_no_source_or_amount():
    doc = json.loads(build.build())
    for node in doc["@graph"]:
        if node["status"] == "fsl:status-kakunin-dekizu":
            assert "source" not in node and "amountText" not in node
            assert node["searchedAt"]


def test_jsonld_parses_as_rdf():
    rdflib = pytest.importorskip("rdflib")
    g = rdflib.Graph()
    g.parse(data=build.build(), format="json-ld")
    rows = schema.load("data/seido.csv")
    records = set(g.subjects(rdflib.RDF.type, rdflib.URIRef(build.BASE + "ns#Record")))
    assert len(records) == len(rows)
    # 制度そのもの(GovernmentService)と言えるのは、あり・予定の行だけ。なし・確認できずを制度として数えさせない
    services = set(g.subjects(rdflib.RDF.type, rdflib.URIRef("https://schema.org/GovernmentService")))
    assert len(services) == sum(r["状態"] in ("あり", "予定") for r in rows)


def test_area_links_to_estat_standard_area_code():
    doc = json.loads(build.build())
    for node in doc["@graph"]:
        area = node["areaServed"]
        assert area["@id"] == "http://data.e-stat.go.jp/lod/sac/C" + area["identifier"]


def test_dbpedia_links_are_only_the_verified_ones():
    rows = {r["市町村コード"]: r for r in schema.read_csv("data/dbpedia.csv")}
    doc = json.loads(build.build())
    assert any("sameAs" in n["areaServed"] for n in doc["@graph"])
    for node in doc["@graph"]:
        area = node["areaServed"]
        checked = rows.get(area["identifier"])
        if "sameAs" in area:
            assert checked["判定"] == "一致" and area["sameAs"] == checked["DBpediaのURI"]
            assert area["sameAs"].startswith("http://ja.dbpedia.org/resource/")
        else:
            assert checked is None or checked["判定"] != "一致"
