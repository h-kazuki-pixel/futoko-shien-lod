"""形(SHACL)の検査。いまの公開データが通ること、壊した公開データが落ちること。"""

import re
import shutil

import pytest

from futoko_lod import publish, schema, shapes

pytest.importorskip("pyshacl")
rdflib = pytest.importorskip("rdflib")

BASE = "https://h-kazuki-pixel.github.io/futoko-shien-lod/"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    publish.write_site(out)
    return out


def broken(site, tmp_path, change, file="seido.ttl"):
    """公開の一式を写し、1か所を壊してから検査する。壊せなかったら(置き換えが空振りしたら)テストの誤り。"""
    for f in ("seido.ttl", "dataset.ttl"):
        shutil.copy(site / f, tmp_path / f)
    text = (tmp_path / file).read_text(encoding="utf-8")
    new = change(text)
    assert new != text, "壊す置き換えが空振りした"
    (tmp_path / file).write_text(new, encoding="utf-8")
    ok, problems, _ = shapes.validate(tmp_path)
    assert not ok
    return "\n".join(problems)


def block(text, rid):
    """1件の記録の節(主語から次の空行まで)。"""
    m = re.search(rf"^<{re.escape(BASE)}id/{re.escape(rid)}>\n.*?\n\n", text, re.S | re.M)
    return m.group(0)


def replace_in(rid, old, new):
    def change(text):
        b = block(text, rid)
        return text.replace(b, b.replace(old, new, 1))
    return change


def first_row(status, kind=None):
    for r in schema.load("data/seido.csv"):
        if r["状態"] == status and (kind is None or schema.KIND_BY_LABEL[r["制度の種類"]] == kind):
            return r
    raise AssertionError((status, kind))


def test_shapes_file_is_up_to_date():
    assert shapes.OUT.read_text(encoding="utf-8") == shapes.shapes_turtle(), "python -m futoko_lod.shapes を回す"


def test_shapes_are_valid_shacl_core_only(site):
    g = rdflib.Graph().parse(data=shapes.shapes_turtle(), format="turtle")
    SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    # SHACL-SPARQL や SHACL-AF は使わない(どの道具でも同じ結果になるように)
    for p in (SH.sparql, SH.select, SH.ask, SH.rule, SH.target, SH.targetSubjectsOf):
        assert not list(g.subject_objects(p)), p
    assert (site / "shapes.ttl").read_text(encoding="utf-8") == shapes.shapes_turtle()


def test_published_data_conforms(site):
    ok, problems, n = shapes.validate(site)
    assert ok, problems
    assert n > 1000


def test_dataset_points_to_the_shapes(site):
    g = rdflib.Graph().parse(site / "dataset.ttl", format="turtle")
    DCT = rdflib.Namespace("http://purl.org/dc/terms/")
    assert rdflib.URIRef(shapes.SHAPES_IRI) in set(g.objects(None, DCT.conformsTo))


def test_shapes_page_lists_every_shape(site):
    text = (site / "shapes.html").read_text(encoding="utf-8")
    for name in ("RecordShape", "AriYoteiRule", "NashiRule", "KakuninDekizuRule", "AreaShape", "RefetchShape", "DatasetShape"):
        assert f'id="{name}"' in text
    assert 'href="shapes"' in (site / "index.html").read_text(encoding="utf-8")


# ---------- 壊したら落ちる ----------

def test_ari_without_source_fails(site, tmp_path):
    r = first_row("あり")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]),
                                                     re.sub(r"    dct:source <[^>]*> ;\n", "", block(t, r["id"]), count=1)))
    assert "「あり」「予定」なのに" in out


def test_fs_hojo_without_payment_form_fails(site, tmp_path):
    r = first_row("あり", "fs-hojo")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]),
                                                     re.sub(r"    fsl:paymentForm [^\n]*\n", "", block(t, r["id"]))))
    assert "補助の形" in out


def test_nashi_must_not_be_a_government_service(site, tmp_path):
    r = first_row("なし")
    out = broken(site, tmp_path, replace_in(r["id"], "a fsl:Record ;", "a fsl:Record, schema:GovernmentService ;"))
    assert "「なし」の決まり" in out


def test_kakunin_dekizu_needs_searched_places_and_no_source(site, tmp_path):
    r = first_row("確認できず")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]),
                                                     re.sub(r"    fsl:searchedAt [^\n]*\n", "", block(t, r["id"]))))
    assert "「確認できず」の決まり" in out
    out = broken(site, tmp_path, replace_in(r["id"], "    fsl:checkMethod",
                                            "    dct:source <https://www.pref.fukuoka.lg.jp/x> ;\n    fsl:checkMethod"))
    assert "「確認できず」の決まり" in out


def test_unofficial_source_fails(site, tmp_path):
    r = first_row("あり")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]),
                                                     re.sub(r"dct:source <[^>]*>", "dct:source <https://example.com/a>", block(t, r["id"]), count=1)))
    assert "公式サイトだけ" in out


def test_setter_subsidy_on_a_city_fails(site, tmp_path):
    r = first_row("あり", "fs-hojo")
    out = broken(site, tmp_path, replace_in(r["id"], "fsl:kind fsl:kind-fs-hojo", "fsl:kind fsl:kind-fs-unei"))
    assert "設置者向けの補助" in out


def test_long_basis_phrase_fails(site, tmp_path):
    r = first_row("あり")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]), re.sub(
        r'fsl:basisPhrase "[^"]*"@ja', 'fsl:basisPhrase "' + "あ" * (schema.MAX_BASIS + 1) + '"@ja', block(t, r["id"]), count=1)))
    assert f"{schema.MAX_BASIS}字まで" in out


def test_two_statuses_fail(site, tmp_path):
    r = first_row("あり")
    out = broken(site, tmp_path, replace_in(r["id"], "fsl:status fsl:status-ari", "fsl:status fsl:status-ari, fsl:status-yotei"))
    assert "状態は" in out


def test_review_checked_must_not_exceed_total(site, tmp_path):
    out = broken(site, tmp_path, lambda t: re.sub(r'fsl:itemsChecked "\d+"', 'fsl:itemsChecked "999"', t, count=1))
    assert "見比べた項目の数" in out


def test_collation_without_fetch_fails(site, tmp_path):
    out = broken(site, tmp_path, lambda t: re.sub(
        r'fsl:fetchResult "取得"@ja( ;\n(?:    [^\n]*\n)*?    fsl:collationResult)', r'fsl:fetchResult "取得できず(HTTP 404)"@ja\1', t, count=1))
    assert "照合の結果がある" in out


def test_dataset_without_conforms_to_fails(site, tmp_path):
    out = broken(site, tmp_path, lambda t: t.replace(f"<{shapes.SHAPES_IRI}>", f"<{BASE}other>"), "dataset.ttl")
    assert "形(shapes)への" in out


# ---------- 公式サイトの決まりが schema.py と同じか ----------

def test_official_pattern_agrees_with_schema():
    extra = schema.load_extra_domains()
    pat = re.compile(shapes.official_pattern(extra), re.I)
    urls = set()
    for r in schema.load("data/seido.csv"):
        for key in ("出典URL", "出典URL_2", "要綱URL"):
            if r[key]:
                urls.add(r[key])
        urls |= {p.strip() for p in r["探した場所"].split("|") if p.strip()}
    urls |= {
        "https://example.com/a", "https://city.fukuoka.lg.jp.example.com/", "https://example.com/?x=.lg.jp",
        "https://www.city.fukuoka.lg.jp:443/a", "http://www.pref.fukuoka.lg.jp", "https://www.town.umi.lg.jp/x",
        "https://www.city.kasuga.fukuoka.jp/", "https://kasuga.fukuoka.jp/", "https://www1.g-reiki.net/city.kasuga.fukuoka/x",
        "https://www1.g-reiki.net/city.other.fukuoka/x", "https://www.mext.go.jp/a", "ftp://www.mext.go.jp/a",
        # 点検で食い違いが見つかった書き方(11/17)。どれも落とす
        "https://evil.com\\@www.city.fukuoka.lg.jp/a", "https://user@www.city.fukuoka.lg.jp/a",
        "https://my_host.city.fukuoka.lg.jp/", "https://www.city.fukuoka.lg.jp:/a",
        "https://user@www1.g-reiki.net/city.kasuga.fukuoka/x", "https://www.city.fukuoka.lg.jp\t/a",
        "https://www1.g-reiki.net/city.kasuga.fukuoka/../city.other.fukuoka/x",
        "https://ops-jg.d1-law.com/opensearch/srjbf01/init?jctcd=8a9160eadb9",
        "https://www1.g-reiki.net:443/city.kasuga.fukuoka/x", "https://www.city.x.lg.jp:99999/a",
        "https://www.city.x.lg.jp/a?next=/./b", "https://www.city.x.lg.jp/a#/../x",
        "https://www1.g-reiki.net/city.kasuga.fukuoka/%2e%2e/city.other/x", "https://www1.g-reiki.net/city.kasuga.fukuoka/%2E%2E/x",
        # 通すもの
        "https://ops-jg.d1-law.com/opensearch/srjbf01/init?jctcd=8A9160EADB&houcd=H1",
    }
    unsafe = re.compile(shapes.UNSAFE_URL_PATTERN, re.I)
    for u in sorted(urls):
        by_shape = bool(pat.search(u)) and not unsafe.search(u)
        assert by_shape == schema.is_official_url(u, extra), u
    for u in ("https://evil.com\\@www.city.fukuoka.lg.jp/a", "https://www1.g-reiki.net/city.kasuga.fukuoka/../city.other.fukuoka/x",
              "https://ops-jg.d1-law.com/opensearch/srjbf01/init?jctcd=8a9160eadb9"):
        assert not schema.is_official_url(u, extra), u


def test_patterns_use_only_xpath_escapes():
    # XPath の正規表現で使える逃がし文字だけを使う(ほかの SHACL の道具でも形を読めるように)
    g = rdflib.Graph().parse(data=shapes.shapes_turtle(), format="turtle")
    SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    allowed = set("\\.?*+()[]{}|^$-sdwSDWnrt")
    for pat in g.objects(None, SH.pattern):
        for m in re.finditer(r"\\(.)", str(pat)):
            assert m.group(1) in allowed, (str(pat), m.group(0))
    assert shapes.xpath_escape("a&b~c#d.e") == "a&b~c#d\\.e"


# ---------- 点検で、壊すテストが無いと言われた形(11/17) ----------

def test_guideline_url_without_state_fails(site, tmp_path):
    r = next(r for r in schema.load("data/seido.csv") if r["状態"] == "あり" and not r["要綱の状況"])
    out = broken(site, tmp_path, replace_in(r["id"], "    fsl:checkMethod",
                                            "    fsl:guideline <https://www.pref.fukuoka.lg.jp/y> ;\n    fsl:checkMethod"))
    assert "要綱の状況" in out


def test_second_source_must_be_official_and_differ_from_source(site, tmp_path):
    rid = next(r["id"] for r in schema.load("data/seido.csv") if r["出典URL_2"])
    out = broken(site, tmp_path, lambda t: re.sub(
        r"(<" + re.escape(BASE) + "id/" + re.escape(rid) + r"#source2>\n(?:    [^\n]*\n)*?    dct:source )<[^>]*>",
        r"\1<https://example.com/b>", t, count=1))
    assert "第2の出典も公式サイトだけ" in out
    src = next(r["出典URL"] for r in schema.load("data/seido.csv") if r["id"] == rid)
    out = broken(site, tmp_path, lambda t: re.sub(
        r"(<" + re.escape(BASE) + "id/" + re.escape(rid) + r"#source2>\n(?:    [^\n]*\n)*?    dct:source )<[^>]*>",
        lambda m: m.group(1) + publish.iri(src), t, count=1))
    assert "出典と同じ URL" in out


def test_second_source_supporting_an_empty_field_fails(site, tmp_path):
    r = next(r for r in schema.load("data/seido.csv") if r["出典URL_2"] and not r["開始"])
    out = broken(site, tmp_path, lambda t: re.sub(
        r"(<" + re.escape(BASE) + "id/" + re.escape(r["id"]) + r"#source2>\n(?:    [^\n]*\n)*?    fsl:supports )",
        r"\1fsl:startText, ", t, count=1))
    assert "記録の側で空" in out


def test_area_outside_fukuoka_fails(site, tmp_path):
    out = broken(site, tmp_path, lambda t: t.replace("<http://data.e-stat.go.jp/lod/sac/C40219>", "<http://data.e-stat.go.jp/lod/sac/C13101>"))
    assert "C13101" in out


def test_machine_read_nashi_needs_a_source(site, tmp_path):
    r = next(r for r in schema.load("data/seido.csv") if r["状態"] == "なし" and r["確認方法"] == "機械の読み取り")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]),
                                                     re.sub(r"    dct:source <[^>]*> ;\n", "", block(t, r["id"]), count=1)))
    assert "「なし」の決まり" in out


def test_kakunin_dekizu_must_not_be_a_government_service(site, tmp_path):
    r = first_row("確認できず")
    out = broken(site, tmp_path, replace_in(r["id"], "a fsl:Record ;", "a fsl:Record, schema:GovernmentService ;"))
    assert "「確認できず」の決まり" in out


def test_dot_dot_in_a_url_fails(site, tmp_path):
    r = first_row("確認できず")
    out = broken(site, tmp_path, lambda t: t.replace(block(t, r["id"]), re.sub(
        r"fsl:searchedAt <(https?://[^/>]+)/", r"fsl:searchedAt <\1/../", block(t, r["id"]), count=1)))
    assert "公式サイトの URL" in out
