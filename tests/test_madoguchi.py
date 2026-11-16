import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import madoguchi  # noqa: E402

HTML = """<html><body><p>本文</p><a href="/about.html">この市について</a>
<div><h2>このページに関するお問い合わせ</h2><p>見本課 見本係</p><p>電話: 000-000-0000</p>
<a href="/form/detail.php?sec=34">メールでのお問い合わせはこちら</a>
<a href="mailto:mihon@city.mihon.lg.jp">mihon@city.mihon.lg.jp</a></div></body></html>"""


def test_toiawase_no_link_to_ran_wo_hirou():
    got = madoguchi.pick(HTML, "https://www.city.mihon.lg.jp/a/b.html")
    hrefs = [h for _, h in got["links"]]
    assert "https://www.city.mihon.lg.jp/form/detail.php?sec=34" in hrefs  # 相対のリンクは、ページの場所から組み立てる
    assert "mailto:mihon@city.mihon.lg.jp" in hrefs
    assert "https://www.city.mihon.lg.jp/about.html" not in hrefs
    assert any("見本課" in x for x in got["near"])


def test_pages_wa_17_shichou_de_koushiki_dake():
    from futoko_lod import schema
    assert len(madoguchi.PAGES) == 17
    assert all(schema.is_official_url(u) for u in madoguchi.PAGES.values())
