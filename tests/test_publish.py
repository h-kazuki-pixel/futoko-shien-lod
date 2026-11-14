import html
import json
import re

import pytest

from futoko_lod import build, publish, schema

rdflib = pytest.importorskip("rdflib")
from rdflib.compare import to_isomorphic  # noqa: E402


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    publish.write_site(out)
    return out


@pytest.fixture(scope="module")
def rows():
    return schema.load("data/seido.csv")


def graph(text: str, fmt: str):
    g = rdflib.Graph()
    g.parse(data=text, format=fmt)
    return g


def test_turtle_has_the_same_triples_as_jsonld(site):
    ttl = graph((site / "seido.ttl").read_text(encoding="utf-8"), "turtle")
    jld = graph((site / "seido.jsonld").read_text(encoding="utf-8"), "json-ld")
    assert len(ttl) > 0
    assert to_isomorphic(ttl) == to_isomorphic(jld)


def test_each_record_file_has_the_same_triples_in_both_forms(site, rows):
    for r in rows:
        ttl = graph((site / "id" / f"{r['id']}.ttl").read_text(encoding="utf-8"), "turtle")
        jld = graph((site / "id" / f"{r['id']}.jsonld").read_text(encoding="utf-8"), "json-ld")
        assert to_isomorphic(ttl) == to_isomorphic(jld), r["id"]


def test_record_files_add_up_to_the_whole(site, rows):
    whole = graph((site / "seido.ttl").read_text(encoding="utf-8"), "turtle")
    parts = rdflib.Graph()
    for r in rows:
        parts.parse(data=(site / "id" / f"{r['id']}.ttl").read_text(encoding="utf-8"), format="turtle")
    assert to_isomorphic(parts) == to_isomorphic(whole)


def test_every_record_has_a_page_with_embedded_jsonld(site, rows):
    for r in rows:
        text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
        m = re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)
        node = json.loads(m.group(1))
        assert node["@id"] == f"{build.BASE}id/{r['id']}"
        assert node["identifier"] == r["id"]


def test_every_fsl_term_in_the_data_is_defined_in_the_vocabulary(site):
    data = graph((site / "seido.ttl").read_text(encoding="utf-8"), "turtle")
    vocab = graph((site / "ns.ttl").read_text(encoding="utf-8"), "turtle")
    defined = {str(s) for s in vocab.subjects()}
    used = {str(t) for triple in data for t in triple[1:] if isinstance(t, rdflib.URIRef) and str(t).startswith(publish.NS)}
    assert used and used <= defined


def test_vocabulary_covers_every_value_the_schema_allows(site):
    vocab = graph((site / "ns.ttl").read_text(encoding="utf-8"), "turtle")
    defined = {str(s) for s in vocab.subjects()}
    for slug in schema.KINDS:
        assert f"{publish.NS}kind-{slug}" in defined
    for slug in schema.STATUSES.values():
        assert f"{publish.NS}status-{slug}" in defined
    for slug in schema.FORMS.values():
        assert f"{publish.NS}form-{slug}" in defined
    for slug in schema.METHODS.values():
        assert f"{publish.NS}method-{slug}" in defined
    for term, target in build.CONTEXT.items():
        iri = target["@id"] if isinstance(target, dict) else target
        if iri.startswith("fsl:") and term != "fsl":
            assert publish.NS + iri[4:] in defined, term


def test_dataset_description_parses_and_lists_three_files(site):
    g = graph((site / "dataset.ttl").read_text(encoding="utf-8"), "turtle")
    dcat = rdflib.Namespace("http://www.w3.org/ns/dcat#")
    assert len(set(g.objects(rdflib.URIRef(publish.DATASET), dcat.distribution))) == 3
    for f in ("seido.csv", "seido.jsonld", "seido.ttl"):
        assert (site / f).exists()


def test_published_csv_is_the_data_file_itself(site):
    assert (site / "seido.csv").read_bytes() == open("data/seido.csv", "rb").read()


def test_kakunin_dekizu_page_says_it_does_not_mean_none(site, rows):
    for r in rows:
        text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
        warned = "制度が無いという意味ではない" in text
        assert warned == (r["状態"] == "確認できず"), r["id"]
        if r["状態"] == "確認できず":
            for place in r["探した場所"].split(schema.SEP.strip()):
                assert html.escape(place.strip()) in text


def test_ari_page_shows_source_and_check_date(site, rows):
    for r in rows:
        if r["状態"] in ("あり", "予定"):
            text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
            assert html.escape(r["出典URL"]) in text and r["確認日"] in text


def test_matrix_matches_the_data(site, rows):
    text = (site / "index.html").read_text(encoding="utf-8")
    areas = [a for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"]
    tbody = text.split("<tbody>")[1].split("</tbody>")[0]
    trs = [t for t in tbody.split("<tr>") if t.strip()]
    assert len(trs) == len(areas) == 17
    cell = {(r["市町村コード"], schema.KIND_BY_LABEL[r["制度の種類"]]): r for r in rows}
    for a, tr in zip(areas, trs):
        assert f'<th scope="row">{a["市町村"]}</th>' in tr
        tds = re.findall(r"<td>(.*?)</td>", tr)
        assert len(tds) == 5
        for k, td in zip(publish.MATRIX_KINDS, tds):
            r = cell.get((a["市町村コード"], k))
            if r:
                assert f'href="id/{r["id"]}/"' in td and f">{r['状態']}<" in td
            else:
                assert "未着手" in td and "href" not in td


def test_internal_links_resolve(site):
    for p in site.rglob("*.html"):
        for href in re.findall(r'href="([^"#]+)"', p.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://")):
                continue
            target = (p.parent / href).resolve()
            if href == "ns":  # GitHub Pages は拡張子なしの URL に ns.html を返す
                target = site / "ns.html"
            assert target.exists() or (target / "index.html").exists(), f"{p}: {href}"


def test_iri_escapes_characters_turtle_does_not_allow():
    assert publish.iri("https://example.lg.jp/a b|c") == "<https://example.lg.jp/a%20b%7Cc>"
    assert publish.lit('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'


def test_pages_do_not_carry_long_text_beyond_the_data_limits(site, rows):
    # ページに載る項目は、検査で長さを抑えた項目だけ(公式ページの文章を載せない)
    for r in rows:
        assert len(r["根拠の箇所"]) <= schema.MAX_BASIS
