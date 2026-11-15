import json

from futoko_lod import build, kumiawase as k

A, N, I = k.SAC + "40219", k.SAC + "40231", k.SAC + "40230"


def obs(plain, area, ind, year, value):
    return {"plain": plain, "area": "http://data.e-stat.go.jp/lod/sac/" + area, "ind": k.CODE + ind, "t": year, "v": value}


def test_area_uris_come_from_the_published_jsonld(tmp_path):
    doc = json.loads(build.build())
    uris = k.area_uris(codes={"40219", "40231"})
    assert set(uris) == {A, N} and uris[A] == "大野城市"
    assert set(k.area_uris()) == {n["areaServed"]["@id"] for n in doc["@graph"]}


def test_latest_year_wins_and_ties_go_to_the_newer_code():
    got = k.latest_pupils([obs(A, "C40219-20110301", "E2501", "2014", "100"), obs(A, "C40219-20110301", "E2501", "2015", "110.0")])
    assert got[A]["E2501"] == ("2015", 110, "C40219-20110301")
    tie = [obs(A, "C40219-20070101", "E2501", "2015", "1"), obs(A, "C40219-20110301", "E2501", "2015", "2")]
    assert k.latest_pupils(tie)[A]["E2501"][2] == k.latest_pupils(tie[::-1])[A]["E2501"][2] == "C40219-20110301"


def test_single_predecessor_is_used_only_when_the_current_code_has_no_value():
    before = [obs(N, "C40305-19720401", "E2501", "2015", "300")]
    got = k.latest_pupils([], before)
    assert got[N]["E2501"] == ("2015", 300, "C40305-19720401") and "C40305" in got[N]["備考"]
    own = [obs(N, "C40231-20181001", "E2501", "2014", "290")]
    assert k.latest_pupils(own, before)[N]["E2501"] == ("2014", 290, "C40231-20181001")


def test_merged_predecessors_are_not_taken_as_the_value_of_the_city():
    before = [obs(I, "C40222-19921001", "E2501", "2015", "400"), obs(I, "C40462-19650401", "E2501", "2015", "90")]
    got = k.latest_pupils([], before)
    assert "E2501" not in got[I] and "足していない" in got[I]["備考"]
    row = k.table({I: "糸島市"}, got, "2026-11-16")[0]
    assert row["小学校児童数"] == "" and "複数" in row["備考"]


def test_table_does_not_say_none_when_it_only_did_not_come_back():
    t = k.table({A: "大野城市", N: "那珂川市"}, k.latest_pupils([obs(A, "C40219-20110301", "E2501", "2015", "110")]), "2026-11-16")
    assert t[0]["小学校児童数"] == "110" and t[0]["備考"] == "" and t[0]["標準地域コードのURI"] == A
    assert "無いとは確かめていない" in t[1]["備考"]


def test_queries_follow_dated_codes_and_limit_years():
    q = k.pupils_query([A])
    assert "latestCode" in q and "pastCode" in q and k.MIN_YEAR in q and f"<{A}>" in q
    assert "succeedingMunicipality" in k.predecessor_query([N])
