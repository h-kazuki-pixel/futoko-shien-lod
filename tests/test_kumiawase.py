from futoko_lod import kumiawase as k


def obs(code, area, ind, year, value):
    return {"plain": k.SAC + code, "area": "http://data.e-stat.go.jp/lod/sac/" + area, "ind": k.CODE + ind, "t": year, "v": value}


def test_latest_year_wins():
    got = k.latest_pupils([obs("40219", "C40219-20110301", "E2501", "2014", "100"), obs("40219", "C40219-20110301", "E2501", "2015", "110.0")])
    assert got["40219"]["E2501"] == ("2015", 110, "C40219-20110301")


def test_previous_code_is_used_only_when_the_current_code_has_no_value():
    got = k.latest_pupils([obs("40231", "C40305-19720401", "E2501", "2015", "300")])
    assert got["40231"]["E2501"][2] == "C40305-19720401"
    both = k.latest_pupils([obs("40231", "C40305-19720401", "E2501", "2015", "300"), obs("40231", "C40231-20181001", "E2501", "2014", "290")])
    assert both["40231"]["E2501"] == ("2014", 290, "C40231-20181001")


def test_table_marks_missing_and_changed_codes():
    areas = [{"市町村コード": "40219", "市町村": "大野城市"}, {"市町村コード": "40231", "市町村": "那珂川市"}, {"市町村コード": "40999", "市町村": "見本町"}]
    got = k.latest_pupils([obs("40219", "C40219-20110301", "E2501", "2015", "110"), obs("40231", "C40305-19720401", "E3501", "2015", "50")])
    t = {r["市町村コード"]: r for r in k.table(areas, got, "2026-11-16")}
    assert t["40219"]["小学校児童数"] == "110" and t["40219"]["中学校生徒数"] == "" and t["40219"]["備考"] == ""
    assert "コードが替わる前" in t["40231"]["備考"]
    assert t["40999"]["備考"] == "統計LOD に値が無い"


def test_query_follows_dated_codes_and_limits_years():
    q = k.pupils_query(["40219"])
    assert "latestCode" in q and "pastCode" in q and "previousCode" in q and k.MIN_YEAR in q
