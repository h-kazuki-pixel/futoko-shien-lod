"""公開の形を作る。data/seido.csv から、GitHub Pages に置く一式を書き出す。

書き出すもの(置き場所は docs/公開の形.md にまとめてある):
  index.html            市町×種類の表、種類ごとの件数、ファイルへのリンク
  ichiran/index.html    全件の一覧
  id/{id}/index.html    1件ごとのページ(JSON-LD を埋め込む)
  id/{id}.ttl, .jsonld  1件ごとのデータ
  seido.csv, seido.jsonld, seido.ttl   全件
  ns.html, ns.ttl       語彙(fsl:)の説明
  dataset.ttl           データセットの説明(DCAT)

中身は build.py が作る JSON-LD の節(to_node)だけを元にする。ここで項目を足したり直したりしない。
Turtle は、その節を CONTEXT に従って書き直したもの。同じトリプルになることはテストで確かめる。
ページに載せるのは項目だけ。公式ページの文章は載せない。

使い方: python -m futoko_lod.publish            (_site/ に書き出す)
        python -m futoko_lod.publish --out DIR
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import re
import shutil
from pathlib import Path

from . import build, schema

BASE = build.BASE
NS = BASE + "ns#"
DATASET = BASE + "#dataset"
REPO = "https://github.com/h-kazuki-pixel/futoko-shien-lod"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
AUTHOR = "https://github.com/h-kazuki-pixel"
ISSUED = "2026-11-15"  # はじめて公開した日
TITLE = "不登校支援制度LOD"
LAW = "義務教育の段階における普通教育に相当する教育の機会の確保等に関する法律"

PREFIXES = {
    "schema": "https://schema.org/",
    "dct": "http://purl.org/dc/terms/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "fsl": NS,
}

# 表に並べる5種類(保護者・子どもに向けた制度)。fs-unei は県の行だけなので表に入れない。
MATRIX_KINDS = ["fs-hojo", "shien-center", "tayouka", "online", "shusseki"]
KIND_SHORT = {
    "fs-hojo": "利用料の補助",
    "shien-center": "教育支援センター",
    "tayouka": "学びの多様化学校",
    "online": "オンライン",
    "shusseki": "出席扱いの要綱・一覧",
    "fs-unei": "施設への補助(設置者向け)",
}

STATUS_MEANING = {
    "あり": "公式の出典、根拠の箇所、確認日がそろっている。",
    "予定": "始まる予定であることが、公式の出典に書かれている。",
    "なし": "市町村が「無い」と答えた記録か、公式の一覧に載っていないことを確かめた記録がある。どちらなのかは「なしの根拠」に書いてある。",
    "確認できず": "公式ページで見つからなかっただけ。制度が無いとは言っていない。",
}
METHOD_MEANING = {
    "機械の読み取り": "プログラムが公式ページを読んで項目にした。出典のある行は、ページの文字列と照合している。",
    "人の読み取り": "人が公式ページを見て項目にした。",
    "人の再確認": "機械の読み取りを、人が公式ページと見比べた。",
    "問い合わせ": "市町村に問い合わせて、回答をもらった。",
}

# 語彙。ラベルは data/seido.csv の列の名前。説明は docs/データの項目.md の決まりを短くしたもの。
PROPERTIES = {
    "kind": ("制度の種類", "6つの種類のどれか。", "skos:Concept"),
    "status": ("状態", "あり / 予定 / なし / 確認できず。「なし」と「確認できず」を混ぜない。", "skos:Concept"),
    "paymentForm": ("補助の形", "毎月の補助と1回きりの補助を取り違えないための区別。", "skos:Concept"),
    "eligibility": ("対象", "だれが使えるか。要点に直したもの。", "rdf:langString"),
    "amountText": ("金額", "金額の決まり。", "rdf:langString"),
    "amountMaxYen": ("上限額_円", "上限の金額。円の整数。", "xsd:integer"),
    "subsidyRate": ("補助率", "補助の割合。1/2 の形。", "xsd:string"),
    "startText": ("開始", "いつから。", "rdf:langString"),
    "sourceName": ("出典名", "出典のページの呼び名。出典の URL は dct:source に入る。", "rdf:langString"),
    "basisPhrase": ("根拠の箇所", "出典のページにある短い語句(40字まで)。照合に使う。第2の出典の節でも使う。", "rdf:langString"),
    "additionalSource": ("第2の出典", "項目の根拠が、出典のページでなく別のページや資料にあるときの、その資料。", "fsl:AdditionalSource"),
    "supports": ("出典2の項目", "第2の出典で裏付ける項目(この語彙や schema.org の性質)。", "rdf:Property"),
    "guidelineState": ("要綱の状況", "要綱を取得できたか。", "rdf:langString"),
    "guideline": ("要綱URL", "要綱の URL。", "rdfs:Resource"),
    "searchedAt": ("探した場所", "探したページの URL。「確認できず」のときに必ず入る。", "rdfs:Resource"),
    "noneBasis": ("なしの根拠", "無いと言える理由。「なし」のときに必ず入る。", "rdf:langString"),
    "note": ("備考", "補足。", "rdf:langString"),
    "dateChecked": ("確認日", "確かめた日。", "xsd:date"),
    "checkMethod": ("確認方法", "だれが、どう確かめたか。", "skos:Concept"),
}
# rdfs:domain が fsl:Record でない性質。None は domain を書かない(記録と第2の出典の節の両方で使うため)
DOMAINS = {"sourceName": None, "basisPhrase": None, "supports": "fsl:AdditionalSource"}

SCHEMES = [
    ("kinds", "制度の種類", "kind", {slug: (label, "") for slug, label in schema.KINDS.items()}),
    ("statuses", "状態", "status", {slug: (label, STATUS_MEANING[label]) for label, slug in schema.STATUSES.items()}),
    ("forms", "補助の形", "form", {slug: (label, "") for label, slug in schema.FORMS.items()}),
    ("methods", "確認方法", "method", {slug: (label, METHOD_MEANING[label]) for label, slug in schema.METHODS.items()}),
]


# ---------- Turtle ----------

_IRI_BAD = re.compile(r'[<>"{}|^`\\\x00-\x20]')


def iri(url: str) -> str:
    return "<" + _IRI_BAD.sub(lambda m: f"%{ord(m.group()):02X}", url) + ">"


def lit(text: str, datatype: str = "") -> str:
    s = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{s}"' + (f"^^{datatype}" if datatype else "")


def ref(value: str) -> str:
    """@id として書かれた値。fsl: などの短い形はそのまま、URL は <> で囲む。"""
    prefix = value.split(":", 1)[0]
    if prefix in PREFIXES and not value.startswith(("http://", "https://")):
        return value
    return iri(value)


def node_triples(node: dict) -> list[tuple[str, list[tuple[str, list[str]]]]]:
    """JSON-LD の節を (主語, [(述語, [目的語...])]) の並びにする。入れ子(areaServed)は別の主語になる。"""
    blocks: list[tuple[str, list[tuple[str, list[str]]]]] = []
    types = node["@type"] if isinstance(node["@type"], list) else [node["@type"]]
    pos: list[tuple[str, list[str]]] = [("a", types)]
    for key, value in node.items():
        if key.startswith("@"):
            continue
        term = build.CONTEXT[key]
        pred = term["@id"] if isinstance(term, dict) else term
        coerce = term.get("@type", "") if isinstance(term, dict) else ""
        values = value if isinstance(value, list) else [value]
        objs = []
        for v in values:
            if isinstance(v, dict):
                objs.append(iri(v["@id"]))
                blocks += node_triples(v)
            elif coerce == "@id":
                objs.append(ref(v))
            elif coerce:
                objs.append(lit(v, coerce))
            else:
                # 言語は CONTEXT の決まりに従う(全体は ja。項目ごとに外せる)
                lang = term["@language"] if isinstance(term, dict) and "@language" in term else build.CONTEXT.get("@language")
                objs.append(lit(v) + (f"@{lang}" if lang else ""))
        pos.append((pred, objs))
    return [(iri(node["@id"]), pos)] + blocks


def turtle(blocks: list[tuple[str, list[tuple[str, list[str]]]]]) -> str:
    out = [f"@prefix {p}: <{u}> ." for p, u in PREFIXES.items()] + [""]
    seen: set[str] = set()
    for subj, pos in blocks:
        body = " ;\n".join(f"    {p} {', '.join(objs)}" for p, objs in pos)
        text = f"{subj}\n{body} .\n"
        if text not in seen:  # 同じ市町村の節は1回だけ書く
            seen.add(text)
            out.append(text)
    return "\n".join(out)


def nodes_turtle(nodes: list[dict]) -> str:
    return turtle([b for n in nodes for b in node_triples(n)])


def vocab_turtle() -> str:
    blocks = [
        (iri(BASE + "ns"), [
            ("a", ["owl:Ontology"]),
            ("rdfs:label", [lit("不登校支援制度LOD の語彙") + "@ja"]),
            ("rdfs:comment", [lit("市町村の不登校支援の制度について、確かめた記録を書くための項目と値。") + "@ja"]),
            ("dct:license", [iri(LICENSE)]),
        ]),
        ("fsl:Record", [
            ("a", ["rdfs:Class"]),
            ("rdfs:label", [lit("確かめた記録") + "@ja"]),
            ("rdfs:comment", [lit(
                "1つの市町村の、1つの種類の制度について、確かめた結果の記録。制度が無い・確認できていない場合も記録になる。"
                "制度があると確かめた記録(状態が あり・予定)だけが、schema:GovernmentService でもある。") + "@ja"]),
            ("rdfs:isDefinedBy", [iri(BASE + "ns")]),
        ]),
    ]
    blocks.append(("fsl:AdditionalSource", [
        ("a", ["rdfs:Class"]),
        ("rdfs:label", [lit("第2の出典") + "@ja"]),
        ("rdfs:comment", [lit(
            "項目の根拠が、出典のページでなく別のページや資料にあるときの、その資料。"
            "URL(dct:source)、呼び名、資料にある短い語句、裏付ける項目を持つ。照合は出典ごとに分けて行う。") + "@ja"]),
        ("rdfs:isDefinedBy", [iri(BASE + "ns")]),
    ]))
    for name, (label, comment, rng) in PROPERTIES.items():
        domain = DOMAINS.get(name, "fsl:Record")
        pos = [
            ("a", ["rdf:Property"]),
            ("rdfs:label", [lit(label) + "@ja"]),
            ("rdfs:comment", [lit(comment) + "@ja"]),
        ]
        if domain:
            pos.append(("rdfs:domain", [domain]))
        pos += [("rdfs:range", [rng]), ("rdfs:isDefinedBy", [iri(BASE + "ns")])]
        blocks.append((f"fsl:{name}", pos))
    for scheme, title, prefix, concepts in SCHEMES:
        blocks.append((f"fsl:{scheme}", [("a", ["skos:ConceptScheme"]), ("skos:prefLabel", [lit(title) + "@ja"])]))
        for slug, (label, definition) in concepts.items():
            pos = [("a", ["skos:Concept"]), ("skos:inScheme", [f"fsl:{scheme}"]),
                   ("skos:prefLabel", [lit(label) + "@ja"]), ("skos:notation", [lit(slug)])]
            if definition:
                pos.append(("skos:definition", [lit(definition) + "@ja"]))
            blocks.append((f"fsl:{prefix}-{slug}", pos))
    return turtle(blocks)


def dataset_turtle(rows: list[dict[str, str]]) -> str:
    modified = max(r["確認日"] for r in rows)
    dists = [("seido.csv", "text/csv"), ("seido.jsonld", "application/ld+json"), ("seido.ttl", "text/turtle")]
    blocks = [(iri(DATASET), [
        ("a", ["dcat:Dataset"]),
        ("dct:title", [lit(TITLE) + "@ja"]),
        ("dct:description", [lit(
            "福岡県の市町村ごとの不登校支援の制度を、同じ項目で並べ、公式の出典と確認日を付けたデータ。"
            "「制度なし」と「確認できず」を分けて記録する。対象は義務教育の段階。") + "@ja"]),
        ("dct:license", [iri(LICENSE)]),
        ("dct:creator", [iri(AUTHOR)]),
        ("dct:publisher", [iri(AUTHOR)]),
        ("dct:issued", [lit(ISSUED, "xsd:date")]),
        ("dct:modified", [lit(modified, "xsd:date")]),
        ("dct:language", [lit("ja")]),
        ("dcat:keyword", [lit(k) + "@ja" for k in ("不登校", "教育支援センター", "フリースクール", "学びの多様化学校", "福岡県")]),
        ("dcat:contactPoint", [iri(REPO + "/issues")]),
        ("dct:spatial", [iri(build.SAC + "40000")]),
        ("dct:conformsTo", [iri(NS)]),
        ("dcat:landingPage", [iri(BASE)]),
        ("dcat:distribution", [iri(BASE + f) for f, _ in dists]),
    ])]
    blocks.append((iri(AUTHOR), [("a", ["schema:Person"]), ("schema:name", [lit("h-kazuki-pixel")]), ("schema:url", [iri(AUTHOR)])]))
    for f, mime in dists:
        blocks.append((iri(BASE + f), [("a", ["dcat:Distribution"]), ("dcat:accessURL", [iri(BASE)]),
                                       ("dcat:downloadURL", [iri(BASE + f)]),
                                       ("dcat:mediaType", [iri("https://www.iana.org/assignments/media-types/" + mime)]), ("dct:license", [iri(LICENSE)])]))
    return turtle(blocks)


# ---------- HTML ----------

CSS = """\
:root{--ink:#1c2321;--sub:#55605c;--line:#c9d1cd;--bg:#fbfcfb;--accent:#1f5f4a;--soft:#eef3f0}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,"Hiragino Sans","Noto Sans JP",sans-serif;color:var(--ink);background:var(--bg);line-height:1.75}
main,header,footer{max-width:62rem;margin:0 auto;padding:1rem 1.25rem}
header a{color:var(--accent);font-weight:700;text-decoration:none}
footer{color:var(--sub);font-size:.875rem;border-top:1px solid var(--line);margin-top:3rem}
h1{font-size:1.6rem;line-height:1.4;margin:.5rem 0 1rem}
h2{font-size:1.15rem;margin:2.5rem 0 .75rem;padding-bottom:.25rem;border-bottom:2px solid var(--accent)}
a{color:var(--accent)}
a:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.lead{font-size:1.05rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.925rem}
th,td{border:1px solid var(--line);padding:.45rem .6rem;text-align:left;vertical-align:top}
thead th{background:var(--soft)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.st{display:inline-block;white-space:nowrap;padding:0 .5rem;border-radius:.25rem;border:1px solid var(--line)}
.st-ari,.st-yotei{background:var(--accent);border-color:var(--accent);color:#fff}
.st-nashi{background:var(--soft)}
.st-kakunin-dekizu{border-style:dashed;color:var(--sub)}
.st-mi{border:0;color:var(--sub)}
a .st{text-decoration:underline}
dl.rec{display:grid;grid-template-columns:minmax(7rem,12rem) 1fr;margin:0;border-top:1px solid var(--line)}
dl.rec dt,dl.rec dd{margin:0;padding:.5rem .25rem;border-bottom:1px solid var(--line)}
dl.rec dt{color:var(--sub)}
dl.rec dd{overflow-wrap:anywhere}
.note{background:var(--soft);padding:.75rem 1rem;border-left:4px solid var(--accent)}
code{font-size:.9em;overflow-wrap:anywhere}
@media (max-width:36rem){dl.rec{grid-template-columns:1fr}dl.rec dt{border-bottom:0;padding-bottom:0}}
"""

e = html.escape


def page(title: str, body: str, root: str, head: str = "") -> str:
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<link rel="stylesheet" href="{root}style.css">
{head}</head>
<body>
<header><a href="{root}">{TITLE}</a> ／ <a href="{root}about/" style="font-weight:400">この作品について</a></header>
<main>
{body}
</main>
<footer>
<p>データは <a href="{LICENSE}">CC BY 4.0</a>。制度は変わる。使う前に、各行の出典と確認日を確かめてほしい。申請できるかどうかは、市町村の窓口で確かめてほしい。</p>
<p>誤りや、制度が変わった所を見つけたら、<a href="{REPO}/issues">GitHub の Issue</a> で知らせてほしい。<a href="{REPO}">リポジトリ</a></p>
</footer>
</body>
</html>
"""


def badge(status: str) -> str:
    slug = schema.STATUSES.get(status, "mi")
    return f'<span class="st st-{slug}">{e(status)}</span>'


def link(url: str) -> str:
    return f'<a href="{e(url)}" rel="noopener">{e(url)}</a>'


def jst_day(stamp: str) -> str:
    """取得日時(UTC)を、日本時間の日付にする。"""
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(stamp).astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    except ValueError:
        return stamp[:10]


def list_based_none(row: dict[str, str]) -> bool:
    """市町村の回答ではなく、公式の一覧に載っていないことを根拠にした「なし」。"""
    return row["状態"] == "なし" and row["確認方法"] != "問い合わせ"


def kind_slug(row: dict[str, str]) -> str:
    return schema.KIND_BY_LABEL[row["制度の種類"]]


def index_html(rows: list[dict[str, str]], areas: list[dict[str, str]], records: dict | None = None) -> str:
    cell: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for r in rows:
        cell[(r["市町村コード"], kind_slug(r))].append(r)
    metro = [a for a in areas if a["福岡都市圏"] == "○"]
    filled: collections.Counter = collections.Counter()
    lines = []
    for a in metro:
        tds = []
        for k in MATRIX_KINDS:
            found = cell.get((a["市町村コード"], k), [])
            if found:
                filled[found[0]["状態"]] += 1  # マスの数は、1つ目の行の状態で数える
                tds.append("<td>" + " ".join(
                    f'<a href="id/{e(r["id"])}/" aria-label="{e(a["市町村"])} {e(KIND_SHORT[k])}: {e(r["状態"])}">'
                    f'{badge(r["状態"])}</a>' + ("※" if list_based_none(r) else "") for r in found) + "</td>")
            elif any(q["市町村コード"] == a["市町村コード"] and q["種類"].strip() == k for q in (records or {}).get("toiawase", [])):
                # 読んでいないが、市町に問い合わせてある(須恵町の出席扱いなど)
                tds.append(f"<td>{badge('未着手')}<br><small>問い合わせ中</small></td>")
            else:
                tds.append(f"<td>{badge('未着手')}</td>")
        lines.append(f'<tr><th scope="row">{e(a["市町村"])}</th>{"".join(tds)}</tr>')
    by_kind = collections.Counter((kind_slug(r), r["状態"]) for r in rows)
    kind_lines = []
    for k in schema.KINDS:
        n = [by_kind[(k, s)] for s in schema.STATUSES]
        kind_lines.append(f'<tr><th scope="row">{e(schema.KINDS[k])}</th>'
                          + "".join(f'<td class="num">{x}</td>' for x in n) + f'<td class="num">{sum(n)}</td></tr>')
    total = collections.Counter(r["状態"] for r in rows)
    methods = collections.Counter(r["確認方法"] for r in rows)
    answered_nashi = sum(r["状態"] == "なし" and r["確認方法"] == "問い合わせ" for r in rows)
    modified = max(r["確認日"] for r in rows)
    records = records or {"torinaoshi": [], "saikakunin": [], "toiawase": []}
    checks = []
    if records["torinaoshi"]:
        pages = {r["URL"]: r for r in records["torinaoshi"]}
        day = max(jst_day(r["取得日時"]) for r in pages.values())
        got = sum(r["取得"] == "取得" for r in pages.values())
        checks.append(f"出典と探した場所のページは、週に1回取り直す。いちばん新しい取り直しは {e(day)}({len(pages)}ページのうち、取得できた {got})。")
    if records["saikakunin"]:
        items_all = len(records["saikakunin"])
        c = collections.Counter(r["判定"] for r in records["saikakunin"] if r["判定"])
        checks.append(f"「あり」「予定」の行は、項目ごとに人が出典と見比べる。{items_all}項目のうち、見比べたのは {sum(c.values())}"
                      f"(合っている {c['合っている']}、違う {c['違う']}、分からない {c['分からない']})。")
    checks.append(f"市町への問い合わせの記録は {len(records['toiawase'])} 件。")
    checks_html = "".join(f"<p>{x}</p>\n" for x in checks)
    metro_codes = {a["市町村コード"] for a in metro}
    outside = [r for r in rows if r["市町村コード"] not in metro_codes and r["市町村コード"] != "40000"]
    outside_other = sum(kind_slug(r) != "tayouka" for r in outside)
    tayouka_codes = {r["市町村コード"] for r in rows if kind_slug(r) == "tayouka"}
    missing = [a["市町村"] for a in areas if a["市町村コード"] != "40000" and a["市町村コード"] not in tayouka_codes]
    scope_note = (f"都市圏の外の市町村は、主に学びの多様化学校を調べている(ほかの種類の行は {outside_other} 件)。"
                  f"学びの多様化学校の行があるのは、県内60市町村のうち {len(tayouka_codes - {'40000'})}。"
                  + (f"まだ行が無いのは {'、'.join(missing)}。" if missing else ""))
    legend = "".join(f"<tr><td>{badge(s)}</td><td>{e(m)}</td></tr>" for s, m in STATUS_MEANING.items())
    legend += f"<tr><td>{badge('未着手')}</td><td>まだ読んでいない。</td></tr>"
    body = f"""<h1>{TITLE}</h1>
<p class="lead">市町村ごとに違う不登校支援の制度を、同じ項目で並べ、公式の出典と確認日を付けたデータ。対象は福岡県の市町村、義務教育の段階(小学生・中学生)。</p>
<p class="note">いちばん大事にしている決まりは一つ。<strong>「制度なし」と「確認できず」を混ぜない。</strong>公式ページで見つからなかっただけのものは「確認できず」と書き、探した場所を残す。</p>

<h2>福岡都市圏の17市町 × 5種類</h2>
<p>{len(metro) * len(MATRIX_KINDS)}マスのうち、{sum(filled.values())}マスに状態が付いている(あり {filled['あり']}、予定 {filled['予定']}、なし {filled['なし']}、確認できず {filled['確認できず']})。マスを選ぶと、その1件のページが開く。</p>
<div class="scroll"><table>
<thead><tr><th scope="col">市町</th>{"".join(f'<th scope="col">{e(KIND_SHORT[k])}</th>' for k in MATRIX_KINDS)}</tr></thead>
<tbody>
{chr(10).join(lines)}
</tbody></table></div>
<p>※ の付いた「なし」は、公式の一覧(学びの多様化学校では、文部科学省の設置者一覧)に、その市町が管理する学校が載っていないという意味。市町が「無い」と答えたものではない。設置の検討や予定は、この一覧からは分からない。</p>
<p>「確認できず」は、公式ページで見つからなかっただけで、制度が無いという意味ではない。使えるかどうかは、市町の教育委員会に確かめてほしい。</p>

<h2>状態の意味</h2>
<div class="scroll"><table><thead><tr><th scope="col">状態</th><th scope="col">意味</th></tr></thead><tbody>{legend}</tbody></table></div>

<h2>種類ごとの件数</h2>
<p>全{len(rows)}件(あり {total['あり']}、予定 {total['予定']}、なし {total['なし']}、確認できず {total['確認できず']})。件数は種類で大きく違うので、分けて示す。{e(scope_note)}</p>
<div class="scroll"><table>
<thead><tr><th scope="col">種類</th>{"".join(f'<th scope="col">{e(s)}</th>' for s in schema.STATUSES)}<th scope="col">計</th></tr></thead>
<tbody>
{chr(10).join(kind_lines)}
</tbody></table></div>
<p>「なし」{total['なし']}件のうち、公式の一覧に載っていないことを根拠にしたものは {sum(list_based_none(r) for r in rows)} 件(いまは、すべて学びの多様化学校)。市町村の回答に基づく「なし」は {answered_nashi} 件。</p>
<p>確かめ方の内訳: {"、".join(f"{e(m)} {methods[m]}件" for m in schema.METHODS)}。確認日のいちばん新しい行は {e(modified)}。</p>
<p><a href="ichiran/">全{len(rows)}件の一覧</a></p>

<h2>確かめ方の現状</h2>
{checks_html}
<h2>データ</h2>
<div class="scroll"><table>
<thead><tr><th scope="col">ファイル</th><th scope="col">形式</th></tr></thead>
<tbody>
<tr><td><a href="seido.csv">seido.csv</a></td><td>CSV(UTF-8)。1行 = 1市町村の1制度</td></tr>
<tr><td><a href="seido.jsonld">seido.jsonld</a></td><td>JSON-LD</td></tr>
<tr><td><a href="seido.ttl">seido.ttl</a></td><td>Turtle</td></tr>
<tr><td><a href="ns">ns</a> / <a href="ns.ttl">ns.ttl</a></td><td>語彙(項目と、種類・状態などの値)の説明</td></tr>
<tr><td><a href="dataset.ttl">dataset.ttl</a></td><td>このデータセットの説明(DCAT)</td></tr>
<tr><td><a href="kumiawase/">組み合わせの例</a> / <a href="kumiawase.csv">kumiawase.csv</a></td><td>e-Stat 統計LOD の児童数・生徒数と、標準地域コードの URI で並べた例。数字は e-Stat 統計LOD によるもの</td></tr>
</tbody></table></div>
<p>1件ごとの URI は <code>{e(BASE)}id/{{id}}</code>。同じ場所に <code>.ttl</code> と <code>.jsonld</code> を付けると、その1件のデータが取れる。市町村は、e-Stat 統計LOD の標準地域コードと、DBpedia Japanese の資源につないでいる。</p>

<h2>対象の範囲</h2>
<p>根拠の法律({e(LAW)})の範囲に合わせ、義務教育の段階に向けた市町村の制度を対象にしている。福岡都市圏の17市町は5種類すべてを、そのほかの市町村は主に学びの多様化学校を調べている。個人の体験、施設の評価、口コミは載せない。</p>
"""
    return page(TITLE, body, "")


def ichiran_html(rows: list[dict[str, str]]) -> str:
    trs = "\n".join(
        f'<tr><th scope="row">{e(r["市町村"])}</th><td>{e(KIND_SHORT[kind_slug(r)])}</td><td>{badge(r["状態"])}</td>'
        f'<td>{e(r["制度名"])}</td><td>{e(r["確認日"])}</td><td><a href="../id/{e(r["id"])}/">{e(r["id"])}</a></td></tr>'
        for r in rows)
    body = f"""<h1>全{len(rows)}件の一覧</h1>
<div class="scroll"><table>
<thead><tr><th scope="col">市町村</th><th scope="col">種類</th><th scope="col">状態</th><th scope="col">制度名</th><th scope="col">確認日</th><th scope="col">id</th></tr></thead>
<tbody>
{trs}
</tbody></table></div>
"""
    return page(f"全件の一覧 | {TITLE}", body, "../")


def record_html(row: dict[str, str], node: dict, siblings: list[dict[str, str]], records: dict | None = None) -> str:
    def v(key: str) -> str:
        return (row.get(key) or "").strip()

    items: list[tuple[str, str]] = [
        ("市町村", f'{e(v("市町村"))} (<a href="{e(node["areaServed"]["@id"])}" rel="noopener">標準地域コード {e(v("市町村コード"))}</a>'
                   + (f'、<a href="{e(node["areaServed"]["sameAs"])}" rel="noopener">DBpedia Japanese</a>' if node["areaServed"].get("sameAs") else "") + ")"),
        ("制度の種類", e(v("制度の種類"))),
        ("状態", f'{badge(v("状態"))} {e(STATUS_MEANING[v("状態")])}'),
    ]
    for key in ("制度名", "補助の形", "対象", "金額"):
        if v(key):
            items.append((key, e(v(key))))
    if v("上限額_円"):
        items.append(("上限額", f'{int(v("上限額_円")):,}円'))
    for key in ("補助率", "開始"):
        if v(key):
            items.append((key, e(v(key))))
    if v("出典URL"):
        items.append(("出典", f'{e(v("出典名"))}<br>{link(v("出典URL"))}'))
    if v("根拠の箇所"):
        items.append(("根拠の箇所", f'「{e(v("根拠の箇所"))}」(出典のページにある語句)'))
    if v("出典URL_2"):
        fields = "、".join(schema.source2_fields(row))
        items.append(("第2の出典", f'{e(v("出典名_2"))}<br>{link(v("出典URL_2"))}<br>'
                      f'根拠の箇所「{e(v("根拠の箇所_2"))}」。この資料で裏付ける項目: {e(fields)}'))
    if v("要綱の状況"):
        items.append(("要綱", e(v("要綱の状況")) + (f'<br>{link(v("要綱URL"))}' if v("要綱URL") else "")))
    if v("なしの根拠"):
        items.append(("なしの根拠", e(v("なしの根拠"))))
    places = node.get("searchedAt", [])
    if places:
        items.append(("探した場所", "<br>".join(link(p) for p in places)))
    if v("備考"):
        items.append(("備考", e(v("備考"))))
    items.append(("確認日", e(v("確認日"))))
    items.append(("確認方法", f'{e(v("確認方法"))}。{e(METHOD_MEANING[v("確認方法")])}'))
    records = records or {"torinaoshi": [], "saikakunin": [], "toiawase": []}
    recheck = recheck_line(row, records)
    if recheck:
        items.append(("人の再確認", e(recheck)))
    inquiries = inquiry_lines(row, records)
    if inquiries:
        items.append(("問い合わせ", "<br>".join(e(x) for x in inquiries)))
    refetch = refetch_lines(row, records)
    if refetch:
        items.append(("定期的な取り直し", "<br>".join(e(x) for x in refetch)))
    dl = "\n".join(f"<dt>{k}</dt><dd>{val}</dd>" for k, val in items)

    caution = ""
    if v("状態") == "確認できず":
        caution = ('<p class="note">この1件は、公式ページで見つからなかっただけ。<strong>制度が無いという意味ではない。</strong>'
                   '探したページは下にある。使えるかどうかは、市町村の教育委員会に確かめてほしい。</p>\n')
    elif list_based_none(row):
        caution = ('<p class="note">この「なし」は、<strong>公式の一覧に載っていない</strong>という意味。市町村が「無い」と答えたものではない。'
                   '設置の検討や予定は、一覧からは分からない。</p>\n')
    elif kind_slug(row) in ("fs-hojo", "fs-unei") and v("状態") in ("あり", "予定"):
        # 申請の受付期間は年度ごとに変わるので、データには持たない(docs/弱い所.md の 33)
        caution = ('<p class="note">「あり」は、制度があるという意味。<strong>いま申請を受け付けているかは、このデータには無い。</strong>'
                   '申請の時期や受付の期間は、出典のページで確かめてほしい。</p>\n')
    sib = "".join(
        f'<li><a href="../{e(s["id"])}/">{e(KIND_SHORT[kind_slug(s)])}</a> {badge(s["状態"])}</li>'
        for s in sorted(siblings, key=lambda s: list(schema.KINDS).index(kind_slug(s))) if s["id"] != row["id"])
    sib_html = f'<h2>{e(v("市町村"))}のほかの種類</h2>\n<ul>{sib}</ul>\n' if sib else ""
    uri = node["@id"]
    jsonld = json.dumps({"@context": build.CONTEXT, **node}, ensure_ascii=False, indent=1).replace("</", "<\\/")
    head = (f'<link rel="alternate" type="text/turtle" href="../{e(row["id"])}.ttl">\n'
            f'<link rel="alternate" type="application/ld+json" href="../{e(row["id"])}.jsonld">\n'
            f'<script type="application/ld+json">\n{jsonld}\n</script>\n')
    title = f'{v("市町村")} {KIND_SHORT[kind_slug(row)]}'
    body = f"""<h1>{e(title)}</h1>
{caution}<dl class="rec">
{dl}
</dl>
{sib_html}<h2>この1件のデータ</h2>
<p>URI: <code>{e(uri)}</code></p>
<p><a href="../{e(row["id"])}.ttl">Turtle</a> / <a href="../{e(row["id"])}.jsonld">JSON-LD</a> / <a href="../../ichiran/">全件の一覧</a></p>
"""
    return page(f"{title} | {TITLE}", body, "../../", head)


def about_html(rows: list[dict[str, str]], areas: list[dict[str, str]], records: dict) -> str:
    """この作品について。数はすべてデータから数える(書いた時点の数を残さない)。"""
    total = collections.Counter(r["状態"] for r in rows)
    metro = {a["市町村コード"] for a in areas if a["福岡都市圏"] == "○"}
    cells = {(r["市町村コード"], kind_slug(r)): r["状態"] for r in rows if r["市町村コード"] in metro and kind_slug(r) in MATRIX_KINDS}
    cell_count = collections.Counter(cells.values())
    area_codes = {r["市町村コード"] for r in rows}
    judged = collections.Counter(r["判定"] for r in records["saikakunin"] if r["判定"])
    pages = {r["URL"]: r for r in records["torinaoshi"]}
    got = sum(r["取得"] == "取得" for r in pages.values())
    answered_nashi = sum(r["状態"] == "なし" and r["確認方法"] == "問い合わせ" for r in rows)
    listed_nashi = sum(list_based_none(r) for r in rows)
    refetch = (f"いちばん新しい取り直しでは、{len(pages)}ページのうち {got} ページを取得できた。" if pages else "")
    body = f"""<h1>この作品について</h1>
<p class="lead">不登校の子どもと保護者が使える公的な支援は、市町村ごとに違う。このデータは、福岡県の市町村について、制度の有無と中身を同じ項目で並べ、1件ごとに公式の出典と確認日を付けたもの。</p>

<h2>解こうとしている課題</h2>
<p>市町村の公式サイトに制度の記載が無いとき、それが「制度が無い」のか「載っていないだけ」なのかは、ページからは分からない。一覧にまとめるときに、この2つは同じ空欄になりやすい。空欄を「無い」と読めば、使える制度を見逃す。</p>
<p>このデータは、状態を4つに分ける。<strong>あり、予定、なし、確認できず。</strong>「なし」と書けるのは、市町村が無いと答えた記録か、公式の一覧に載っていないことを確かめた記録がある場合だけ。見つからなかっただけのものは「確認できず」とし、どのページを探したかを残す。</p>

<h2>いまの中身</h2>
<div class="scroll"><table>
<thead><tr><th scope="col">数えたもの</th><th scope="col">数</th><th scope="col">数え方</th></tr></thead>
<tbody>
<tr><th scope="row">記録</th><td class="num">{len(rows)}</td><td>1件 = 1市町村の1種類。{len(area_codes)}の市町村・県</td></tr>
<tr><th scope="row">あり・予定</th><td class="num">{total['あり'] + total['予定']}</td><td>出典のページに、根拠の語句と数字があることを照合した</td></tr>
<tr><th scope="row">なし</th><td class="num">{total['なし']}</td><td>公式の一覧に載っていないことによるもの {listed_nashi}、市町村の回答によるもの {answered_nashi}</td></tr>
<tr><th scope="row">確認できず</th><td class="num">{total['確認できず']}</td><td>探した場所を記録している</td></tr>
<tr><th scope="row">福岡都市圏17市町×5種類</th><td class="num">{len(cells)} / {len(metro) * len(MATRIX_KINDS)}</td><td>状態が付いたマス(あり {cell_count['あり']}、予定 {cell_count['予定']}、なし {cell_count['なし']}、確認できず {cell_count['確認できず']})</td></tr>
<tr><th scope="row">人が出典と見比べた項目</th><td class="num">{sum(judged.values())} / {len(records['saikakunin'])}</td><td>「あり」「予定」の行の項目。合っている {judged['合っている']}、違う {judged['違う']}、分からない {judged['分からない']}</td></tr>
<tr><th scope="row">市町への問い合わせの記録</th><td class="num">{len(records['toiawase'])}</td><td></td></tr>
</tbody></table></div>

<h2>正しさを保つ仕組み</h2>
<ul>
<li><strong>読み込みの検査。</strong>「あり」「予定」は、出典の URL・根拠の語句・確認日がそろわないと保存できない。「確認できず」は、探した場所が無いと保存できない。出典は、市町村・県・国の公式サイトだけ。</li>
<li><strong>出典との照合。</strong>金額・対象・時期に出てくる数字と単位が、出典のページに実際にあるかを、プログラムで確かめる。合わない行は公開しない。</li>
<li><strong>別の目。</strong>読み取りとは別の呼び出し、別の種類の AI、人の3つで、出典と見比べる。人が見た数は上の表のとおり。</li>
<li><strong>定期的な取り直し。</strong>週に1回、出典と探した場所のページを取り直し、前回から変わった所を記録する。出典と合わなくなった行は、知らせが出る。{refetch}</li>
</ul>

<h2>使い方</h2>
<ul>
<li><strong>人が読む。</strong><a href="../">市町×種類の表</a>から、1件のページへ。出典のページへのリンク、確認日、確かめ方が載っている。</li>
<li><strong>プログラムで読む。</strong><a href="../seido.csv">CSV</a>、<a href="../seido.jsonld">JSON-LD</a>、<a href="../seido.ttl">Turtle</a>。1件ごとに URI があり、<code>.ttl</code> か <code>.jsonld</code> を付けるとその1件が取れる。ほかのサイトの上のプログラムからも読める。</li>
<li><strong>つなぐ。</strong>市町村は、e-Stat 統計LOD の標準地域コードの URI で持つ。統計LOD の児童数・生徒数と実際に並べた例が<a href="../kumiawase/">組み合わせの例</a>にある。DBpedia Japanese の市町村の資源にも、<code>schema:sameAs</code> でつないでいる(地方公共団体コードが合うことを、1件ずつ引いて確かめたものだけ)。出典は <code>dct:source</code> で公式ページにつながる。</li>
<li><strong>数える。</strong>{len(rows)}件すべてが「確かめた記録」(<code>fsl:Record</code>)。制度があると確かめた記録だけが、schema.org の <code>GovernmentService</code> でもある。語彙の説明は <a href="../ns">ns</a>。</li>
</ul>
<p>データは CC BY 4.0、プログラムは MIT ライセンス。作り方と検査の決まりは、<a href="{REPO}">リポジトリ</a>にある。同じ手順で、ほかの県にも広げられる。</p>

<h2>分かっていないこと、できていないこと</h2>
<ul>
<li>「確認できず」が {total['確認できず']} 件ある。市町に問い合わせて減らしている途中。</li>
<li>「なし」のうち {listed_nashi} 件は、公式の一覧に載っていないという意味で、市町村が無いと答えたものではない。</li>
<li>人が出典と見比べたのは、{len(records['saikakunin'])} 項目のうち {sum(judged.values())}。そのうち「違う」は {judged['違う']}。全部の項目は見ていないので、全体の誤りの割合としては言えない。</li>
<li>照合で分かるのは「ページに無い数字を載せていない」ことまで。数字の意味の取り違えは、人の目で見るしかない。</li>
<li>都市圏の外の市町村は、主に学びの多様化学校だけを調べている。</li>
<li>GitHub Pages では、制度の URI とページを分ける転送(303)や、形式の出し分けはできない。</li>
<li>制度は変わる。申請できるかどうかは、必ず市町村の窓口で確かめてほしい。</li>
</ul>
"""
    return page(f"この作品について | {TITLE}", body, "../")


def kumiawase_html(rows: list[dict[str, str]], areas: list[dict[str, str]], pupils: list[dict[str, str]]) -> str:
    """組み合わせの例。このデータと、e-Stat 統計LOD の児童数・生徒数を、標準地域コードの URI で並べる。"""
    from . import kumiawase as km

    # つなぐ手がかりは URI。公開データの側は areaServed の URI、統計の側は引いたときの URI
    cell: dict[tuple[str, str], list[dict[str, str]]] = collections.defaultdict(list)
    for r in rows:
        cell[(build.to_node(r)["areaServed"]["@id"], kind_slug(r))].append(r)
    by_uri = {p["標準地域コードのURI"]: p for p in pupils}
    lines, notes = [], []
    for a in (a for a in areas if a["福岡都市圏"] == "○"):
        uri = build.SAC + a["市町村コード"]
        p = by_uri.get(uri, {})
        found = [r for k in MATRIX_KINDS for r in cell.get((uri, k), [])]
        c = collections.Counter(r["状態"] for r in found)
        listed = sum(list_based_none(r) for r in found)
        untouched = sum(not cell.get((uri, k)) for k in MATRIX_KINDS)

        def num(key: str) -> str:
            return f'{int(p[key]):,}' if p.get(key) else "返らなかった"

        if p.get("備考"):
            notes.append(f'{a["市町村"]}: {p["備考"]}')
        lines.append(
            f'<tr><th scope="row">{e(a["市町村"])}</th><td class="num">{num("小学校児童数")}</td><td class="num">{num("中学校生徒数")}</td>'
            f'<td class="num">{c["あり"] + c["予定"]}</td><td class="num">{c["なし"]}{"※" if listed else ""}</td>'
            f'<td class="num">{c["確認できず"]}</td><td class="num">{untouched}</td>'
            f'<td><code>{e(p.get("統計LODの地域コード", ""))}</code></td></tr>')
    years = sorted({p[k] for p in pupils for k in ("小学校児童数の年", "中学校生徒数の年") if p.get(k)})
    fetched = max((p["取得日"] for p in pupils), default="")
    got = sum(bool(p.get("小学校児童数")) for p in pupils)
    sample = build.SAC + "40219"
    notes_html = "".join(f"<li>{e(n)}</li>" for n in notes)
    body = f"""<h1>組み合わせの例: 子どもの数と並べる</h1>
<p class="lead">このデータの市町村は、e-Stat 統計LOD の標準地域コードの URI で持っている。公開している JSON-LD の <code>schema:areaServed</code> の URI から出発して、統計LOD にある小学校の児童数と中学校の生徒数を引き、制度の確かめ具合と並べた。</p>
<p class="note">児童数・生徒数は <strong>{e("、".join(years))}年</strong>の値(この17市町について、統計LOD の「社会・人口統計体系」から引けた、いちばん新しい年)。いまの人数ではない。まちの大きさの目安として見てほしい。「確認できず」は、制度が無いという意味ではない。</p>

<h2>福岡都市圏の17市町</h2>
<div class="scroll"><table>
<caption style="text-align:left;caption-side:top;color:var(--sub)">児童数・生徒数(e-Stat 統計LOD)と、5種類の制度の確かめ具合(このデータ)</caption>
<thead><tr><th scope="col">市町</th><th scope="col">小学校児童数</th><th scope="col">中学校生徒数</th><th scope="col">あり・予定</th><th scope="col">なし</th><th scope="col">確認できず</th><th scope="col">未着手</th><th scope="col">統計LOD の地域コード</th></tr></thead>
<tbody>
{chr(10).join(lines)}
</tbody></table></div>
<p>右の4列は、5種類の制度のうち、それぞれの状態になっている数。<strong>市町の良し悪しを比べる表ではない。</strong>「確認できず」の多さは、こちらの調べが進んでいないことを表す。市町の落ち度ではない。</p>
<p>※ の付いた「なし」は、公式の一覧(学びの多様化学校では、文部科学省の設置者一覧)に、その市町が管理する学校が載っていないという意味。市町が「無い」と答えたものではない。</p>
{f"<ul>{notes_html}</ul>" if notes else ""}
<p>児童数・生徒数の出典: <a href="https://data.e-stat.go.jp/lodw/" rel="noopener">e-Stat 統計LOD</a>(総務省統計局・独立行政法人統計センター)の「社会・人口統計体系」を、{e(fetched)} に引いて、表に直したもの。統計LOD のサイトは、内容を CC BY 4.0 で提供するとしている。引いた結果は <a href="../kumiawase.csv">CSV</a> にある。</p>

<h2>つなぎ方</h2>
<ol>
<li>このデータの1件は、<code>schema:areaServed</code> で <code>{e(sample)}</code> のような URI を指す(時期を持たないコード)。問い合わせは、公開している JSON-LD からこの URI を集めて始める。</li>
<li>統計LOD の観測値は、時期つきのコード(例 <code>C40219-20110301</code>)を指している。時期なしのコードから <code>sacs:latestCode</code> と <code>sacs:pastCode</code> で辿る。</li>
<li>辿った先の地域について、指標(小学校児童数 <code>E2501</code>、中学校生徒数 <code>E3501</code>)の観測値を引く。</li>
<li>いまのコードに観測値が無い市町(市になってコードが替わった所)は、<code>sacs:succeedingMunicipality</code> を逆に辿って前の地域を見つけ、その値を使う。前の地域が2つ以上あるとき(合併)は、足さずに空のままにする。</li>
</ol>
<p>大野城市の分を引く問い合わせ(SPARQL)。送り先は <code>{e(km.ENDPOINT)}</code>。</p>
<pre style="overflow-x:auto;background:var(--soft);padding:.75rem"><code>{e(km.pupils_query([sample]))}</code></pre>

<h2>分かったこと、できていないこと</h2>
<ul>
<li>時期なしのコードを直接指す観測値は無かった(大野城市と那珂川市で確かめた)。時期つきのコードへ辿る1手が要る。</li>
<li>17市町のうち {got} 市町で値が返った。値は{e(years[-1] if years else "")}年までだった(この17市町で引いた範囲)。それより新しい年の値は、統計LOD からは取れなかった。</li>
<li>問い合わせの結果は、1000行で切られる。年を絞って引いている。</li>
<li>並べたのは児童数・生徒数だけ。ほかの統計(人口、世帯など)とは、まだ試していない。</li>
<li>11年前の人数と、いまの制度を並べている。人数が大きく変わった市町では、目安としても粗い。</li>
<li>ほかの人がこのデータを使った例は、まだ無い。</li>
</ul>
"""
    return page(f"組み合わせの例 | {TITLE}", body, "../")


def ns_html() -> str:
    props = "\n".join(
        f'<tr id="{name}"><td><code>fsl:{name}</code></td><td>{e(label)}</td><td>{e(comment)}</td></tr>'
        for name, (label, comment, _) in PROPERTIES.items())
    parts = []
    for _, title, prefix, concepts in SCHEMES:
        trs = "\n".join(
            f'<tr id="{prefix}-{slug}"><td><code>fsl:{prefix}-{slug}</code></td><td>{e(label)}</td><td>{e(d)}</td></tr>'
            for slug, (label, d) in concepts.items())
        parts.append(f'<h2>{e(title)}</h2>\n<div class="scroll"><table>\n<thead><tr><th scope="col">値</th>'
                     f'<th scope="col">名前</th><th scope="col">意味</th></tr></thead>\n<tbody>\n{trs}\n</tbody></table></div>')
    body = f"""<h1>語彙(fsl:)</h1>
<p>名前空間は <code>{e(NS)}</code>。同じ中身の Turtle は <a href="ns.ttl">ns.ttl</a>。1件は「確かめた記録」(<code>fsl:Record</code>)。制度があると確かめた記録(状態が あり・予定)だけが、schema.org の <code>GovernmentService</code> でもある。制度の数を数えるときは、型ではなく状態で絞ってほしい。出典は <code>dct:source</code>、市町村は <code>schema:areaServed</code> で持つ。足りない項目だけを、ここで決めている。</p>
<h2>項目</h2>
<div class="scroll"><table>
<thead><tr><th scope="col">項目</th><th scope="col">CSV の列</th><th scope="col">決まり</th></tr></thead>
<tbody>
{props}
</tbody></table></div>
{chr(10).join(parts)}
"""
    return page(f"語彙 | {TITLE}", body, "",
                '<link rel="alternate" type="text/turtle" href="ns.ttl">\n')


# ---------- 確かめた記録(取り直し、人の再確認、問い合わせ) ----------

def load_records(base: str | Path = "data") -> dict[str, list[dict[str, str]]]:
    """データに添える記録を読む。ファイルが無ければ空。ここでは読むだけで、書き換えない。"""
    base = Path(base)
    return {
        "torinaoshi": schema.read_csv(base / "torinaoshi" / "saishin.csv") if (base / "torinaoshi" / "saishin.csv").exists() else [],
        "saikakunin": schema.read_csv(base / "saikakunin.csv") if (base / "saikakunin.csv").exists() else [],
        "toiawase": schema.read_csv(base / "toiawase.csv") if (base / "toiawase.csv").exists() else [],
    }


def refetch_lines(row: dict[str, str], records: dict) -> list[str]:
    mine = [r for r in records["torinaoshi"] if r["id"] == row["id"]]
    lines = []
    for r in (r for r in mine if r["役割"] == "出典"):
        day = jst_day(r["取得日時"])
        if r["取得"] != "取得":
            why = r["取得"].removeprefix("取得できず(").removesuffix(")")
            lines.append(f"出典: {day} に取り直したが、取得できなかった({why})")
        else:
            lines.append(f"出典: {day} に取り直し、照合は{r['判定']}")
    for r in (r for r in mine if r["役割"] == "出典2"):
        day = jst_day(r["取得日時"])
        if r["取得"] != "取得":
            why = r["取得"].removeprefix("取得できず(").removesuffix(")")
            lines.append(f"第2の出典: {day} に取り直したが、取得できなかった({why})")
        else:
            lines.append(f"第2の出典: {day} に取り直し、照合は{r['判定']}")
    places = [r for r in mine if r["役割"] == "探した場所"]
    if places:
        got = sum(r["取得"] == "取得" for r in places)
        day = max(jst_day(r["取得日時"]) for r in places)
        lines.append(f"探した場所: {day} に{len(places)}ページを取り直した(取得できた {got})。変わった所は記録している")
    return lines


def recheck_line(row: dict[str, str], records: dict) -> str:
    """人の再確認。判定の列に入っているのは、人が出典のページと見比べた結果だけ。"""
    mine = [r for r in records["saikakunin"] if r["id"] == row["id"]]
    if not mine:
        return ""
    c = collections.Counter(r["判定"] for r in mine if r["判定"])
    if not c:
        return f"人は、まだ出典と見比べていない(見比べる項目は {len(mine)})"
    parts = "、".join(f"{k} {c[k]}" for k in ("合っている", "違う", "分からない") if c[k])
    return f"人が出典と見比べた項目は {sum(c.values())} / {len(mine)}({parts})"


def inquiry_lines(row: dict[str, str], records: dict) -> list[str]:
    """問い合わせの記録。載せるのは、日付・方法・担当課と、回答があったかどうかだけ。

    回答の文面は載せない(自由に書いた文で、人の名前が入るかもしれない)。回答の中身は、反映した行の項目と「なしの根拠」に出る。
    突き合わせ: 「反映したid」があればそれだけを見る。無ければ、同じ市町村・同じ種類の行すべてに出す。
    """
    slug = kind_slug(row)
    lines = []
    for r in records["toiawase"]:
        reflected = r.get("反映したid", "").replace(",", " ").replace("|", " ").split()
        if reflected:
            if row["id"] not in reflected:
                continue
        elif not (r["市町村コード"] == row["市町村コード"] and r["種類"].strip() in (row["制度の種類"], slug, KIND_SHORT[slug])):
            continue
        head = f"{r['日付']} {r['担当課']}に{r['方法']}で問い合わせた。"
        if r.get("公開の可否", "").strip().startswith("差し支えあり"):
            lines.append(head + "回答は、データに使っていない(載せることに差し支えがあるとのこと)")
        elif r["回答"].strip():
            lines.append(head + ("回答があり、この1件に反映した" if reflected else "回答があった"))
        else:
            lines.append(head + "回答はまだ無い")
    return lines


# ---------- 書き出し ----------

def write_site(out: str | Path = "_site", csv_path: str = "data/seido.csv") -> dict[str, int]:
    out = Path(out)
    rows = schema.load(csv_path)
    areas = schema.read_csv("data/shichoson.csv")
    nodes = [build.to_node(r) for r in rows]
    if out.exists():
        shutil.rmtree(out)
    (out / "id").mkdir(parents=True)
    (out / "ichiran").mkdir()

    def put(rel: str, text: str) -> None:
        (out / rel).write_text(text, encoding="utf-8")

    put(".nojekyll", "")
    put("style.css", CSS)
    records = load_records(Path(csv_path).parent)
    put("index.html", index_html(rows, areas, records))
    put("ichiran/index.html", ichiran_html(rows))
    (out / "about").mkdir()
    put("about/index.html", about_html(rows, areas, records))
    pupils_path = Path(csv_path).parent / "kumiawase" / "jidou_seito.csv"
    if pupils_path.exists():
        (out / "kumiawase").mkdir()
        put("kumiawase/index.html", kumiawase_html(rows, areas, schema.read_csv(pupils_path)))
        shutil.copyfile(pupils_path, out / "kumiawase.csv")
    put("ns.html", ns_html())
    put("ns.ttl", vocab_turtle())
    put("dataset.ttl", dataset_turtle(rows))
    shutil.copyfile(csv_path, out / "seido.csv")
    put("seido.jsonld", build.build(csv_path))
    put("seido.ttl", nodes_turtle(nodes))
    by_area: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for r in rows:
        by_area[r["市町村コード"]].append(r)
    for row, node in zip(rows, nodes):
        rid = row["id"]
        (out / "id" / rid).mkdir()
        put(f"id/{rid}/index.html", record_html(row, node, by_area[row["市町村コード"]], records))
        put(f"id/{rid}.ttl", nodes_turtle([node]))
        put(f"id/{rid}.jsonld", json.dumps({"@context": build.CONTEXT, **node}, ensure_ascii=False, indent=1) + "\n")
    return {"件数": len(rows), "ファイル": sum(1 for p in out.rglob("*") if p.is_file())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    args = ap.parse_args()
    n = write_site(args.out)
    print(f"{args.out}/ に書き出した。{n['件数']}件、ファイル{n['ファイル']}個")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
