import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import muse  # noqa: E402


def _ichiran():
    return [{"id": i, "項目": k} for i in ("a", "b", "c") for k in ("制度名", "対象")]


def _muse(judges):
    return [{"id": r["id"], "項目": r["項目"], "Muse判定": j} for r, j in zip(_ichiran(), judges)]


def test_ichiran_to_awanai_to_tomeru():
    rows = _muse(["合っている"] * 6)[:-1]
    assert muse.check(rows, _ichiran())
    assert muse.check(_muse(["たぶん"] + ["合っている"] * 5), _ichiran())
    assert muse.check(_muse(["合っている"] * 6), _ichiran()) == []


def test_chigau_to_wakaranai_wa_kanarazu_hito_ga_miru():
    rows = muse.choose(_muse(["違う", "合っている", "分からない", "合っている", "合っている", "合っている"]), 0, 1)
    look = {(r["id"], r["項目"]) for r in rows if r["人が見る"]}
    assert look == {("a", "制度名"), ("b", "制度名")}


def test_nukitori_wa_seido_no_zengyou_de_saigen_dekiru():
    rows = _muse(["合っている"] * 6)
    first = muse.choose(rows, 1, 7)
    again = muse.choose(rows, 1, 7)
    assert first == again  # 種が同じなら同じ制度が選ばれる
    picked = {r["id"] for r in first if r["人が見る"]}
    assert len(picked) == 1
    assert sum(1 for r in first if r["人が見る"]) == 2  # 選んだ制度の全行
