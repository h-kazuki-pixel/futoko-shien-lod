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
    services = set(g.subjects(rdflib.RDF.type, rdflib.URIRef("https://schema.org/GovernmentService")))
    assert len(services) == len(rows)
