"""市町の問い合わせの窓口(担当課、メールフォーム、メールアドレス)を、公式ページから拾う。

不登校支援のページの「お問い合わせ」欄を見る。拾うのは、公開されている役所の窓口だけ。
robots.txt に従い、1ページごとに間隔をあける。ページの本文は保存しない。結果は実行の記録に出す。
拾った結果は手がかり。送る前に、人がフォームを開いて確かめる。

使い方: python scripts/madoguchi.py   (GitHub Actions の madoguchi で回す)
"""

from __future__ import annotations

import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futoko_lod import fetch  # noqa: E402

# 市町ごとに、問い合わせ欄がありそうな公式ページ(データの出典・探した場所から)
PAGES = {
    "福岡市": "https://www.city.fukuoka.lg.jp/kyoiku-iinkai/kyoikusodan/child/soudan04.html",
    "筑紫野市": "https://www.city.chikushino.fukuoka.jp/soshiki/34/1336.html",
    "春日市": "https://www.city.kasuga.fukuoka.jp/kosodate/eschool/1001730/index.html",
    "大野城市": "https://www.city.onojo.fukuoka.jp/s075/020/010/080/hutoukou.html",
    "宗像市": "https://www.city.munakata.lg.jp/kiji0033002/index.html",
    "太宰府市": "https://www.city.dazaifu.lg.jp/soshiki/28/2085.html",
    "古賀市": "https://www.city.koga.fukuoka.jp/cityhall/work/gakkokyoiku/064.php",
    "福津市": "https://www.city.fukutsu.lg.jp/soshiki/gakko/kyouikushido/14465.html",
    "糸島市": "https://www.city.itoshima.lg.jp/s031/010/010/020/070/ito-kyouikusoudan.html",
    "那珂川市": "https://www.city.nakagawa.lg.jp/site/nobinobi/hutoukou2024.html",
    "宇美町": "https://www.town.umi.lg.jp/soshiki/39/70131.html",
    "篠栗町": "https://www.town.sasaguri.fukuoka.jp/soshiki/gakko_kyoiku/index.html",
    "志免町": "https://www.town.shime.lg.jp/site/kouhou/hikikomori-hutoukou-soudann.html",
    "須恵町": "https://www.town.sue.fukuoka.jp/soshiki/gakkoukyouikuka/syou_tyuugakkou/10565.html",
    "新宮町": "https://www.town.shingu.fukuoka.jp/soshiki/kosodate/4/3_1/7016.html",
    "久山町": "https://www.town.hisayama.fukuoka.jp/gyosei/kosodate_kyoiku/kyoiku_iinkai/index.html",
    "粕屋町": "https://www.town.kasuya.fukuoka.jp/s022/040/010/020/040/20260708111059.html",
}

LINK = re.compile(r"問い?合わ?せ|問合せ|メール|inquiry|mailform|contact|/form|toiawase|otoiawase", re.I)
LINE = re.compile(r"課|係|室|センター|電話|TEL|Tel|ファクス|FAX|メール|E-?mail", re.I)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append(("".join(self._text).strip(), self._href))
            self._href = None


def pick(html: str, base: str) -> dict:
    """ページから、問い合わせの手がかりを拾う。"""
    p = _Links()
    p.feed(html)
    links = []
    for text, href in p.links:
        if href and (href.startswith("mailto:") or LINK.search(text) or LINK.search(href)):
            item = (text[:40], href if href.startswith("mailto:") else urljoin(base, href))
            if item not in links:
                links.append(item)
    text = re.sub(r"\s+", " ", fetch.html_to_text(html))
    near = []
    for m in re.finditer(r"問い?合わ?せ|問合せ", text):
        snippet = text[m.start():m.start() + 160]
        if LINE.search(snippet) and not any(snippet[:30] in x for x in near):
            near.append(snippet)
    return {"links": links[:12], "near": near[-3:]}


def main() -> int:
    for name, url in PAGES.items():
        ok, note = fetch.robots_decision(url)
        print(f"## {name} {url}")
        if not ok:
            print(f"  取得しない: {note}")
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": fetch.USER_AGENT})
            with urllib.request.urlopen(req, timeout=fetch.TIMEOUT_SEC) as res:
                html = fetch.decode(res.read(), res.headers.get("Content-Type", ""))
        except Exception as e:  # 取得できないページは飛ばす
            print(f"  取得できず: {type(e).__name__} {getattr(e, 'code', '')}")
            continue
        got = pick(html, url)
        for line in got["near"]:
            print(f"  欄: {line}")
        for text, href in got["links"]:
            print(f"  リンク: {text} -> {href}")
        time.sleep(fetch.INTERVAL_SEC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
