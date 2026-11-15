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
        ("要確認", "照合の結果が変わった", "40999-fs-hojo", "一致", "不一致")]


def test_page_gone_is_heavy_and_coming_back_is_light():
    gone = {k: v for k, v in ALL.items() if k != "https://example.lg.jp/a"}
    d = t.diff(run(ALL), run(gone), "2026-11-23")
    assert [(c["重さ"], c["変わった所"]) for c in d] == [("要確認", "取得できなくなった")]
    back = t.diff(run(gone), run(ALL), "2026-11-30")
    assert [(c["重さ"], c["変わった所"]) for c in back] == [("記録のみ", "取得できるようになった")]


def test_text_change_with_same_collation_is_light():
    changed = ALL | {"https://example.lg.jp/a": PAGE_OK + "申請の期限を延ばしました。"}
    d = t.diff(run(ALL), run(changed), "2026-11-23")
    assert [(c["重さ"], c["変わった所"]) for c in d] == [("記録のみ", "ページの文字が変わった(照合は一致のまま)")]


def test_searched_place_change_is_recorded_once_per_page():
    other = KAKUNIN | {"id": "40999-shusseki"}
    changed = ALL | {"https://example.lg.jp/b": "相談の窓口。新しい事業を始めます"}
    d = t.diff(run(ALL, rows=[KAKUNIN, other]), run(changed, rows=[KAKUNIN, other]), "2026-11-23")
    assert len(d) == 1
    assert d[0]["変わった所"] == "探した場所のページの文字が変わった" and d[0]["重さ"] == "記録のみ"
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
