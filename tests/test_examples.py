"""使い方の例(examples/tsukaikata.py)が、いまの公開物の形で動くことを確かめる。"""

import importlib.util
from pathlib import Path

import pytest

from futoko_lod import publish, schema


@pytest.fixture(scope="module")
def graph(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    publish.write_site(out)
    spec = importlib.util.spec_from_file_location("tsukaikata", Path("examples/tsukaikata.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.load(str(out))


def test_kazu_matches_csv(graph):
    mod, g = graph
    rows = schema.read_csv("data/seido.csv")
    want = {}
    for r in rows:
        want[r["状態"]] = want.get(r["状態"], 0) + 1
    assert mod.kazu(g) == want


def test_shichoson_has_five_kinds_in_metro(graph):
    mod, g = graph
    got = mod.shichoson(g, "大野城市")
    assert len(got) == 5
    assert {s for _, s, *_ in got} <= {"あり", "予定", "なし", "確認できず"}


def test_kakunin_dekizu_rows_have_places(graph):
    mod, g = graph
    rows = schema.read_csv("data/seido.csv")
    n = sum(r["状態"] == "確認できず" for r in rows)
    got = mod.kakunin_dekizu(g)
    assert len(got) == n
    assert all(p >= 1 for *_, p in got)
