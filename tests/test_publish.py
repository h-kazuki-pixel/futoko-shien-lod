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
        warned = "無いとは限りません。" in text and "教育委員会に聞いてみてください" in text
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
    text = (site / "hikaku" / "index.html").read_text(encoding="utf-8")
    areas = [a for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"]
    tbody = text.split("<tbody>")[1].split("</tbody>")[0]
    trs = [t for t in tbody.split("<tr>") if t.strip()]
    assert len(trs) == len(areas) == 17
    cell = {(r["市町村コード"], schema.KIND_BY_LABEL[r["制度の種類"]]): r for r in rows}
    for a, tr in zip(areas, trs):
        assert f'<th scope="row"><a href="../shi/{a["市町村コード"]}/">{a["市町村"]}</a></th>' in tr
        tds = re.findall(r"<td>(.*?)</td>", tr)
        assert len(tds) == 5
        for k, td in zip(publish.MATRIX_KINDS, tds):
            r = cell.get((a["市町村コード"], k))
            if r:
                assert f'href="../id/{r["id"]}/"' in td and f">{r['状態']}<" in td
                # 一覧に載っていないことを根拠にした「なし」には、必ず ※ が付く
                assert ("※" in td) == publish.list_based_none(r)
            else:
                assert "未着手" in td and "href" not in td


def test_internal_links_resolve(site):
    for p in site.rglob("*.html"):
        for href in re.findall(r'href="([^"#]+)"', p.read_text(encoding="utf-8")):
            if href.startswith(("http://", "https://")):
                continue
            target = (p.parent / href).resolve()
            if href in ("ns", "../ns", "shapes", "../shapes"):  # GitHub Pages は拡張子なしの URL に .html を返す
                target = site / (href.split("/")[-1] + ".html")
            assert target.exists() or (target / "index.html").exists(), f"{p}: {href}"


def test_iri_escapes_characters_turtle_does_not_allow():
    assert publish.iri("https://example.lg.jp/a b|c") == "<https://example.lg.jp/a%20b%7Cc>"
    assert publish.lit('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'


def test_pages_do_not_carry_long_text_beyond_the_data_limits(site, rows):
    # ページに載る項目は、検査で長さを抑えた項目だけ(公式ページの文章を載せない)
    for r in rows:
        assert len(r["根拠の箇所"]) <= schema.MAX_BASIS


REC = {c: "" for c in schema.COLUMNS} | {
    "id": "40999-fs-hojo", "市町村コード": "40999", "市町村": "見本町",
    "制度の種類": "フリースクール等の利用料の補助(保護者向け)", "状態": "確認できず",
}


def recs(**kw):
    return {"torinaoshi": [], "saikakunin": [], "toiawase": []} | kw


def test_recheck_line_counts_only_filled_judgements():
    rows = [{"id": "40999-fs-hojo", "判定": "合っている"}, {"id": "40999-fs-hojo", "判定": ""}, {"id": "x", "判定": "違う"}]
    assert publish.recheck_line(REC, recs(saikakunin=rows)) == "人が出典と見比べた項目は 1 / 2(合っている 1)"
    assert "まだ出典と見比べていない" in publish.recheck_line(REC, recs(saikakunin=[{"id": "40999-fs-hojo", "判定": ""}]))
    assert publish.recheck_line(REC, recs()) == ""


def test_inquiry_never_shows_the_answer_text():
    base = {"日付": "2026-11-20", "市町村コード": "40999", "市町村": "見本町", "担当課": "学校教育課", "方法": "メール",
            "種類": "フリースクール等の利用料の補助(保護者向け)", "反映したid": ""}
    for kahi in ("", "不可", "差し支えなし", "差し支えあり"):
        out = publish.inquiry_lines(REC, recs(toiawase=[base | {"回答": "担当の見本さんによると制度は無い", "公開の可否": kahi}]))
        assert len(out) == 1 and "見本さん" not in out[0] and "制度は無い" not in out[0]
    declined = publish.inquiry_lines(REC, recs(toiawase=[base | {"回答": "a", "公開の可否": "差し支えあり"}]))
    assert "差し支えがあるとのこと" in declined[0]
    fine = publish.inquiry_lines(REC, recs(toiawase=[base | {"回答": "a", "公開の可否": "差し支えなし"}]))
    assert "差し支えがある" not in fine[0] and "回答があった" in fine[0]
    waiting = publish.inquiry_lines(REC, recs(toiawase=[base | {"回答": "", "公開の可否": ""}]))
    assert "回答はまだ無い" in waiting[0]


def test_inquiry_is_matched_by_reflected_id_first():
    base = {"日付": "2026-11-20", "市町村コード": "40999", "市町村": "見本町", "担当課": "学校教育課", "方法": "電話",
            "種類": "フリースクール等の利用料の補助(保護者向け)", "回答": "a", "公開の可否": ""}
    other_town = publish.inquiry_lines(REC, recs(toiawase=[base | {"市町村コード": "40998", "反映したid": ""}]))
    other_kind = publish.inquiry_lines(REC, recs(toiawase=[base | {"種類": "学びの多様化学校", "反映したid": ""}]))
    other_id = publish.inquiry_lines(REC, recs(toiawase=[base | {"反映したid": "40999-fs-hojo-2"}]))
    mine = publish.inquiry_lines(REC, recs(toiawase=[base | {"反映したid": "40999-fs-hojo-2 40999-fs-hojo"}]))
    assert other_town == [] and other_kind == [] and other_id == []
    assert "この1件に反映した" in mine[0]


def test_refetch_lines_say_when_a_source_could_not_be_fetched():
    rows = [
        {"id": "40999-fs-hojo", "役割": "出典", "URL": "u", "取得日時": "2026-11-15T19:31:37+00:00", "取得": "取得できず(HTTP 404)", "判定": ""},
        {"id": "40999-fs-hojo", "役割": "探した場所", "URL": "v", "取得日時": "2026-11-15T19:32:00+00:00", "取得": "取得", "判定": ""},
    ]
    lines = publish.refetch_lines(REC, recs(torinaoshi=rows))
    assert lines[0] == "出典: 2026-11-16 に取り直したが、取得できなかった(HTTP 404)"
    assert "1ページを取り直した(取得できた 1)" in lines[1]


def test_record_pages_show_the_real_records(site, rows):
    records = publish.load_records("data")
    for r in rows:
        text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
        for line in publish.refetch_lines(r, records) + publish.inquiry_lines(r, records):
            assert html.escape(line) in text
        if publish.recheck_line(r, records):
            assert html.escape(publish.recheck_line(r, records)) in text


def test_strings_carry_language_and_ids_do_not(site):
    g = graph((site / "seido.ttl").read_text(encoding="utf-8"), "turtle")
    fsl = rdflib.Namespace(publish.NS)
    sdo = rdflib.Namespace("https://schema.org/")
    assert all(o.language == "ja" for o in g.objects(None, fsl.note))
    assert all(o.language is None for o in g.objects(None, sdo.identifier))
    assert all(isinstance(o, rdflib.URIRef) for o in g.objects(None, fsl.searchedAt))


def test_list_based_none_is_explained_on_its_page(site, rows):
    for r in rows:
        text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
        assert ("公式の一覧に載っていない</strong>" in text) == publish.list_based_none(r), r["id"]


def test_only_existing_systems_are_government_services(site, rows):
    g = graph((site / "seido.ttl").read_text(encoding="utf-8"), "turtle")
    sdo = rdflib.Namespace("https://schema.org/")
    fsl = rdflib.Namespace(publish.NS)
    services = {str(s) for s in g.subjects(rdflib.RDF.type, sdo.GovernmentService)}
    assert services == {f"{build.BASE}id/{r['id']}" for r in rows if r["状態"] in ("あり", "予定")}
    assert len(set(g.subjects(rdflib.RDF.type, fsl.Record))) == len(rows)


def test_scope_note_counts_come_from_the_data(site, rows):
    text = (site / "about" / "index.html").read_text(encoding="utf-8")
    areas = schema.read_csv("data/shichoson.csv")
    have = {r["市町村コード"] for r in rows if r["制度の種類"] == "学びの多様化学校"} - {"40000"}
    assert f"県内60市町村のうち {len(have)}" in text
    for a in areas:
        if a["市町村コード"] != "40000" and a["市町村コード"] not in have:
            assert a["市町村"] in text.split("まだ行が無いのは")[1].split("。")[0]


def test_about_page_numbers_come_from_the_data(site, rows):
    text = re.sub(r"<[^>]+>", "", (site / "about" / "index.html").read_text(encoding="utf-8"))
    c = {s: sum(r["状態"] == s for r in rows) for s in schema.STATUSES}
    assert f"記録{len(rows)}" in text.replace("\n", "")
    assert f"あり・予定{c['あり'] + c['予定']}" in text.replace("\n", "")
    assert f"「確認できず」が {c['確認できず']} 件ある" in text
    judged = sum(bool(r["判定"]) for r in schema.read_csv("data/saikakunin.csv"))
    assert f"項目のうち {judged}。" in text


def test_combination_page_matches_both_sources(site, rows):
    pupils = schema.read_csv("data/kumiawase/jidou_seito.csv")
    text = (site / "kumiawase" / "index.html").read_text(encoding="utf-8")
    areas = [a for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"]
    by_uri = {p["標準地域コードのURI"]: p for p in pupils}
    trs = [tr for tr in text.split("<tbody>")[1].split("</tbody>")[0].split("<tr>") if tr.strip()]
    assert len(trs) == len(areas)
    for a, tr in zip(areas, trs):
        p = by_uri[build.SAC + a["市町村コード"]]
        cells = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr)]
        mine = [r for r in rows if r["市町村コード"] == a["市町村コード"] and schema.KIND_BY_LABEL[r["制度の種類"]] in publish.MATRIX_KINDS]
        n = {s: sum(r["状態"] == s for r in mine) for s in schema.STATUSES}
        assert f'<th scope="row">{a["市町村"]}</th>' in tr
        assert cells[0] == (f'{int(p["小学校児童数"]):,}' if p["小学校児童数"] else "返らなかった")
        assert cells[1] == (f'{int(p["中学校生徒数"]):,}' if p["中学校生徒数"] else "返らなかった")
        assert cells[2] == str(n["あり"] + n["予定"]) and cells[4] == str(n["確認できず"])
        assert cells[3].rstrip("※") == str(n["なし"])
        assert cells[3].endswith("※") == any(publish.list_based_none(r) for r in mine)
        assert int(cells[2]) + int(cells[3].rstrip("※")) + int(cells[4]) + int(cells[5]) == 5
    years = {p["小学校児童数の年"] for p in pupils if p["小学校児童数の年"]}
    assert all(f"{y}年" in text for y in years)
    for must in ("いまの人数ではない", "良し悪しを比べる表ではない", "市町が「無い」と答えたものではない", "e-Stat 統計LOD"):
        assert must in text
    assert "無かった。市に" not in text  # 「返らなかった」を「無い」と言い切らない
    assert (site / "kumiawase.csv").read_bytes() == open("data/kumiawase/jidou_seito.csv", "rb").read()


def test_hojo_page_says_the_data_does_not_hold_the_application_period(site, rows):
    """補助の「あり」は、いま申請できるという意味ではない(弱い所 33)。"""
    hojo = [r for r in rows if publish.kind_slug(r) in ("fs-hojo", "fs-unei") and r["状態"] in ("あり", "予定")]
    assert hojo
    for r in hojo:
        text = (site / "id" / r["id"] / "index.html").read_text(encoding="utf-8")
        assert "いま申請を受け付けているかは、この一覧には載せていません" in text
    other = next(r for r in rows if publish.kind_slug(r) == "shien-center" and r["状態"] == "あり")
    assert "いま申請を受け付けているか" not in (site / "id" / other["id"] / "index.html").read_text(encoding="utf-8")


def test_second_source_node_is_the_same_in_turtle_and_jsonld():
    # 第2の出典(弱い所18)。見本は作りもの
    r = REC | {"状態": "あり", "制度名": "見本教室", "出典URL": "https://www.town.mihon.lg.jp/a.html", "出典名": "町のページ",
               "根拠の箇所": "見本教室", "出典URL_2": "https://www.town.mihon.lg.jp/b.pdf", "出典名_2": "案内",
               "根拠の箇所_2": "通う教室", "出典2の項目": "制度名 | 備考", "備考": "場所は図書館", "確認日": "2026-11-16",
               "確認方法": "機械の読み取り", "制度の種類": schema.KINDS["shien-center"], "id": "40999-shien-center"}
    node = build.to_node(r)
    assert node["additionalSource"]["@id"].endswith("id/40999-shien-center#source2")
    assert node["additionalSource"]["supports"] == ["schema:name", "fsl:note"]
    ttl = graph(publish.nodes_turtle([node]), "turtle")
    jld = graph(json.dumps({"@context": build.CONTEXT, "@graph": [node]}, ensure_ascii=False), "json-ld")
    assert to_isomorphic(ttl) == to_isomorphic(jld)
    s2 = rdflib.URIRef(node["additionalSource"]["@id"])
    fsl = rdflib.Namespace(build.BASE + "ns#")
    assert (s2, fsl.supports, rdflib.URIRef("https://schema.org/name")) in jld
    assert (s2, rdflib.URIRef("http://purl.org/dc/terms/source"), rdflib.URIRef("https://www.town.mihon.lg.jp/b.pdf")) in jld


# ---- ほかの語彙との対応(点5) ----

AIKATA = {"同じ", "同じ(下位の性質)", "近い", "対応なし"}


def test_taiou_covers_every_column_and_property():
    rows = schema.read_csv(publish.TAIOU_PATH)
    assert {r["合い方"] for r in rows} <= AIKATA
    items = {r["このデータの項目"] for r in rows}
    # 語彙で決めた性質は、全部どこかの行にある(対応なしでも書く)
    assert {f"fsl:{name}" for name in publish.PROPERTIES} - {"fsl:supports"} <= items
    for r in rows:
        if r["合い方"] == "対応なし":
            assert not r["相手の項目"] and not r["相手のIRI"], r
        else:
            assert r["相手の語彙"] and r["相手の項目"], r


def test_subproperties_match_the_table():
    rows = schema.read_csv(publish.TAIOU_PATH)
    sub = {(r["このデータの項目"], r["相手のIRI"]) for r in rows if r["合い方"] == "同じ(下位の性質)"}
    want = {(f"fsl:{k}", publish.PREFIXES[v.split(":")[0]] + v.split(":")[1]) for k, v in publish.SUBPROPERTY_OF.items()}
    assert sub == want


def test_vocab_turtle_has_subproperties():
    g = graph(publish.vocab_turtle(), "turtle")
    RDFS = rdflib.RDFS
    fsl = rdflib.Namespace(build.BASE + "ns#")
    assert (fsl.note, RDFS.subPropertyOf, rdflib.URIRef("http://www.w3.org/2004/02/skos/core#note")) in g
    assert (fsl.kind, RDFS.subPropertyOf, rdflib.URIRef("https://schema.org/category")) in g
    assert (fsl.dateChecked, RDFS.subPropertyOf, rdflib.URIRef("http://purl.org/dc/terms/date")) in g


def test_kind_catalog_covers_all_kinds(site):
    kinds = schema.read_csv(publish.TAIOU_SHURUI_PATH)
    assert {k["種類"] for k in kinds} == set(schema.KINDS.values())
    assert {k["このデータの値"] for k in kinds} == {f"fsl:kind-{s}" for s in schema.KINDS}
    assert (site / "goi_taiou.csv").exists() and (site / "goi_taiou_shurui.csv").exists()
    assert "ほかの語彙との対応" in (site / "ns.html").read_text(encoding="utf-8")


# ---- 確かめた記録を RDF に(公5) ----

def test_activities_never_carry_the_answer_text():
    toi = {"日付": "2026-11-20", "市町村コード": "40999", "市町村": "見本町", "担当課": "学校教育課", "方法": "メール",
           "種類": "fs-hojo", "回答": "担当の見本さんによると制度は無い", "公開の可否": "", "反映したid": ""}
    sai = [{"id": "40999-fs-hojo", "判定": "合っている", "確認日": "2026-11-16"}, {"id": "40999-fs-hojo", "判定": "", "確認日": ""}]
    tor = [{"id": "40999-fs-hojo", "役割": "探した場所", "URL": "https://www.town.mihon.lg.jp/a.html",
            "取得日時": "2026-11-16T08:00:00+00:00", "取得": "取得", "判定": "", "本文の印": "x"}]
    acts = publish.activities(REC, recs(toiawase=[toi], saikakunin=sai, torinaoshi=tor))
    text = json.dumps(acts, ensure_ascii=False)
    assert "見本さん" not in text and "制度は無い" not in text
    kinds = {a["@type"][1]: a for a in acts}
    assert kinds["fsl:Inquiry"]["answerState"] == "回答があった"
    assert kinds["fsl:HumanReview"]["itemsChecked"] == "1" and kinds["fsl:HumanReview"]["itemsTotal"] == "2"
    assert kinds["fsl:Refetch"]["used"] == "https://www.town.mihon.lg.jp/a.html"
    node = publish.with_activities(build.to_node(REC | {"確認日": "2026-11-16", "確認方法": "機械の読み取り",
                                                       "探した場所": "https://www.town.mihon.lg.jp/a.html"}),
                                   REC, recs(toiawase=[toi], saikakunin=sai, torinaoshi=tor))
    ttl = graph(publish.nodes_turtle([node]), "turtle")
    jld = graph(json.dumps({"@context": build.CONTEXT, "@graph": [node]}, ensure_ascii=False), "json-ld")
    assert to_isomorphic(ttl) == to_isomorphic(jld)
    PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")
    assert len(list(jld.subjects(rdflib.RDF.type, PROV.Activity))) == 3


def test_published_files_have_activities_but_repo_jsonld_does_not(site):
    pub = json.loads((site / "seido.jsonld").read_text(encoding="utf-8"))
    assert any("checkActivity" in n for n in pub["@graph"])
    repo = json.loads(open("data/seido.jsonld", encoding="utf-8").read())
    assert not any("checkActivity" in n for n in repo["@graph"])


# ---- 隣接(DBpedia Japanese、点7) ----

def test_neighbors_use_only_pairs_written_on_both_sides():
    rows = schema.read_csv("data/rinsetsu.csv")
    both = {(r["市町村コード"], r["隣接する市町村コード"]) for r in rows if r["判定"] == "県内(両方にある)"}
    assert both and all((b, a) in both for a, b in both)
    recs_ = publish.load_records("data")
    assert {r["判定"] for r in recs_["rinsetsu"]} == {"県内(両方にある)"}
    # 大野城市の隣に太宰府市がある(「府」を県名と取り違えない)
    assert "40221" in publish.neighbors_of("40219", recs_)


def test_neighbor_gaps_only_unknown_cells_with_ari_next_door(site, rows):
    recs_ = publish.load_records("data")
    areas = schema.read_csv("data/shichoson.csv")
    for r, found in publish.neighbor_gaps(rows, areas, recs_):
        assert r["状態"] == "確認できず"
        assert found and all(o["状態"] in ("あり", "予定") and publish.kind_slug(o) == publish.kind_slug(r) for o in found)
        assert all(o["市町村コード"] in publish.neighbors_of(r["市町村コード"], recs_) for o in found)
    assert (site / "rinsetsu.csv").exists()
    assert "隣り合う市町と並べる" in (site / "kumiawase" / "index.html").read_text(encoding="utf-8")


def test_rinsetsu_is_not_mixed_into_the_rdf(site):
    # DBpedia Japanese の値(CC BY-SA)は、このデータの RDF(CC BY)に入れない
    assert "隣接" not in (site / "seido.ttl").read_text(encoding="utf-8")


# ---------- 保護者向けのページ(11/17) ----------

def test_every_area_with_rows_has_a_page_and_is_linked_from_the_top(site, rows):
    top = (site / "index.html").read_text(encoding="utf-8")
    codes = {r["市町村コード"] for r in rows} - {"40000"}
    for c in codes:
        assert (site / "shi" / c / "index.html").exists(), c
        assert f'href="shi/{c}/"' in top, c
    assert not (site / "shi" / "40000").exists()


def test_area_page_has_a_card_per_kind_and_plain_words(site, rows):
    areas = schema.read_csv("data/shichoson.csv")
    for a in areas:
        if a["市町村コード"] == "40000" or not (site / "shi" / a["市町村コード"]).exists():
            continue
        text = (site / "shi" / a["市町村コード"] / "index.html").read_text(encoding="utf-8")
        mine = [r for r in rows if r["市町村コード"] == a["市町村コード"]]
        if a["福岡都市圏"] == "○":
            for k in publish.MATRIX_KINDS:
                assert f"<h3>{publish.KIND_PLAIN[k][0]}</h3>" in text, (a["市町村"], k)
        for r in mine:
            if r["状態"] in ("あり", "予定"):
                assert html.escape(r["出典URL"]) in text and f'id/{r["id"]}/' in text
            if r["状態"] == "確認できず":
                assert "無いとは限りません" in text
        # 技術の言葉は、保護者向けのページに出さない
        for word in ("Turtle", "URI", "SHACL", "照合"):
            assert word not in text.split("<main")[1].split("</main>")[0], (a["市町村"], word)


def test_top_page_speaks_to_parents_first(site):
    text = (site / "index.html").read_text(encoding="utf-8")
    main = text.split("<main")[1]
    assert main.index("お住まいの市町村を選んでください") < main.index("載せている5つの支援")
    assert "<table" not in main  # 表は見比べるページに分けた
    for word in ("Turtle", "SHACL", "JSON-LD"):
        assert word not in main


def test_area_page_puts_found_support_first_and_gives_a_place_to_ask(site, rows):
    areas = [a for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"]
    for a in areas:
        text = (site / "shi" / a["市町村コード"] / "index.html").read_text(encoding="utf-8")
        mine = [r for r in rows if r["市町村コード"] == a["市町村コード"]]
        if any(r["状態"] in ("あり", "予定") for r in mine) and any(r["状態"] == "確認できず" for r in mine):
            assert text.index("見つかった支援</h2>") < text.index("公式ページでは見つからなかった支援</h2>"), a["市町村"]
        url = publish.ask_url(mine)
        if url:
            assert f'href="{html.escape(url)}"' in text and "公式ページを開く" in text, a["市町村"]
            assert schema.is_official_url(url, schema.load_extra_domains())
        # 内部の記録の言葉(なしの根拠)は、このページには出さない
        for r in mine:
            if r["なしの根拠"]:
                assert html.escape(r["なしの根拠"]) not in text


def test_area_summary_counts_match_the_cards(site, rows):
    for a in schema.read_csv("data/shichoson.csv"):
        f = site / "shi" / a["市町村コード"] / "index.html"
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        n = sum(r["市町村コード"] == a["市町村コード"] and r["状態"] in ("あり", "予定")
                and publish.kind_slug(r) in publish.MATRIX_KINDS for r in rows)
        summary = text.split('<p class="summary">')[1].split("</p>")[0]
        assert (f"{n}つ" in summary) if n else ("まだありません" in summary), a["市町村"]


def test_dates_on_parent_pages_are_written_in_japanese_style(site, rows):
    assert publish.jp_date("2026-11-06") == "2026年11月6日" and publish.jp_date("") == ""
    r = next(r for r in rows if r["状態"] == "あり" and r["市町村コード"] != "40000")
    text = (site / "shi" / r["市町村コード"] / "index.html").read_text(encoding="utf-8")
    assert publish.jp_date(r["確認日"]) + "に公式ページで確認" in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}", re.sub(r"<[^>]+>", "", text.split("<main")[1].split("</main>")[0]))
