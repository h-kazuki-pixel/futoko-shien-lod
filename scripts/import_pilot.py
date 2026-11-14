"""見本(data/pilot/pilot.csv、12件)を新しい形に入れ直す。1回きりの道具。

検査に通った行は data/seido.csv へ、通らなかった行は理由つきで data/horyu.csv へ。
見本に無かった項目(補助の形、上限額、補助率)は、見本の「金額」「備考」の記載から
人の目で下の表に起こした。推測では足していない。

使い方: python scripts/import_pilot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import schema  # noqa: E402

KIND = {
    "利用料の補助(保護者向け)": "fs-hojo",
    "施設への補助(設置者向け)": "fs-unei",
    "学びの多様化学校": "tayouka",
    "教育支援センター(校外)": "shien-center",
    "出席扱いの施設一覧の公表": "shusseki",
}

GUIDELINE = {
    "未確認(ページに要綱のリンクなし)": "ページにリンクなし",
    "あり(ページにPDFのリンク)": "リンクあり・URL未取得",
    "あり(県のサイトにPDF)": "リンクあり・URL未取得",
    "": "",
}

# 見本の「金額」「備考」から起こした項目
EXTRA = {
    "40219-fs-hojo": {"補助の形": "毎月", "上限額_円": "10000", "補助率": "1/2"},
    "40223-fs-hojo": {"補助の形": "毎月", "上限額_円": "5000"},
    "40203-fs-hojo": {"補助の形": "利用開始時の1回", "上限額_円": "30000"},
    "40621-fs-hojo": {"補助の形": "毎月", "上限額_円": "5000"},
    "40000-fs-unei": {"上限額_円": "2000000", "補助率": "1/2"},
}

# 見本で「開始」に入っていたが、開始の時期ではないもの。備考へ移す
NOT_A_START = {"40223-fs-hojo", "40219-shusseki"}


def convert(old: dict[str, str]) -> dict[str, str]:
    slug = KIND[old["制度の種類"]]
    rid = f"{old['市町村コード']}-{slug}"
    row = {c: "" for c in schema.COLUMNS}
    row.update(
        {
            "id": rid,
            "市町村コード": old["市町村コード"],
            "市町村": old["市町村"],
            "制度の種類": schema.KINDS[slug],
            "状態": old["状態"],
            "制度名": old["制度名"],
            "対象": old["対象"],
            "金額": old["金額"],
            "開始": old["開始"],
            "出典URL": old["出典URL"],
            "出典名": old["出典名"],
            "根拠の箇所": old["根拠の箇所"],
            "要綱の状況": GUIDELINE[old["要綱"]],
            "備考": old["備考"],
            "確認日": old["確認日"],
            "確認方法": "機械の読み取り",
        }
    )
    row.update(EXTRA.get(rid, {}))
    if rid in NOT_A_START:
        row["備考"] = "; ".join(x for x in (row["開始"], row["備考"]) if x)
        row["開始"] = ""
    if row["状態"] == "確認できず":
        row["探した場所"] = row["出典URL"]
        row["出典URL"] = ""
        row["出典名"] = ""
    return row


def main() -> int:
    old_rows = schema.read_csv("data/pilot/pilot.csv")
    ok, hold = [], []
    for old in old_rows:
        row = convert(old)
        problems = schema.check_row(row)
        if problems:
            hold.append({**row, "保留の理由": " / ".join(f"{p.rule}: {p.message}" for p in problems)})
        else:
            ok.append(row)
    schema.write_csv("data/seido.csv", ok)
    schema.write_csv("data/horyu.csv", hold, schema.COLUMNS + ["保留の理由"])
    print(f"見本 {len(old_rows)}件 → 公開データ {len(ok)}件、保留 {len(hold)}件")
    for h in hold:
        print(f"  保留: {h['id']}  {h['保留の理由']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
