"""組み合わせの例。このデータを、e-Stat 統計LOD の統計と、標準地域コードの URI で並べる。

e-Stat 統計LOD の SPARQL エンドポイントの使い方は、公式の説明による:
  https://data.e-stat.go.jp/lodw/index.php/en/sparqlendpoint/api
  (http://data.e-stat.go.jp/lod/sparql/alldata/query に、query という名前で問い合わせを POST する)
項目の名前(述語)は推測で書かず、--probe で実際に引いて確かめてから使う。GitHub Actions で回す。

使い方: python -m futoko_lod.kumiawase --probe [コード]
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request

from .fetch import USER_AGENT

ENDPOINT = "http://data.e-stat.go.jp/lod/sparql/alldata/query"
SAC = "http://data.e-stat.go.jp/lod/sac/C"
INTERVAL_SEC = 3


def sparql(query: str, timeout: int = 90) -> list[dict[str, str]]:
    data = urllib.parse.urlencode({"query": query}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=data, headers={
        "User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        doc = json.loads(res.read().decode("utf-8"))
    time.sleep(INTERVAL_SEC)
    # 変数の名前は大文字で返ってくることがある(2026-11-16 に確かめた)。小文字にそろえる
    return [{k.lower(): v["value"] for k, v in b.items()} for b in doc["results"]["bindings"]]


def show(title: str, query: str) -> list[dict[str, str]]:
    print(f"\n### {title}\n```\n{query.strip()}\n```")
    try:
        rows = sparql(query)
    except Exception as e:  # 届かない、時間切れ、書き方の誤り
        print(f"失敗: {type(e).__name__}: {str(e)[:200]}")
        return []
    print(f"{len(rows)} 行")
    for r in rows[:12]:
        print("  " + " | ".join(f"{k}={v[:110]}" for k, v in r.items()))
    return rows


def probe(code: str) -> None:
    area = SAC + code
    rows = show("時期なしのコードが持つもの", f"select ?p ?o where {{ <{area}> ?p ?o }} limit 60")
    dated = [r["o"] for r in rows if "/lod/sac/C" in r["o"] and r["o"] != area]
    for uri in [area] + dated[-2:]:
        ps = show(f"{uri} を指している述語", f"select ?p (count(?s) as ?n) where {{ ?s ?p <{uri}> }} group by ?p order by desc(?n) limit 20")
        for p in [r["p"] for r in ps if "Area" in r["p"] or "area" in r["p"]][:1]:
            show("それを指す観測値が属するデータセット",
                 f"select ?ds (count(?s) as ?n) where {{ ?s <{p}> <{uri}> ; <http://purl.org/linked-data/cube#dataSet> ?ds }} group by ?ds order by desc(?n) limit 40")
            obs = show("観測値の見本", f"select ?s where {{ ?s <{p}> <{uri}> }} limit 2")
            for o in obs[:2]:
                show("見本の中身", f"select ?p ?o where {{ <{o['s']}> ?p ?o }} limit 40")


REF_AREA = "http://purl.org/linked-data/sdmx/2009/dimension#refArea"
DATASET = "http://purl.org/linked-data/cube#dataSet"
SSDS = "http://data.e-stat.go.jp/lod/dataset/g00200502/"  # 社会・人口統計体系(市区町村)。--probe で見つけた
INDICATOR = "http://data.e-stat.go.jp/lod/ontology/g00200502/dimension/indicator"
TIME = "http://data.e-stat.go.jp/lod/ontology/crossDomain/dimension/timePeriod"


def indicators(code: str, part: str) -> None:
    """社会・人口統計体系の1つの分野(am=人口、em=教育 など)に、その市町村のどんな指標が、何年まであるか。"""
    q = f"""select ?ind ?label (min(?t) as ?from) (max(?t) as ?to) (count(?s) as ?n) where {{
  <{SAC}{code}> <http://data.e-stat.go.jp/lod/terms/sacs#latestCode> ?area .
  ?s <{REF_AREA}> ?area ; <{DATASET}> <{SSDS}d00200502{part}> ; <{INDICATOR}> ?ind ; <{TIME}> ?t .
  optional {{ ?ind <http://www.w3.org/2000/01/rdf-schema#label> ?label . filter(lang(?label) = "ja") }}
}} group by ?ind ?label order by ?ind limit 200"""
    show(f"分野 {part} の指標(最新のコードの分)", q)


OBS = "http://purl.org/linked-data/sdmx/2009/measure#obsValue"
SACS = "http://data.e-stat.go.jp/lod/terms/sacs#"
CODE = "http://data.e-stat.go.jp/lod/ontology/g00200502/code/indicator-"
PUPILS = {"E2501": "小学校児童数", "E3501": "中学校生徒数"}  # --indicators で、名前と年(2011〜2015)を確かめた


MIN_YEAR = "2014"  # 行が多いと1000行で切られる(2026-11-16 に確かめた)ので、新しい年だけを引く
CSV_PATH = "data/kumiawase/jidou_seito.csv"
CSV_COLUMNS = ["標準地域コードのURI", "市町村コード", "市町村", "小学校児童数", "小学校児童数の年", "中学校生徒数", "中学校生徒数の年",
               "統計LODの地域コード", "備考", "取得日"]


def area_uris(jsonld_path: str = "data/seido.jsonld", codes: set[str] | None = None) -> dict[str, str]:
    """公開している JSON-LD の schema:areaServed から、市町村の URI を集める。{URI: 名前}

    つなぐ手がかりは、この URI。市町村の台帳(CSV)のコードからは作らない。
    """
    with open(jsonld_path, encoding="utf-8") as f:
        doc = json.load(f)
    out: dict[str, str] = {}
    for node in doc["@graph"]:
        area = node["areaServed"]
        if codes is None or area["identifier"] in codes:
            out[area["@id"]] = area["name"]
    return out


def _observations(inds: str) -> str:
    return (f"?s <{REF_AREA}> ?area ; <{DATASET}> <{SSDS}d00200502em> ; <{INDICATOR}> ?ind ; <{TIME}> ?t ; <{OBS}> ?v .\n"
            f'  filter(?ind in ({inds}) && str(?t) >= "{MIN_YEAR}")')


def pupils_query(uris: list[str]) -> str:
    """時期なしの URI から、同じコードの時期つきのコード(最新と過去)を辿って、観測値を引く。"""
    values = " ".join(f"<{u}>" for u in uris)
    inds = ", ".join(f"<{CODE}{k}>" for k in PUPILS)
    return f"""select ?plain ?area ?ind ?t ?v where {{
  values ?plain {{ {values} }}
  {{ ?plain <{SACS}latestCode> ?area }} union {{ ?plain <{SACS}pastCode> ?area }}
  {_observations(inds)}
}}"""


def predecessor_query(uris: list[str]) -> str:
    """いまのコードに観測値が無い市町村について、その市町村になる前の地域の観測値を引く。

    那珂川市(C40231-20181001)は、観測値が1つも無かった。前の那珂川町は、最後の時期つきのコード(C40305-20181001)が
    sacs:succeedingMunicipality でいまのコードを指し、観測値は同じ番号の別の時期つきのコード(C40305-19700401)に
    付いていた(2026-11-16 に確かめた)。そこで、前の地域の番号に戻ってから、その時期つきのコードを全部見る。合併で前の地域が複数あるときは、ここで引けても使わない(latest_pupils の側で止める)。
    """
    values = " ".join(f"<{u}>" for u in uris)
    inds = ", ".join(f"<{CODE}{k}>" for k in PUPILS)
    return f"""select ?plain ?area ?ind ?t ?v where {{
  values ?plain {{ {values} }}
  ?plain <{SACS}latestCode> ?now . ?old <{SACS}succeedingMunicipality> ?now .
  {{ ?oldplain <{SACS}pastCode> ?old }} union {{ ?oldplain <{SACS}latestCode> ?old }}
  {{ ?oldplain <{SACS}pastCode> ?area }} union {{ ?oldplain <{SACS}latestCode> ?area }}
  {_observations(inds)}
}}"""


def latest_pupils(rows: list[dict[str, str]], predecessor_rows: list[dict[str, str]] | None = None) -> dict[str, dict]:
    """URI ごと・指標ごとに、いちばん新しい年の値を選ぶ。{URI: {指標: (年, 人数, 時期つきのコード), "備考": 文}}

    同じ年に時期つきのコードが複数あれば、新しいコード(日付の大きいほう)を取る。
    いまのコードに値が無いときだけ、前の地域の値を使う。前の地域が2つ以上あれば、足さずに空のままにする。
    """
    out: dict[str, dict] = {}

    def pick(target: dict, r: dict[str, str]) -> None:
        ind = r["ind"].rsplit("-", 1)[1]
        area = r["area"].rsplit("/", 1)[1]
        if ind not in PUPILS:
            return
        key = (r["t"][:4], area)
        if ind not in target or key > (target[ind][0], target[ind][2]):
            target[ind] = (r["t"][:4], int(float(r["v"])), area)

    for r in rows:
        pick(out.setdefault(r["plain"], {}), r)
    by_plain: dict[str, list[dict[str, str]]] = {}
    for r in predecessor_rows or []:
        if r["plain"] not in out:
            by_plain.setdefault(r["plain"], []).append(r)
    for plain, rs in by_plain.items():
        codes = sorted({r["area"].rsplit("/", 1)[1].split("-")[0] for r in rs})
        if len(codes) > 1:
            out[plain] = {"備考": "前の地域が複数ある(" + " ".join(codes) + ")。足していない"}
            continue
        target: dict = {}
        for r in rs:
            pick(target, r)
        target["備考"] = f"いまのコードには値が無い。その前の地域({codes[0]})の値"
        out[plain] = target
    return out


def table(uris: dict[str, str], got: dict, date: str) -> list[dict[str, str]]:
    out = []
    for uri, name in uris.items():
        g = got.get(uri, {})
        used = sorted({v[2] for k, v in g.items() if k in PUPILS})
        out.append({
            "標準地域コードのURI": uri, "市町村コード": uri.rsplit("/C", 1)[1], "市町村": name,
            "小学校児童数": str(g["E2501"][1]) if "E2501" in g else "", "小学校児童数の年": g["E2501"][0] if "E2501" in g else "",
            "中学校生徒数": str(g["E3501"][1]) if "E3501" in g else "", "中学校生徒数の年": g["E3501"][0] if "E3501" in g else "",
            "統計LODの地域コード": " ".join(used),
            "備考": g.get("備考", "" if used else "この問い合わせでは返らなかった(統計LOD に無いとは確かめていない)"),
            "取得日": date,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="?", const="40219")
    ap.add_argument("--indicators", nargs="+", metavar="コード 分野...")
    ap.add_argument("--pupils", nargs="?", const="show", choices=["show", "write"])
    args = ap.parse_args()
    if args.probe:
        probe(args.probe)
    if args.pupils:
        import csv
        import datetime as dt
        from pathlib import Path
        from . import schema
        metro = {a["市町村コード"] for a in schema.read_csv("data/shichoson.csv") if a["福岡都市圏"] == "○"}
        uris = area_uris(codes=metro)
        rows = show("17市町の児童数・生徒数(公開データの areaServed の URI から)", pupils_query(list(uris)))
        if not rows or len(rows) >= 1000:
            print(f"行の数が {len(rows)}。届かなかったか、切られた恐れがある。書き出さない")
            return 1
        missing = [u for u in uris if u not in {r["plain"] for r in rows}]
        before = show("値が返らなかった市町村の、前の地域", predecessor_query(missing)) if missing else []
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()  # 日本時間
        out = table(uris, latest_pupils(rows, before), today)
        for r in out:
            print("| " + " | ".join(r[c] for c in CSV_COLUMNS[1:]) + " |")
        if args.pupils == "write":
            Path(CSV_PATH).parent.mkdir(parents=True, exist_ok=True)
            with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
                w.writeheader()
                w.writerows(out)
            print(f"{CSV_PATH} を書いた")
    if args.indicators:
        for part in args.indicators[1:]:
            indicators(args.indicators[0], part)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
