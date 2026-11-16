from futoko_lod import dbpedia as d

R = d.RESOURCE


def row(name, code, label=None, redirect=""):
    r = {"s": R + name, "c": code, "label": name if label is None else label}
    if redirect:
        r["redirect"] = redirect
    return r


def judged(areas, rows):
    return {r["市町村コード"]: r for r in d.judge(areas, rows, "2026-11-16")}


def test_one_resource_with_the_same_code_and_name_is_taken():
    j = judged({"40219": "大野城市"}, [row("大野城市", "40219")])
    assert j["40219"]["判定"] == "一致" and j["40219"]["DBpediaのURI"] == R + "大野城市"


def test_bracketed_names_are_accepted_but_other_names_are_not():
    j = judged({"40605": "川崎町", "40231": "那珂川市"}, [row("川崎町_(福岡県)", "40605", "川崎町 (福岡県)"), row("那珂川町", "40231")])
    assert j["40605"]["判定"] == "一致"
    assert j["40231"]["DBpediaのURI"] == "" and "名前が違う" in j["40231"]["判定"]


def test_missing_and_duplicated_codes_are_not_taken():
    j = judged({"40999": "見本町", "40998": "見本市"}, [row("見本市", "40998"), row("見本市_(別)", "40998", "見本市 (別)")])
    assert j["40999"]["DBpediaのURI"] == "" and "返らなかった" in j["40999"]["判定"]
    assert j["40998"]["DBpediaのURI"] == "" and "複数" in j["40998"]["判定"]


def test_redirects_are_ignored():
    j = judged({"40219": "大野城市"}, [row("大野城市", "40219"), row("大野城", "40219", "大野城", redirect=R + "大野城市")])
    assert j["40219"]["判定"] == "一致"


def test_query_asks_by_code_not_by_name():
    q = d.verify_query(["40219"])
    assert d.CODE_PROP in q and '"40219"' in q and "大野城市" not in q


def test_neighbor_names_are_matched_to_codes():
    names = {"40130": "福岡市", "40216": "小郡市", "40341": "宇美町", "40605": "川崎町"}
    assert d.split_names("福岡市、春日市、糟屋郡宇美町") == ["福岡市", "春日市", "糟屋郡宇美町"]
    assert d.match_name("糟屋郡宇美町", names) == ("40341", "宇美町", "県内")
    assert d.match_name("小郡市", names) == ("40216", "小郡市", "県内")  # 「郡」を外さない
    assert d.match_name("福岡県田川郡川崎町", names) == ("40605", "川崎町", "県内")
    assert d.match_name("佐賀県鳥栖市", names)[2] == "県外"
    assert d.match_name("春日市", names)[2] == "照合できず"
