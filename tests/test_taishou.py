from futoko_lod import schema, taishou

# 見本は作りもの。
def row(name, status, code="40999"):
    return {c: "" for c in schema.COLUMNS} | {"id": f"{code}-tayouka", "市町村コード": code, "市町村": name,
                                              "制度の種類": "学びの多様化学校", "状態": status}


def test_plain_form_is_caught_and_absent_town_is_clean():
    r = taishou.check([row("みほん市", "あり"), row("べつの町", "なし")], "設置者一覧 福岡県 みほん市 みほん中学校")
    assert (r[0]["A"], r[0]["見立て"]) == (True, "照合の形で拾える")
    assert (r[1]["B"], r[1]["C"], r[1]["見立て"]) == (False, False, "空振りではない見込み")


def test_gun_form_is_flagged():
    page = "設置者一覧 福岡県みほん郡べつの町 べつの小学校"
    r = taishou.check([row("べつの町", "なし"), row("べつの町", "あり")], page)
    assert (r[0]["A"], r[0]["C"], r[0]["見立て"]) == (False, True, "人が見る")
    assert r[1]["見立て"] == "照合の形では拾えない"


def test_prefecture_row_and_other_kinds_are_skipped():
    other = row("みほん市", "あり") | {"制度の種類": "教育支援センター(校外)"}
    assert taishou.check([row("福岡県", "あり", "40000"), other], "福岡県") == []
