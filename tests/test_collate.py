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
