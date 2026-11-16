from futoko_lod import schema, torinaoshi as t

# 見本は作りもの。公式ページの文章は写していない。
ARI = {c: "" for c in schema.COLUMNS} | {
    "id": "40999-fs-hojo", "状態": "あり", "金額": "月額の2分の1、上限10,000円", "上限額_円": "10000",
    "出典URL": "https://example.lg.jp/a", "根拠の箇所": "10,000円を上限",
}
KAKUNIN = {c: "" for c in schema.COLUMNS} | {
    "id": "40999-online", "状態": "確認できず",
    "探した場所": "https://example.lg.jp/b | https://example.lg.jp/c",
}
PAGE_OK = "補助します。2分の1、10,000円を上限とします。"


def fetcher(pages: dict, calls: list | None = None):
    def f(url: str) -> dict:
        if calls is not None:
            calls.append(url)
        text = pages.get(url)
        return {"url": url, "取得日時": "2026-11-16T00:00:00+00:00",
                "結果": "取得" if text is not None else "取得できず(HTTP 404)", "text": text}
    return f


def run(pages: dict, rows=(ARI, KAKUNIN), calls=None):
    return t.collect(list(rows), fetcher(pages, calls), interval=0, retry_wait=0)


ALL = {"https://example.lg.jp/a": PAGE_OK, "https://example.lg.jp/b": "相談の窓口", "https://example.lg.jp/c": "お知らせ"}


def test_targets_are_source_and_every_searched_place():
    assert [(r["id"], role, url) for r, role, url in t.targets([ARI, KAKUNIN])] == [
        ("40999-fs-hojo", "出典", "https://example.lg.jp/a"),
        ("40999-online", "探した場所", "https://example.lg.jp/b"),
        ("40999-online", "探した場所", "https://example.lg.jp/c"),
    ]


def test_source_is_collated_and_searched_place_is_only_marked():
    cur = run(ALL)
    assert [c["判定"] for c in cur] == ["一致", "", ""]
    assert all(len(c["本文の印"]) == 16 for c in cur)


def test_no_page_text_is_kept():
    for c in run(ALL):
        assert PAGE_OK not in "".join(c.values()) and set(c) == set(t.SAISHIN_COLUMNS)


def test_mark_ignores_spacing_and_width():
    assert t.text_mark("上限 10,000円") == t.text_mark("上限１０，０００円")
    assert t.text_mark("上限10,000円") != t.text_mark("上限20,000円")


def test_nothing_changed_gives_no_diff():
    assert t.diff(run(ALL), run(ALL), "2026-11-23") == []


def test_first_run_and_new_rows_are_not_changes():
    assert t.diff([], run(ALL), "2026-11-23") == []
    assert t.diff(run(ALL, rows=[ARI]), run(ALL), "2026-11-23") == []


def test_amount_changed_on_the_page_is_heavy():
    changed = ALL | {"https://example.lg.jp/a": "補助します。2分の1、20,000円を上限とします。"}
    d = t.diff(run(ALL), run(changed), "2026-11-23")
    assert [(c["重さ"], c["変わった所"], c["id"], c["前"], c["後"]) for c in d] == [
        ("要確認", "照合の結果が変わった", "40999-fs-hojo", "一致", "不一致(合わない: 根拠の箇所 | 10000円)")]


def test_page_gone_is_heavy_and_coming_back_is_light():
    gone = {k: v for k, v in ALL.items() if k != "https://example.lg.jp/a"}
    d = t.diff(run(ALL), run(gone), "2026-11-23")
    assert [(c["重さ"], c["変わった所"]) for c in d] == [("要確認", "取得できなくなった")]
    back = t.diff(run(gone), run(ALL), "2026-11-30")
    assert [(c["重さ"], c["変わった所"]) for c in back] == [("記録のみ", "取得できるようになった")]


def test_text_change_with_same_collation_is_light():
    changed = ALL | {"https://example.lg.jp/a": PAGE_OK + "申請の期限を延ばしました。"}
    d = t.diff(run(ALL), run(changed), "2026-11-23")
    assert [(c["重さ"], c["変わった所"]) for c in d] == [
        ("記録のみ", "ページの文字が変わった(照合に使う語句と数字は、すべてまだある)")]


def test_searched_place_change_is_recorded_once_per_page():
    other = KAKUNIN | {"id": "40999-shusseki"}
    changed = ALL | {"https://example.lg.jp/b": "相談の窓口。新しい事業を始めます"}
    d = t.diff(run(ALL, rows=[KAKUNIN, other]), run(changed, rows=[KAKUNIN, other]), "2026-11-23")
    assert len(d) == 1
    assert d[0]["変わった所"] == "探した場所のページの文字が変わった(種類の語の数は同じ)" and d[0]["重さ"] == "記録のみ"
    assert d[0]["id"] == "40999-online 40999-shusseki"


def test_failed_fetch_is_retried_once_and_each_page_fetched_once():
    calls: list[str] = []
    run({k: v for k, v in ALL.items() if k != "https://example.lg.jp/c"}, rows=[KAKUNIN, KAKUNIN | {"id": "x"}], calls=calls)
    assert calls == ["https://example.lg.jp/b", "https://example.lg.jp/c", "https://example.lg.jp/c"]


def test_robots_refusal_is_not_retried():
    calls: list[str] = []

    def f(url):
        calls.append(url)
        return {"url": url, "取得日時": "", "結果": "robots.txt により取得しない", "text": None}

    cur = t.collect([ARI], f, interval=0, retry_wait=0)
    assert calls == ["https://example.lg.jp/a"] and cur[0]["判定"] == ""


def test_issue_is_written_only_for_heavy_changes():
    changed = ALL | {"https://example.lg.jp/b": "相談の窓口が変わりました"}
    assert t.issue_markdown(t.diff(run(ALL), run(changed), "2026-11-23"), "2026-11-23") == ""
    gone = {k: v for k, v in ALL.items() if k != "https://example.lg.jp/a"}
    text = t.issue_markdown(t.diff(run(ALL), run(gone), "2026-11-23"), "2026-11-23")
    assert "40999-fs-hojo" in text and "公開データは書き換えていない" in text


def test_records_round_trip(tmp_path):
    cur = run(ALL)
    t.write(tmp_path / "d" / "saishin.csv", cur, t.SAISHIN_COLUMNS)
    assert t.read(tmp_path / "d" / "saishin.csv") == cur
    assert t.read(tmp_path / "none.csv") == []


def test_summary_counts_pages_once():
    md = t.summary_markdown(run(ALL), [], first_run=True, date="2026-11-16")
    assert "| 取りに行ったページ | 3 |" in md and "初回" in md


def test_second_source_is_fetched_and_collated_separately():
    # 第2の出典(弱い所18)。見本は作りもの
    row = ARI | {"出典URL_2": "https://example.lg.jp/d", "根拠の箇所_2": "案内の語句", "出典2の項目": "備考", "備考": "補足"}
    pages = ALL | {"https://example.lg.jp/d": "案内の語句があります"}
    cur = run(pages, rows=(row,))
    roles = {c["役割"]: c["判定"] for c in cur}
    assert roles == {"出典": "一致", "出典2": "一致"}
    cur = run(ALL | {"https://example.lg.jp/d": "別のページ"}, rows=(row,))
    assert {c["役割"]: c["判定"] for c in cur}["出典2"] == "不一致"


# ---------- 何が変わったか(弱い所 取2) ----------

def test_each_collation_item_is_recorded_without_page_text():
    c = run(ALL)[0]
    assert t.split_list(c["照合で見たもの"]) == ["根拠の箇所", "1/2", "10000円"]
    assert c["合わなかったもの"] == "" and c["種類の語の数"] == ""
    # 見たものは、データの側の語句・数字の名前だけ。ページの文は入らない
    assert "補助します" not in "".join(run(ALL)[0].values())


def test_missing_items_change_while_still_mismatched_is_recorded():
    one = ALL | {"https://example.lg.jp/a": "補助します。10,000円を上限とします。"}       # 1/2 が消えた
    two = ALL | {"https://example.lg.jp/a": "補助します。2分の1、上限は別に定めます。"}  # 1/2 は戻り、根拠と金額が消えた
    first, second = run(one), run(two)
    assert first[0]["合わなかったもの"] == "1/2"
    d = t.diff(first, second, "2026-11-30")
    assert [(c["重さ"], c["変わった所"], c["前"], c["後"]) for c in d] == [
        ("記録のみ", "合わない語句・数字が変わった(照合は不一致のまま)", "1/2", "根拠の箇所 | 10000円")]


def test_coming_back_to_match_says_what_was_missing():
    bad = ALL | {"https://example.lg.jp/a": "補助します。10,000円を上限とします。"}
    d = t.diff(run(bad), run(ALL), "2026-11-30")
    assert [(c["重さ"], c["前"], c["後"]) for c in d] == [("記録のみ", "不一致(合わない: 1/2)", "一致")]


def test_kind_word_appearing_on_a_searched_place_is_heavy_only_for_its_own_kind():
    # KAKUNIN は online(確認できず)。探した場所 b に「オンライン」が新しく出た
    changed = ALL | {"https://example.lg.jp/b": "相談の窓口。オンラインの学習支援を始めます"}
    d = t.diff(run(ALL), run(changed), "2026-11-30", {"40999-online": "確認できず"})
    assert [(c["重さ"], c["変わった所"], c["前"], c["後"]) for c in d] == [
        ("要確認", "探した場所に、その行の種類の語が新しく出た", "オンライン:0", "オンライン:1")]
    # 「あり」の行の探した場所なら、記録のみ
    d = t.diff(run(ALL), run(changed), "2026-11-30", {"40999-online": "あり"})
    assert [c["重さ"] for c in d] == ["記録のみ"]
    # ほかの種類の語なら、記録のみ
    other = ALL | {"https://example.lg.jp/b": "相談の窓口。出席扱いの案内"}
    d = t.diff(run(ALL), run(other), "2026-11-30", {"40999-online": "確認できず"})
    assert [(c["重さ"], c["変わった所"]) for c in d] == [("記録のみ", "探した場所のページで、種類の語の数が変わった")]
    assert "要確認が 1 件" in t.issue_markdown(t.diff(run(ALL), run(changed), "2026-11-30"), "2026-11-30")


def test_absence_rows_record_what_was_checked():
    nashi = {c: "" for c in schema.COLUMNS} | {
        "id": "40999-tayouka", "市町村": "見本町", "状態": "なし", "出典URL": "https://example.lg.jp/l", "根拠の箇所": "設置者の一覧"}
    ok = {"https://example.lg.jp/l": "設置者の一覧。福岡県見本市 見本市立A中学校"}
    cur = run(ok, rows=(nashi,))
    assert cur[0]["判定"] == "一致" and cur[0]["合わなかったもの"] == ""
    assert t.split_list(cur[0]["照合で見たもの"]) == list(t.ABSENCE_ITEMS)
    listed = {"https://example.lg.jp/l": "設置者の一覧。福岡県見本町 見本町立B中学校"}
    d = t.diff(cur, run(listed, rows=(nashi,)), "2026-11-30")
    assert d[0]["重さ"] == "要確認"
    assert d[0]["後"] == "不一致(合わない: 一覧に市町村が管理する学校の印が無い | 一覧に県名+市町村名が無い)"


def test_old_records_without_the_new_columns_give_no_false_changes():
    old = [{k: v for k, v in c.items() if k in ("id", "役割", "URL", "取得日時", "取得", "判定", "本文の印")} for c in run(ALL)]
    assert t.diff(old, run(ALL), "2026-11-23") == []


def test_summary_counts_collation_items():
    md = t.summary_markdown(run(ALL), [], first_run=True, date="2026-11-16")
    assert "| 照合に使った語句と数字 | 3 |" in md and "ページに無かった 0" in md


def test_place_change_after_old_records_does_not_claim_word_counts_were_compared():
    old = [{k: v for k, v in c.items() if k != "種類の語の数"} for c in run(ALL)]
    changed = ALL | {"https://example.lg.jp/b": "相談の窓口。時間を変えました"}
    d = t.diff(old, run(changed), "2026-11-23")
    assert [c["変わった所"] for c in d] == ["探した場所のページの文字が変わった"]
