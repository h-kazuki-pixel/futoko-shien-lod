import pytest

from futoko_lod import collate, fetch, schema
from futoko_lod.collate import tokens

# 架空のページ。公式ページの文章は試験にも写さない。
PAGE = """
<html><head><style>.a{color:red}</style><script>var x = "9,999円";</script></head>
<body><h1>みほん市 補助金のご案内</h1>
<p>補助額は、月額の利用料の２分の１で、月額５，０００円を上限とします。</p>
<p>令和７年４月１日以降の利用分が対象です。前１年間におおむね３０日以上登校していないこと。</p>
</body></html>
"""


def row(**over):
    r = {c: "" for c in schema.COLUMNS}
    r.update(
        {
            "id": "40999-fs-hojo",
            "金額": "月額の利用料の2分の1、上限5,000円",
            "上限額_円": "5000",
            "補助率": "1/2",
            "開始": "令和7年4月1日以降",
            "対象": "前1年におおむね30日以上登校していない",
            "根拠の箇所": "月額5,000円を上限",
        }
    )
    r.update(over)
    return r


@pytest.mark.parametrize(
    "a,b",
    [
        ("10,000円", "１０，０００円"),
        ("1万円", "10,000円"),
        ("3万円", "30000円"),
        ("1万5千円", "15,000円"),
        ("1.5万円", "15000円"),
        ("5千円", "5,000円"),
        ("2分の1", "１/２"),
        ("二分の一", "1/2"),
        ("１／２", "2分の1"),
        ("令和7年度", "2025年度"),
        ("令和元年", "2019年"),
        ("平成28年", "2016年"),
        ("令和7年4月1日", "2025年4月1日"),
        ("3か月", "３ヶ月"),
    ],
)
def test_same_meaning_same_tokens(a, b):
    assert tokens(a) == tokens(b) != set()


@pytest.mark.parametrize(
    "a,b",
    [
        ("5,000円", "50,000円"),
        ("3万円", "3千円"),
        ("2分の1", "3分の1"),
        ("令和7年度", "令和8年度"),
        ("30日", "30回"),
        ("8月", "9月"),
    ],
)
def test_different_meaning_different_tokens(a, b):
    assert tokens(a) != tokens(b)


def test_month_amount_is_not_a_month():
    # 「月額」の「月」を、何月の「月」と取り違えない
    assert not any(t.startswith("month:") for t in tokens("3月額"))
    assert tokens("月額5,000円") == {"yen:5000"}


def test_collate_matches():
    text = fetch.html_to_text(PAGE)
    result = collate.collate(row(), text)
    assert result["一致"], result


def test_script_text_is_not_page_text():
    text = fetch.html_to_text(PAGE)
    assert "9,999" not in text


def test_wrong_amount_is_caught():
    text = fetch.html_to_text(PAGE)
    result = collate.collate(row(上限額_円="10000", 金額="上限10,000円"), text)
    assert not result["一致"]
    assert "yen:10000" in result["ページに無い数字"]


def test_wrong_year_is_caught():
    text = fetch.html_to_text(PAGE)
    result = collate.collate(row(開始="令和8年4月1日以降"), text)
    assert "year:2026" in result["ページに無い数字"]


def test_basis_phrase_must_be_on_page():
    text = fetch.html_to_text(PAGE)
    result = collate.collate(row(根拠の箇所="月額8,000円を上限"), text)
    assert not result["根拠の箇所がページにある"]
    assert not result["一致"]


def test_empty_basis_never_matches():
    text = fetch.html_to_text(PAGE)
    assert not collate.collate(row(根拠の箇所=""), text)["一致"]


def test_decode_shift_jis():
    body = "<meta charset=\"Shift_JIS\"><p>上限5,000円</p>".encode("cp932")
    assert "上限5,000円" in fetch.decode(body, "text/html")


def test_robots_unreachable_means_do_not_fetch(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(fetch.urllib.request, "urlopen", boom)
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    fetch._robots.clear()
    ok, note = fetch.robots_decision("https://www.city.mihon.lg.jp/a.html")
    assert not ok and "確かめられず" in note
    fetch._robots.clear()


def test_name_parts_are_reported_but_do_not_decide():
    text = fetch.html_to_text(PAGE)
    r = collate.collate(row(制度名="みほん市 補助金(まぼろし教室)"), text)
    assert r["ページに無い名前の部分"] == ["まぼろし教室"]
    assert r["一致"]


LIST_PAGE = "<h1>みほん学校の設置者一覧</h1><table><tr><td>1</td><td>みほん市立あおぞら中学校</td><td>福岡県みほん市</td></tr></table>"


def test_absence_matches_when_name_is_not_listed():
    text = fetch.html_to_text(LIST_PAGE)
    r = collate.collate_absence(row(市町村="べつの町", 根拠の箇所="設置者一覧"), text)
    assert r["一致"]


def test_absence_fails_when_name_is_listed():
    text = fetch.html_to_text(LIST_PAGE)
    r = collate.collate_absence(row(市町村="みほん市", 根拠の箇所="設置者一覧"), text)
    assert not r["一致"]


def test_absence_fails_on_wrong_page():
    r = collate.collate_absence(row(市町村="べつの町", 根拠の箇所="設置者一覧"), "お探しのページは見つかりません")
    assert not r["一致"]


LIST_PAGE2 = (
    "<h1>みほん学校の設置者一覧</h1><table>"
    "<tr><td>1</td><td>みほん市立あおぞら中学校</td><td>みほん市教育委員会</td><td>福岡県べつの市</td></tr>"
    "<tr><td>2</td><td>福岡県立となり高等学校</td><td>福岡県教育委員会</td><td>福岡県となり市</td></tr>"
    "</table>"
)


def test_absence_fails_on_own_school_even_without_place():
    # 設置場所が別の市でも、学校名や管理機関に市町村名があれば「なし」にしない
    text = fetch.html_to_text(LIST_PAGE2)
    r = collate.collate_absence(row(市町村="みほん市", 根拠の箇所="設置者一覧"), text)
    assert not r["一致"]
    assert "一覧に市町村が管理する学校の印がある" in r["ページに無い数字"]


def test_absence_with_prefectural_school_named_in_basis():
    # 設置場所に名前が出ても、根拠の箇所に挙げた県立の学校の1回分だけなら通す
    text = fetch.html_to_text(LIST_PAGE2)
    assert not collate.collate_absence(row(市町村="となり市", 根拠の箇所="設置者一覧"), text)["一致"]
    assert collate.collate_absence(row(市町村="となり市", 根拠の箇所="福岡県立となり高等学校"), text)["一致"]


def test_absence_prefectural_basis_allows_only_one_place():
    text = fetch.html_to_text(LIST_PAGE2 + "<p>福岡県となり市</p>")
    assert not collate.collate_absence(row(市町村="となり市", 根拠の箇所="福岡県立となり高等学校"), text)["一致"]


def test_absence_basis_without_prefectural_school_allows_none():
    text = fetch.html_to_text(LIST_PAGE2)
    assert not collate.collate_absence(row(市町村="となり市", 根拠の箇所="福岡県教育委員会"), text)["一致"]


# ---- 第2の出典(弱い所18)。見本は作りもの ----

def test_collate_splits_fields_by_source():
    r = row(状態="あり", 根拠の箇所="みほん教室を開いています", 対象="小学5年生から", 開始="令和7年度", 金額="", 上限額_円="", 補助率="",
            出典URL_2="https://x.lg.jp/b.pdf", 根拠の箇所_2="みほん教室の案内", 出典2の項目="対象")
    page1 = "みほん教室を開いています。令和7年度から。"
    page2 = "みほん教室の案内 小学5年生から中学生まで"
    # 出典では「対象」の数字を見ない。第2の出典では「開始」の数字を見ない
    assert collate.collate(r, page1)["一致"]
    assert collate.collate(r, page2, part=2)["一致"]
    # 入れ替えると合わない
    assert not collate.collate(r, page2)["一致"]
    assert not collate.collate(r, page1, part=2)["一致"]


def test_collate_part2_needs_basis2():
    r = row(状態="あり", 根拠の箇所="a", 金額="", 上限額_円="", 補助率="", 出典URL_2="https://x.lg.jp/b.pdf", 根拠の箇所_2="みほん教室の案内", 出典2の項目="備考")
    assert not collate.collate(r, "別の資料", part=2)["一致"]


def test_fetch_run_needs_both_sources(tmp_path, monkeypatch):
    import csv
    r = {c: "" for c in schema.COLUMNS} | {
        "id": "40999-shien-center", "市町村コード": "40999", "市町村": "みほん市", "制度の種類": schema.KINDS["shien-center"],
        "状態": "あり", "制度名": "みほん教室", "出典URL": "https://www.city.mihon.lg.jp/a.html", "根拠の箇所": "みほん教室",
        "出典URL_2": "https://www.city.mihon.lg.jp/b.pdf", "出典名_2": "案内", "根拠の箇所_2": "通う教室",
        "出典2の項目": "制度名", "確認日": "2026-11-16", "確認方法": "機械の読み取り"}
    p = tmp_path / "s.csv"
    schema.write_csv(p, [r])
    pages = {"https://www.city.mihon.lg.jp/a.html": "みほん教室", "https://www.city.mihon.lg.jp/b.pdf": "通う教室です"}
    monkeypatch.setattr(fetch, "fetch", lambda u: {"url": u, "結果": "取得" if u in pages else "取得できず(HTTP 404)", "text": pages.get(u)})
    out = fetch.run(str(p), interval=0)
    assert out[0]["判定"] == "一致" and out[0]["出典2"]["一致"]
    pages["https://www.city.mihon.lg.jp/b.pdf"] = "別の資料"
    assert fetch.run(str(p), interval=0)[0]["判定"] == "不一致"
    del pages["https://www.city.mihon.lg.jp/b.pdf"]
    assert fetch.run(str(p), interval=0)[0]["判定"] == "取得できず"
    assert "(出典2)" in fetch.summary_markdown(fetch.run(str(p), interval=0))


def test_blocked_second_source_checked_by_human(tmp_path, monkeypatch):
    # 第2の出典が robots.txt で取得しない資料で、人が確かめた行は、出典の照合で判定する
    r = {c: "" for c in schema.COLUMNS} | {
        "id": "40999-shien-center", "市町村コード": "40999", "市町村": "みほん町", "制度の種類": schema.KINDS["shien-center"],
        "状態": "あり", "制度名": "みほん教室", "出典URL": "https://www.town.mihon.lg.jp/a.html", "根拠の箇所": "みほん教室",
        "出典URL_2": "https://www.town.mihon.lg.jp/b.pdf", "出典名_2": "案内", "根拠の箇所_2": "みほん教室",
        "出典2の項目": "備考", "備考": "補足", "確認日": "2026-11-16", "確認方法": "人の再確認"}
    p = tmp_path / "s.csv"
    schema.write_csv(p, [r])

    def fake(u):
        if u.endswith(".pdf"):
            return {"url": u, "結果": "robots.txt により取得しない", "text": None}
        return {"url": u, "結果": "取得", "text": "みほん教室"}
    monkeypatch.setattr(fetch, "fetch", fake)
    out = fetch.run(str(p), interval=0)[0]
    assert out["判定"] == "一致" and out["出典2"]["人が確かめた"]
    assert "人が確かめた" in fetch.summary_markdown([out])
    # 機械の読み取りの行なら、取得できずのまま
    schema.write_csv(p, [r | {"確認方法": "機械の読み取り"}])
    assert fetch.run(str(p), interval=0)[0]["判定"] == "取得できず"


def test_note_numbers_are_reported_not_judged():
    # 弱い所5: 備考の数字は、どのページにも無ければ挙げる。合否には使わない
    r = row(備考="定員は各学年10名程度。指定年は令和8年")
    assert collate.note_tokens_missing(r, "定員は10名") == ["year:2026"]
    assert collate.note_tokens_missing(r, "定員は10名", "令和8年に指定") == []
