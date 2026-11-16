"""DBpedia Japanese の市町村の URI を、推測で書かずに確かめる。LODチャレンジ2026 のパートナーの資源(http://ja.dbpedia.org)。

名前から URI を作ると、同じ名前の町(ほかの県)を指す恐れがある。そこで、実際に引いて、
その資源が持つ地方公共団体コードがこちらのコードと合うものだけを採る。GitHub Actions で回す。

使い方: python -m futoko_lod.dbpedia --probe 大野城市 40219
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

ENDPOINT = "http://ja.dbpedia.org/sparql"
RESOURCE = "http://ja.dbpedia.org/resource/"
INTERVAL_SEC = 3


def sparql(query: str, timeout: int = 90) -> list[dict[str, str]]:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"})
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        doc = json.loads(res.read().decode("utf-8"))
    time.sleep(INTERVAL_SEC)
    return [{k.lower(): v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


def show(title: str, query: str, limit: int = 40) -> list[dict[str, str]]:
    print(f"\n### {title}\n{query.strip()}")
    try:
        rows = sparql(query)
    except Exception as e:
        print(f"失敗: {type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"{len(rows)} 行")
    for r in rows[:limit]:
        print("  " + " | ".join(f"{k}={v[:100]}" for k, v in r.items()))
    return rows


def probe(name: str, code: str) -> None:
    uri = RESOURCE + name
    show("この名前の資源が持つもののうち、コードらしい値と、型・転送", f"""select ?p ?o where {{ <{uri}> ?p ?o .
  filter(contains(str(?o), "{code}") || ?p = <http://www.w3.org/1999/02/22-rdf-syntax-ns#type>
         || contains(str(?p), "wikiPageRedirects") || contains(str(?p), "wikiPageDisambiguates") || contains(str(?p), "sameAs")) }} limit 60""")
    show("コードの値からさかのぼる(同じコードを持つ資源)", f"""select ?s ?p where {{ ?s ?p ?o . filter(str(?o) in ("{code}", "{code}0", "{code[:2]}{code[2:]}")) }} limit 40""")


CODE_PROP = "http://ja.dbpedia.org/property/コード"  # --probe で、大野城市が 40219 を持つことを確かめた(2026-11-16)
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
REDIRECT = "http://dbpedia.org/ontology/wikiPageRedirects"
CSV_PATH = "data/dbpedia.csv"
CSV_COLUMNS = ["市町村コード", "市町村", "DBpediaのURI", "DBpediaでの名前", "判定", "確かめた日"]


def props(name: str) -> None:
    """資源が持つ性質と値を、全部並べる(使う値を決める前に、何があるかを見る)。"""
    uri = RESOURCE + name
    show(f"{name} が持つ性質と値", f"""select ?p ?o where {{ <{uri}> ?p ?o . filter(!isLiteral(?o) || lang(?o) = "" || lang(?o) = "ja")
  filter(!contains(str(?p), "wikiPageWikiLink")) }} limit 400""", limit=400)


# ---- 隣接する市町村(点7・8) ----
# DBpedia Japanese の「隣接自治体」(Wikipedia の基礎情報から取ったもの)。2022.12.01 のダンプが元(ja.dbpedia.org の版の表示)。
# DBpedia Japanese は CC BY-SA 3.0。このデータ本体(CC BY 4.0)には混ぜず、data/rinsetsu.csv に分けて置く。
NEIGHBOR_PROP = "http://ja.dbpedia.org/property/隣接自治体"
DERIVED = "http://www.w3.org/ns/prov#wasDerivedFrom"
RINSETSU_PATH = "data/rinsetsu.csv"
RINSETSU_COLUMNS = ["市町村コード", "市町村", "隣接する市町村コード", "隣接する市町村", "判定", "元の語", "DBpediaのURI", "Wikipediaの版", "確かめた日"]
PREF = "福岡県"


def neighbors_query(uris: list[str]) -> str:
    values = " ".join(f"<{u}>" for u in uris)
    return f"""select ?s ?o ?olabel ?rev where {{ values ?s {{ {values} }}
  ?s <{NEIGHBOR_PROP}> ?o .
  optional {{ ?o <{LABEL}> ?olabel }}
  optional {{ ?s <{DERIVED}> ?rev }}
}}"""


def split_names(text: str) -> list[str]:
    """「福岡市、春日市、糟屋郡宇美町」のような文字列を、1つずつの名前にする。"""
    import re
    return [t for t in (x.strip() for x in re.split(r"[、,，・/／\s]+", text)) if t]


def match_name(token: str, names: dict[str, str]) -> tuple[str, str, str]:
    """名前1つを、台帳のコードに直す。返すのは (コード, 台帳の名前, 判定)。判定は 県内 / 県外 / 照合できず。

    「糟屋郡宇美町」の郡は外す(郡の後ろが町か村のときだけ。「小郡市」は外さない)。
    「佐賀県鳥栖市」のように福岡県でない県名が付いていれば県外。
    """
    import re
    t = token
    m = re.match(r"^(.+?[都道府県])(.+)$", t)
    if m and m.group(1) != PREF and m.group(2):
        return "", t, "県外"
    if m and m.group(1) == PREF:
        t = m.group(2)
    m = re.match(r"^(.+?郡)(.+[町村])$", t)
    if m:
        t = m.group(2)
    t = re.sub(r"\s*[(（].*[)）]$", "", t)
    by_name = {v: k for k, v in names.items()}
    if t in by_name:
        return by_name[t], t, "県内"
    return "", token, "照合できず"


def neighbors(write: bool) -> int:
    import csv
    import datetime as dt
    from pathlib import Path
    from . import schema
    areas = {a["市町村コード"]: a["市町村"] for a in schema.read_csv("data/shichoson.csv") if a["市町村コード"] != "40000"}
    uris = {r["DBpediaのURI"]: r["市町村コード"] for r in schema.read_csv(CSV_PATH) if r["判定"] == "一致" and r["市町村コード"] in areas}
    rows = show("隣接自治体", neighbors_query(list(uris)), limit=5)
    if not rows:
        print("1行も返らなかった。書き出さない")
        return 1
    date = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    out, seen = [], set()
    for r in rows:
        code = uris[r["s"]]
        raw = r.get("olabel") or r["o"].rsplit("/", 1)[-1] if r["o"].startswith("http") else r["o"]
        for tok in split_names(raw):
            ncode, nname, verdict = match_name(tok, areas)
            key = (code, ncode or nname)
            if key in seen or ncode == code:
                continue
            seen.add(key)
            out.append({"市町村コード": code, "市町村": areas[code], "隣接する市町村コード": ncode, "隣接する市町村": nname,
                        "判定": verdict, "元の語": tok, "DBpediaのURI": r["s"], "Wikipediaの版": r.get("rev", ""), "確かめた日": date})
    out.sort(key=lambda x: (x["市町村コード"], x["隣接する市町村コード"] or "9", x["隣接する市町村"]))
    inner = {(x["市町村コード"], x["隣接する市町村コード"]) for x in out if x["判定"] == "県内"}
    asym = sorted((a, b) for a, b in inner if (b, a) not in inner)
    # 使うのは、両方の市町村が互いを隣と書いている組だけ。片方だけの組は、記録には残すが使わない
    for x in out:
        if x["判定"] == "県内":
            pair = (x["市町村コード"], x["隣接する市町村コード"])
            x["判定"] = "県内(両方にある)" if pair[::-1] in inner else "県内(片方だけ)"
    missing = sorted(set(areas) - {x["市町村コード"] for x in out})
    both = sum(x["判定"] == "県内(両方にある)" for x in out)
    print(f"\n県内の組 {len(inner)}(両方にある {both}、使う組は {both // 2})、県外 {sum(x['判定'] == '県外' for x in out)}、照合できず {sum(x['判定'] == '照合できず' for x in out)}")
    print(f"隣接自治体が返らなかった市町村 {len(missing)}: {' '.join(areas[c] for c in missing)}")
    print(f"片方にしか無い組(A の隣に B があるが、B の隣に A が無い) {len(asym)}: " + " ".join(f"{areas[a]}→{areas[b]}" for a, b in asym))
    for x in out:
        if x["判定"] == "照合できず":
            print(f"  照合できず: {x['市町村']} の「{x['元の語']}」")
    if write:
        Path(RINSETSU_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(RINSETSU_PATH, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RINSETSU_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(out)
        print(f"{RINSETSU_PATH} を書いた")
    return 0


def verify_query(codes: list[str]) -> str:
    """地方公共団体コードがこちらのコードと合う資源を引く。名前からは URI を作らない。"""
    inlist = ", ".join(f'"{c}"' for c in codes)
    return f"""select ?s ?c ?label ?redirect where {{
  ?s <{CODE_PROP}> ?c . filter(str(?c) in ({inlist}))
  optional {{ ?s <{LABEL}> ?label }}
  optional {{ ?s <{REDIRECT}> ?redirect }}
}}"""


def judge(areas: dict[str, str], rows: list[dict[str, str]], date: str) -> list[dict[str, str]]:
    """コードごとに、採ってよい URI が1つに決まるかを判定する。

    採るのは「一致」だけ: そのコードを持つ資源(転送でないもの)がちょうど1つで、名前がこちらの名前で始まる
    (「川崎町 (福岡県)」のような、かっこ付きの名前を許す)。
    """
    by_code: dict[str, dict[str, str]] = {}
    for r in rows:
        if r.get("redirect"):
            continue
        by_code.setdefault(r["c"].strip(), {})[r["s"]] = r.get("label", "")
    out = []
    for code, name in areas.items():
        found = by_code.get(code, {})
        row = {"市町村コード": code, "市町村": name, "DBpediaのURI": "", "DBpediaでの名前": "", "判定": "", "確かめた日": date}
        if not found:
            row["判定"] = "このコードを持つ資源が返らなかった"
        elif len(found) > 1:
            row["判定"] = "同じコードを持つ資源が複数(" + " ".join(sorted(found)) + ")"
        else:
            (uri, label), = found.items()
            row["DBpediaでの名前"] = label
            if label == name or label.startswith(name + " ("):
                row["DBpediaのURI"], row["判定"] = uri, "一致"
            else:
                row["判定"] = f"名前が違う({uri})"
        out.append(row)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs=2, metavar=("名前", "コード"))
    ap.add_argument("--verify", nargs="?", const="show", choices=["show", "write"])
    ap.add_argument("--props", metavar="名前")
    ap.add_argument("--neighbors", nargs="?", const="show", choices=["show", "write"])
    args = ap.parse_args()
    if args.probe:
        probe(*args.probe)
    if args.props:
        props(args.props)
    if args.neighbors:
        return neighbors(args.neighbors == "write")
    if args.verify:
        import csv
        import datetime as dt
        from pathlib import Path
        from . import schema
        areas = {a["市町村コード"]: a["市町村"] for a in schema.read_csv("data/shichoson.csv")}
        rows = show("コードが合う資源", verify_query(list(areas)), limit=5)
        if not rows:
            print("1行も返らなかった。書き出さない")
            return 1
        out = judge(areas, rows, dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat())
        for r in out:
            if r["判定"] != "一致":
                print("| " + " | ".join(r[c] for c in CSV_COLUMNS) + " |")
        print(f"一致 {sum(r['判定'] == '一致' for r in out)} / {len(out)}")
        if args.verify == "write":
            Path(CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
                w.writeheader()
                w.writerows(out)
            print(f"{CSV_PATH} を書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
