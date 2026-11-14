import pytest

from futoko_lod import schema


def base(**over):
    """検査に通る「あり」の行(架空の市)。"""
    row = {c: "" for c in schema.COLUMNS}
    row.update(
        {
            "id": "40999-fs-hojo",
            "市町村コード": "40999",
            "市町村": "みほん市",
            "制度の種類": schema.KINDS["fs-hojo"],
            "補助の形": "毎月",
            "状態": "あり",
            "制度名": "みほん補助金",
            "対象": "市内在住の保護者",
            "金額": "月額上限5,000円",
            "上限額_円": "5000",
            "出典URL": "https://www.city.mihon.lg.jp/a.html",
            "出典名": "みほん市公式ページ",
            "根拠の箇所": "月額5,000円",
            "確認日": "2026-11-14",
            "確認方法": "機械の読み取り",
        }
    )
    row.update(over)
    return row


def rules(row):
    return {p.rule for p in schema.check_row(row)}


def test_base_row_passes():
    assert schema.check_row(base()) == []


# --- 「あり」「予定」は、出典・根拠の箇所・確認日がそろわないと保存できない ---


@pytest.mark.parametrize("status", ["あり", "予定"])
@pytest.mark.parametrize("key", ["出典URL", "根拠の箇所", "確認日"])
def test_ari_requires_source_basis_date(status, key):
    assert schema.check_row(base(**{"状態": status, key: ""})) != []


def test_load_fails_when_any_row_is_bad(tmp_path):
    p = tmp_path / "seido.csv"
    schema.write_csv(p, [base(), base(id="40999-fs-hojo-2", 根拠の箇所="")])
    with pytest.raises(schema.DataError) as e:
        schema.load(p)
    assert any(pr.rule == "出典の必須" for pr in e.value.problems)


def test_load_passes_good_file(tmp_path):
    p = tmp_path / "seido.csv"
    schema.write_csv(p, [base()])
    assert len(schema.load(p)) == 1


# --- 「なし」と「確認できず」を混ぜない ---


def kakunin_dekizu(**over):
    return base(
        **{
            "状態": "確認できず",
            "補助の形": "",
            "制度名": "",
            "金額": "",
            "上限額_円": "",
            "出典URL": "",
            "出典名": "",
            "根拠の箇所": "",
            "探した場所": "https://www.city.mihon.lg.jp/kyoiku/",
            **over,
        }
    )


def test_kakunin_dekizu_passes_with_searched_place():
    assert schema.check_row(kakunin_dekizu()) == []


def test_kakunin_dekizu_needs_searched_place():
    assert "探した場所" in rules(kakunin_dekizu(探した場所=""))


def test_kakunin_dekizu_cannot_carry_content():
    assert "確認できず" in rules(kakunin_dekizu(金額="月額5,000円"))


def test_nashi_needs_basis():
    row = kakunin_dekizu(状態="なし", 探した場所="")
    assert "なしの根拠" in rules(row)


def test_nashi_by_machine_needs_official_document():
    row = kakunin_dekizu(状態="なし", 探した場所="", なしの根拠="ページに記載なし")
    assert "なしの根拠" in rules(row)


def test_nashi_by_inquiry_passes():
    row = kakunin_dekizu(
        状態="なし", 探した場所="", なしの根拠="2026-12-01 教育委員会 学校教育課に電話で確認", 確認方法="問い合わせ"
    )
    assert schema.check_row(row) == []


def test_unknown_status_rejected():
    assert "状態" in rules(base(状態="不明"))


# --- 種類の取り違えを防ぐ ---


def test_hojo_needs_payment_form():
    assert "補助の形" in rules(base(補助の形=""))


def test_setter_subsidy_only_for_prefecture():
    row = base(id="40999-fs-unei", 制度の種類=schema.KINDS["fs-unei"])
    assert "制度の種類" in rules(row)


def test_id_must_match_code_and_kind():
    assert "id" in rules(base(id="40998-fs-hojo"))
    assert "id" in rules(base(id="40999-tayouka"))
    assert schema.check_row(base(id="40999-fs-hojo-2")) == []


def test_duplicate_id():
    assert any(p.message == "同じ id が2回ある" for p in schema.check_rows([base(), base()]))


# --- 出典は公式サイトだけ ---


@pytest.mark.parametrize(
    "url",
    [
        "https://www.city.fukuoka.lg.jp/a.html",
        "https://www.pref.fukuoka.lg.jp/contents/x.html",
        "https://www.city.onojo.fukuoka.jp/s075/x.html",
        "https://city.onojo.fukuoka.jp/s075/x.html",
        "https://www.town.kanda.lg.jp/page/1.html",
        "https://www.mext.go.jp/a.htm",
    ],
)
def test_official_urls(url):
    assert schema.is_official_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://note.com/someone/n/abc",
        "https://example.com/city.fukuoka.lg.jp",
        "https://city.fukuoka.lg.jp.example.com/",
        "https://fukuoka.jp/",
        "ftp://www.city.fukuoka.lg.jp/a",
        "",
    ],
)
def test_unofficial_urls(url):
    assert not schema.is_official_url(url)


def test_unofficial_source_rejected():
    assert "公式サイト" in rules(base(出典URL="https://note.com/x/n/y"))


def test_extra_domain_allowlist():
    extra = frozenset({"mihon-kyoiku.ed.jp"})
    row = base(出典URL="https://www.mihon-kyoiku.ed.jp/a.html")
    assert "公式サイト" in rules(row)
    assert schema.check_row(row, extra) == []


# --- 項目の形 ---


def test_basis_must_be_short():
    assert "根拠の箇所" in rules(base(根拠の箇所="あ" * 41))


def test_amount_and_rate_format():
    assert "上限額_円" in rules(base(上限額_円="5,000"))
    assert "補助率" in rules(base(補助率="2分の1"))


def test_date_format():
    assert "確認日" in rules(base(確認日="2026/11/14"))
    assert "確認日" in rules(base(確認日="2026-02-30"))


def test_guideline_state_and_url_go_together():
    assert "要綱の状況" in rules(base(要綱の状況="取得済み"))
    assert "要綱の状況" in rules(base(要綱URL="https://www.city.mihon.lg.jp/y.pdf"))
    assert schema.check_row(base(要綱の状況="取得済み", 要綱URL="https://www.city.mihon.lg.jp/y.pdf")) == []


# --- 公開データそのもの ---


def test_public_data_loads():
    rows = schema.load("data/seido.csv")
    assert len(rows) >= 1


# --- 上限額の数字は、根拠の箇所の中に無ければならない ---


def test_max_amount_must_appear_in_basis():
    assert "上限額_円" in rules(base(根拠の箇所="補助額の上限"))
    assert "上限額_円" in rules(base(上限額_円="10000"))
    assert schema.check_row(base(上限額_円="30000", 金額="3万円まで", 根拠の箇所="3万円を上限")) == []


# --- 市町村の台帳 ---


def test_area_master_code_and_name():
    areas = {"40999": "みほん市"}
    assert schema.check_rows([base()], areas=areas) == []
    assert any(p.rule == "市町村の台帳" for p in schema.check_rows([base()], areas={"40998": "べつの市"}))
    assert any(p.rule == "市町村の台帳" for p in schema.check_rows([base(市町村="みほん町")], areas=areas))


def test_candidates_load():
    schema.load("data/kouho.csv")
