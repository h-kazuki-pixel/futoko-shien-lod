import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import saikakunin  # noqa: E402

from futoko_lod import schema  # noqa: E402


def _seido(**kw):
    row = {c: "" for c in schema.COLUMNS}
    row.update(id="40999-shien-center", 市町村="見本市", 制度の種類="教育支援センター(校外)", 状態="あり",
               制度名="見本教室", 出典URL="https://www.city.mihon.lg.jp/a.html")
    row.update(kw)
    return row


def test_ari_dake_ga_ichiran_ni_hairu():
    rows = saikakunin.make([_seido(), _seido(id="40999-online", 状態="確認できず", 制度名="")], [])
    assert {r["id"] for r in rows} == {"40999-shien-center"}
    assert [r["項目"] for r in rows] == ["種類と状態", "制度名"]


def test_atai_ga_onaji_nara_hantei_wo_hikitsugu():
    first = saikakunin.make([_seido(対象="小中学生")], [])
    for r in first:
        r["判定"] = "合っている"
    again = saikakunin.make([_seido(対象="中学生")], first)
    judge = {r["項目"]: r["判定"] for r in again}
    assert judge["制度名"] == "合っている"
    assert judge["対象"] == ""  # 値が変わった項目は、見直しになる
    memo = {r["項目"]: r["メモ"] for r in again}
    assert "直す前の値は、人が「合っている」と判定" in memo["対象"]  # 前の判定は、メモにだけ残す


def test_ayamari_ritsu_no_kazoekata():
    rows = [
        {"id": "a", "項目": "制度名", "判定": "合っている", "メモ": ""},
        {"id": "a", "項目": "対象", "判定": "違う", "メモ": "学年が違う"},
        {"id": "b", "項目": "制度名", "判定": "合っている", "メモ": ""},
        {"id": "b", "項目": "対象", "判定": "分からない", "メモ": ""},
        {"id": "c", "項目": "制度名", "判定": "", "メモ": ""},
    ]
    s = saikakunin.shukei(rows)
    assert s["項目の誤り率"] == pytest.approx(1 / 3)  # 分からない・未記入は分母に入れない
    assert s["制度"] == {"違う": 1, "途中・分からないを含む": 1, "未記入": 1}
    assert s["制度の誤り率"] == 1.0
    assert s["違う"] == [("a", "対象", "学年が違う")]


def test_hantei_ga_nai_toki_wa_ritsu_wo_dasanai():
    assert saikakunin.shukei([{"id": "a", "項目": "制度名", "判定": "", "メモ": ""}])["項目の誤り率"] is None


def test_shiranai_hantei_wa_tomeru():
    with pytest.raises(ValueError):
        saikakunin.shukei([{"id": "a", "項目": "制度名", "判定": "たぶん合う", "メモ": ""}])
