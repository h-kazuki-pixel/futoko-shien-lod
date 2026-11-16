"""SHACL の形(shapes.ttl)。公開する RDF が守る決まりを、ほかの人の道具でも確かめられる形で書く。

schema.py の検査は CSV の行を見る。こちらは公開する RDF(seido.ttl と dataset.ttl)を見る。
書くのは SHACL Core の範囲だけ(SPARQL を使う決まりは書かない)。どの SHACL の道具でも同じ結果になるように。
Core で書けない決まり(id と市町村コードの前半が合うこと、市町村の台帳と名前が合うこと、備考の数字の照合など)は、
schema.py と collate.py に残る。どれを書けて、どれを書けないかは docs/公開の形.md の「形(SHACL)」。

値の一覧(種類・状態・補助の形・確認方法、公式サイトのドメイン)は、schema.py と同じものから作る。手で二重に持たない。

使い方:
  python -m futoko_lod.shapes                 data/shapes.ttl を作り直す
  python -m futoko_lod.shapes --check         data/shapes.ttl が最新か確かめる
  python -m futoko_lod.shapes --validate _site 公開する一式(seido.ttl、dataset.ttl)を形で検査する。1つでも外れれば失敗
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from . import build, schema

BASE = build.BASE
SH_NS = BASE + "shapes#"
SHAPES_IRI = BASE + "shapes"
OUT = Path("data/shapes.ttl")

REFETCH_ROLES = ("出典", "出典2", "探した場所")
COLLATION_RESULTS = ("一致", "不一致")


def _str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ja(text: str) -> str:
    return _str(text) + "@ja"


def _list(items: list[str]) -> str:
    return "( " + " ".join(items) + " )"


_XPATH_META = set("\\.?*+()[]{}|^$-")


def xpath_escape(text: str) -> str:
    """SHACL の sh:pattern(XPath の正規表現)で通る逃がし方。Python の re.escape は & ~ # などにも \\ を付け、
    それは XPath では誤りになる(ほかの道具で形を読めなくなる)ので使わない。"""
    return "".join("\\" + ch if ch in _XPATH_META else ch for ch in text)


def official_pattern(extra_domains: frozenset[str] | None = None) -> str:
    """公式サイトの URL の正規表現(schema.is_official_url と同じ決まり)。大文字小文字は区別しない(flags "i")。
    URL の中の「..」の区切りは、ここでは見ない(UNSAFE_URL_PATTERN を sh:not で使う)。"""
    if extra_domains is None:
        extra_domains = schema.load_extra_domains()
    port = ""  # ポートを書いた URL は通さない(schema.is_official_url と同じ)
    host_end = r"([/?#]|$)"
    alts = [
        r"([a-z0-9-]+\.)*[a-z0-9-]+\.(lg|go)\.jp" + host_end,
        r"([a-z0-9-]+\.)*(pref|city|town|vill)\.([a-z0-9-]+\.)?fukuoka\.jp" + host_end,
    ]
    for d in sorted(extra_domains):
        dhost, drest = schema._split_extra(d)
        if drest:  # 業者のサイトの例規集など。その市町村の場所(ホスト+パス)の前方一致だけ
            alts.append(xpath_escape(dhost) + port + xpath_escape(drest) + ("(&|#|$)" if "?" in drest else ""))
        else:
            alts.append(r"([a-z0-9-]+\.)*" + xpath_escape(d) + host_end)
    return "^https?://(" + "|".join(alts) + ")"


# 公式の場所の外を指しうる書き方。schema.is_official_url と同じもの
UNSAFE_URL_PATTERN = schema.UNSAFE_URL_PATTERN


def shapes_turtle(extra_domains: frozenset[str] | None = None) -> str:
    fsl = lambda prefix, slug: f"fsl:{prefix}-{slug}"  # noqa: E731
    kinds = [fsl("kind", s) for s in schema.KINDS]
    statuses = {label: fsl("status", slug) for label, slug in schema.STATUSES.items()}
    forms = [fsl("form", s) for s in schema.FORMS.values()]
    methods = {label: fsl("method", slug) for label, slug in schema.METHODS.items()}
    pref_only = [fsl("kind", s) for s in schema.PREF_ONLY_KINDS]
    other_kinds = [k for k in kinds if k not in pref_only]
    guideline_states = [s for s in schema.GUIDELINE_STATES if s]
    supports = []
    for key in schema.SOURCE2_FIELDS.values():
        term = build.CONTEXT[key]
        supports.append(term["@id"] if isinstance(term, dict) else term)
    supports_and = "\n        ".join(
        f'[ sh:or ( [ sh:not [ sh:path ( fsl:additionalSource fsl:supports ) ; sh:hasValue {p} ] ] [ sh:path {p} ; sh:minCount 1 ] ) ]'
        for p in supports if p != "fsl:kind")
    url = _str(official_pattern(extra_domains)) + f" ; sh:flags \"i\" ; sh:not [ sh:pattern {_str(UNSAFE_URL_PATTERN)} ; sh:flags \"i\" ]"
    id_pattern = _str("^40[0-9]{3}-(" + "|".join(re.escape(s) for s in schema.KINDS) + ")(-[0-9]+)?$")
    st = lambda *labels: _list([statuses[x] for x in labels])  # noqa: E731
    no_content = ["schema:name", "fsl:amountText", "fsl:amountMaxYen", "fsl:subsidyRate", "fsl:startText"]

    def none_of(paths: list[str], message: str) -> str:
        return " ,\n".join(f"        [ sh:path {p} ; sh:maxCount 0 ; sh:message {_ja(message)} ]" for p in paths)

    def lang_text(path: str, name: str, max_len: int | None = None, required: bool = False, single: bool = True) -> str:
        parts = [f"sh:path {path}", f"sh:name {_ja(name)}", "sh:datatype rdf:langString", 'sh:languageIn ( "ja" )']
        if required:
            parts.append("sh:minCount 1")
        if single:
            parts.append("sh:maxCount 1")
        if max_len:
            parts.append(f"sh:maxLength {max_len}")
        return "[ " + " ; ".join(parts) + " ]"

    return f"""@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix schema: <https://schema.org/> .
@prefix fsl: <{BASE}ns#> .
@prefix fslsh: <{SH_NS}> .

# このファイルは futoko_lod/shapes.py が作る。手で直さない。

<{SHAPES_IRI}> a owl:Ontology ;
    rdfs:label {_ja("不登校支援制度LOD の形(SHACL)")} ;
    rdfs:comment {_ja("公開する RDF(seido.ttl、dataset.ttl)が守る決まり。SHACL Core だけで書いている。公開のたびに、この形で検査してから公開する。")} ;
    dct:license <https://creativecommons.org/licenses/by/4.0/> ;
    rdfs:seeAlso <{BASE}ns> .

# ---------- 確かめた記録(すべての状態に共通) ----------

fslsh:RecordShape a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("確かめた記録")} ;
    rdfs:comment {_ja("どの状態の記録にも要る項目と、値の形。")} ;
    sh:nodeKind sh:IRI ;
    sh:pattern {_str("^" + re.escape(BASE) + "id/[0-9a-z-]+$")} ;
    sh:property
        [ sh:path schema:identifier ; sh:name {_ja("id")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ;
          sh:pattern {id_pattern} ;
          sh:message {_ja("id は「市町村コード-種類」(同じ種類が複数あれば -2 など)")} ] ,
        [ sh:path schema:areaServed ; sh:name {_ja("市町村")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:node fslsh:AreaShape ] ,
        [ sh:path fsl:kind ; sh:name {_ja("制度の種類")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {_list(kinds)} ] ,
        [ sh:path fsl:status ; sh:name {_ja("状態")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {_list(list(statuses.values()))} ;
          sh:message {_ja("状態は あり / 予定 / なし / 確認できず の1つ")} ] ,
        [ sh:path fsl:dateChecked ; sh:name {_ja("確認日")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:date ] ,
        [ sh:path fsl:checkMethod ; sh:name {_ja("確認方法")} ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {_list(list(methods.values()))} ] ,
        [ sh:path fsl:paymentForm ; sh:name {_ja("補助の形")} ; sh:maxCount 1 ; sh:in {_list(forms)} ] ,
        [ sh:path schema:name ; sh:name {_ja("制度名")} ; sh:maxCount 1 ; sh:datatype rdf:langString ; sh:languageIn ( "ja" ) ] ,
        {lang_text("fsl:eligibility", "対象", schema.MAX_TEXT)} ,
        {lang_text("fsl:amountText", "金額", schema.MAX_TEXT)} ,
        {lang_text("fsl:startText", "開始", schema.MAX_TEXT)} ,
        {lang_text("fsl:note", "備考", schema.MAX_TEXT)} ,
        {lang_text("fsl:sourceName", "出典名")} ,
        {lang_text("fsl:noneBasis", "なしの根拠")} ,
        [ sh:path fsl:amountMaxYen ; sh:name {_ja("上限額_円")} ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 1 ] ,
        [ sh:path fsl:subsidyRate ; sh:name {_ja("補助率")} ; sh:maxCount 1 ; sh:datatype xsd:string ;
          sh:pattern "^[1-9][0-9]*/[1-9][0-9]*$" ; sh:message {_ja("補助率は 1/2 の形")} ] ,
        [ sh:path fsl:basisPhrase ; sh:name {_ja("根拠の箇所")} ; sh:maxCount 1 ; sh:datatype rdf:langString ;
          sh:maxLength {schema.MAX_BASIS} ; sh:message {_ja(f"根拠の箇所は {schema.MAX_BASIS}字まで(公式ページの文章を写さない)")} ] ,
        [ sh:path dct:source ; sh:name {_ja("出典URL")} ; sh:maxCount 1 ; sh:nodeKind sh:IRI ;
          sh:pattern {url} ; sh:message {_ja("出典は市町村・県・国の公式サイトだけ")} ] ,
        [ sh:path fsl:guideline ; sh:name {_ja("要綱URL")} ; sh:maxCount 1 ; sh:nodeKind sh:IRI ;
          sh:pattern {url} ; sh:message {_ja("要綱は市町村・県・国の公式サイトだけ")} ] ,
        [ sh:path fsl:searchedAt ; sh:name {_ja("探した場所")} ; sh:nodeKind sh:IRI ;
          sh:pattern {url} ; sh:message {_ja("探した場所は公式サイトの URL")} ] ,
        [ sh:path fsl:guidelineState ; sh:name {_ja("要綱の状況")} ; sh:maxCount 1 ; sh:in {_list([_ja(s) for s in sorted(guideline_states)])} ] ,
        [ sh:path fsl:additionalSource ; sh:name {_ja("第2の出典")} ; sh:maxCount 1 ; sh:node fslsh:AdditionalSourceShape ] ,
        [ sh:path fsl:checkActivity ; sh:name {_ja("確かめた記録")} ; sh:class prov:Activity ] .

# ---------- 状態ごとの決まり(この作品の核。「なし」と「確認できず」を混ぜない) ----------

fslsh:AriYoteiRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("あり・予定の決まり")} ;
    rdfs:comment {_ja("「あり」「予定」は、出典・根拠の箇所・制度名がそろい、schema:GovernmentService でもある。利用料の補助は、補助の形(毎月か1回きりか)を必ず持つ。")} ;
    sh:message {_ja("「あり」「予定」なのに、出典・根拠の箇所・制度名・型・補助の形のどれかが足りない")} ;
    sh:or (
        [ sh:path fsl:status ; sh:in {st("なし", "確認できず")} ]
        [ sh:class schema:GovernmentService ;
          sh:property
            [ sh:path dct:source ; sh:minCount 1 ] ,
            [ sh:path fsl:basisPhrase ; sh:minCount 1 ] ,
            [ sh:path schema:name ; sh:minCount 1 ] ;
          sh:or (
            [ sh:path fsl:kind ; sh:in {_list([k for k in kinds if k != fsl("kind", "fs-hojo")])} ]
            [ sh:path fsl:paymentForm ; sh:minCount 1 ]
          ) ]
    ) .

fslsh:NashiRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("なしの決まり")} ;
    rdfs:comment {_ja("「なし」は、なしの根拠を持つ。制度の中身(制度名・金額・開始など)と第2の出典は持たない。制度ではないので GovernmentService ではない。機械の読み取りで「なし」とするなら、無いと分かる公式の資料(出典)と根拠の箇所が要る。")} ;
    sh:message {_ja("「なし」の決まりに合わない(なしの根拠が無い、制度の中身がある、など)")} ;
    sh:or (
        [ sh:path fsl:status ; sh:in {st("あり", "予定", "確認できず")} ]
        [ sh:not [ sh:class schema:GovernmentService ] ;
          sh:property
            [ sh:path fsl:noneBasis ; sh:minCount 1 ] ,
            [ sh:path fsl:additionalSource ; sh:maxCount 0 ] ,
{none_of(no_content, "「なし」なのに制度の中身がある")} ;
          sh:or (
            [ sh:path fsl:checkMethod ; sh:in {_list([m for label, m in methods.items() if label != "機械の読み取り"])} ]
            [ sh:property [ sh:path dct:source ; sh:minCount 1 ] , [ sh:path fsl:basisPhrase ; sh:minCount 1 ] ]
          ) ]
    ) .

fslsh:KakuninDekizuRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("確認できずの決まり")} ;
    rdfs:comment {_ja("「確認できず」は、探した場所を1つ以上持つ。出典・根拠の箇所・制度の中身・第2の出典は持たない(見つかっていないので)。GovernmentService ではない。")} ;
    sh:message {_ja("「確認できず」の決まりに合わない(探した場所が無い、出典や制度の中身がある、など)")} ;
    sh:or (
        [ sh:path fsl:status ; sh:in {st("あり", "予定", "なし")} ]
        [ sh:not [ sh:class schema:GovernmentService ] ;
          sh:property
            [ sh:path fsl:searchedAt ; sh:minCount 1 ] ,
            [ sh:path fsl:additionalSource ; sh:maxCount 0 ] ,
{none_of(no_content + ["dct:source", "fsl:basisPhrase"], "「確認できず」なのに出典や制度の中身がある")} ]
    ) .

fslsh:PrefOnlyKindRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("設置者向けの補助は県の行だけ")} ;
    rdfs:comment {_ja("施設の設置者向けの補助を、保護者向けの制度と混ぜない。この種類は県(40000)の記録にだけ使う。")} ;
    sh:message {_ja("設置者向けの補助が、県でない記録に付いている")} ;
    sh:or (
        [ sh:path fsl:kind ; sh:in {_list(other_kinds)} ]
        [ sh:path schema:areaServed ; sh:hasValue <{build.SAC}40000> ]
    ) .

fslsh:GuidelineRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("要綱の状況と要綱URL")} ;
    rdfs:comment {_ja("要綱の状況が「取得済み」のときだけ、要綱URL を持つ。")} ;
    sh:message {_ja("要綱の状況が「取得済み」なのに要綱URL が無い、または「取得済み」でないのに要綱URL がある")} ;
    sh:xone (
        [ sh:property [ sh:path fsl:guidelineState ; sh:hasValue {_ja("取得済み")} ] , [ sh:path fsl:guideline ; sh:minCount 1 ] ]
        [ sh:property [ sh:path fsl:guidelineState ; sh:in {_list([_ja(s) for s in sorted(guideline_states) if s != "取得済み"])} ] ,
                      [ sh:path fsl:guideline ; sh:maxCount 0 ] ]
    ) .

fslsh:AdditionalSourceRule a sh:NodeShape ;
    sh:targetClass fsl:Record ;
    rdfs:label {_ja("第2の出典と記録の項目")} ;
    rdfs:comment {_ja("第2の出典は、出典と同じ URL にしない。第2の出典で裏付けるとした項目は、記録の側で空にしない。")} ;
    sh:message {_ja("第2の出典で裏付けるとした項目が、記録の側で空になっている")} ;
    sh:property
        [ sh:path ( fsl:additionalSource dct:source ) ; sh:disjoint dct:source ;
          sh:message {_ja("第2の出典が、出典と同じ URL になっている")} ] ;
    sh:and (
        {supports_and}
    ) .

# ---------- 市町村 ----------

fslsh:AreaShape a sh:NodeShape ;
    rdfs:label {_ja("市町村")} ;
    rdfs:comment {_ja("e-Stat 統計LOD の標準地域コード(福岡県)。名前とコードを持つ。DBpedia Japanese の資源につなぐのは、コードが合うと確かめたものだけ。")} ;
    sh:nodeKind sh:IRI ;
    sh:pattern {_str("^" + re.escape(build.SAC) + "40[0-9]{3}$")} ;
    sh:class schema:AdministrativeArea ;
    sh:property
        [ sh:path schema:name ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ; sh:languageIn ( "ja" ) ] ,
        [ sh:path schema:identifier ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:string ; sh:pattern "^40[0-9]{{3}}$" ] ,
        [ sh:path schema:sameAs ; sh:maxCount 1 ; sh:nodeKind sh:IRI ; sh:pattern "^http://ja\\\\.dbpedia\\\\.org/resource/" ] .

# ---------- 第2の出典 ----------

fslsh:AdditionalSourceShape a sh:NodeShape ;
    rdfs:label {_ja("第2の出典")} ;
    rdfs:comment {_ja("項目の根拠が別の資料にあるときの、その資料。URL・呼び名・資料にある短い語句・裏付ける項目がそろう。")} ;
    sh:nodeKind sh:IRI ;
    sh:pattern {_str("^" + re.escape(BASE) + "id/[0-9a-z-]+#source2$")} ;
    sh:class fsl:AdditionalSource ;
    sh:property
        [ sh:path dct:source ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ; sh:pattern {url} ;
          sh:message {_ja("第2の出典も公式サイトだけ")} ] ,
        [ sh:path fsl:sourceName ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ] ,
        [ sh:path fsl:basisPhrase ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ; sh:maxLength {schema.MAX_BASIS} ] ,
        [ sh:path fsl:supports ; sh:minCount 1 ; sh:in {_list(supports)} ] .

# ---------- 確かめた記録(取り直し・人の再確認・問い合わせ) ----------

fslsh:RefetchShape a sh:NodeShape ;
    sh:targetClass fsl:Refetch ;
    rdfs:label {_ja("取り直し")} ;
    rdfs:comment {_ja("どのページを、どの役割で取りに行き、取得できたか。照合の結果は、取得できたときだけ持つ。")} ;
    sh:class prov:Activity ;
    sh:property
        [ sh:path fsl:role ; sh:minCount 1 ; sh:maxCount 1 ; sh:in {_list([_ja(r) for r in REFETCH_ROLES])} ] ,
        [ sh:path prov:used ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ,
        [ sh:path fsl:fetchResult ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ] ,
        [ sh:path prov:endedAtTime ; sh:maxCount 1 ; sh:datatype xsd:dateTime ] ,
        [ sh:path fsl:collationResult ; sh:maxCount 1 ; sh:in {_list([_ja(r) for r in COLLATION_RESULTS])} ] .

fslsh:RefetchCollationRule a sh:NodeShape ;
    sh:targetClass fsl:Refetch ;
    rdfs:label {_ja("照合の結果は取得できたときだけ")} ;
    rdfs:comment {_ja("取り直しで取得できなかったページには、照合の結果を付けない。")} ;
    sh:message {_ja("取り直しで、取得できなかったのに照合の結果がある")} ;
    sh:or (
        [ sh:path fsl:collationResult ; sh:maxCount 0 ]
        [ sh:path fsl:fetchResult ; sh:hasValue {_ja("取得")} ]
    ) .

fslsh:HumanReviewShape a sh:NodeShape ;
    sh:targetClass fsl:HumanReview ;
    rdfs:label {_ja("人の再確認")} ;
    rdfs:comment {_ja("見比べる項目の数と、見比べた・合っている・違う・分からないの数。見比べた数は見比べる数を超えない。合っている・違う・分からないは、それぞれが見比べた数を超えない(足した数が合うかは、形では見ない)。")} ;
    sh:class prov:Activity ;
    sh:property
        [ sh:path fsl:itemsTotal ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 1 ] ,
        [ sh:path fsl:itemsChecked ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ;
          sh:lessThanOrEquals fsl:itemsTotal ; sh:message {_ja("見比べた項目の数が、見比べる項目の数を超えている")} ] ,
        [ sh:path fsl:itemsMatched ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ;
          sh:lessThanOrEquals fsl:itemsChecked ; sh:message {_ja("合っている・違う・分からないの数のどれかが、それだけで見比べた数を超えている")} ] ,
        [ sh:path fsl:itemsWrong ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ;
          sh:lessThanOrEquals fsl:itemsChecked ; sh:message {_ja("合っている・違う・分からないの数のどれかが、それだけで見比べた数を超えている")} ] ,
        [ sh:path fsl:itemsUnsure ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:integer ; sh:minInclusive 0 ;
          sh:lessThanOrEquals fsl:itemsChecked ; sh:message {_ja("合っている・違う・分からないの数のどれかが、それだけで見比べた数を超えている")} ] ,
        [ sh:path fsl:activityDate ; sh:maxCount 1 ; sh:datatype xsd:date ] .

fslsh:InquiryShape a sh:NodeShape ;
    sh:targetClass fsl:Inquiry ;
    rdfs:label {_ja("問い合わせ")} ;
    rdfs:comment {_ja("いつ、どの担当課に、どの方法で聞き、回答があったか。回答の文面は持たない。")} ;
    sh:class prov:Activity ;
    sh:property
        [ sh:path fsl:activityDate ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:date ] ,
        [ sh:path fsl:inquiryTo ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ] ,
        [ sh:path fsl:inquiryMethod ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ] ,
        [ sh:path fsl:answerState ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype rdf:langString ] .

# ---------- データセットの説明(dataset.ttl) ----------

fslsh:DatasetShape a sh:NodeShape ;
    sh:targetClass dcat:Dataset ;
    rdfs:label {_ja("データセットの説明")} ;
    rdfs:comment {_ja("題名・説明・ライセンス・公開日・更新日・配布の形・従う語彙と形を持つ。")} ;
    sh:property
        [ sh:path dct:title ; sh:minCount 1 ] ,
        [ sh:path dct:description ; sh:minCount 1 ] ,
        [ sh:path dct:license ; sh:minCount 1 ; sh:maxCount 1 ; sh:nodeKind sh:IRI ] ,
        [ sh:path dct:issued ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:date ] ,
        [ sh:path dct:modified ; sh:minCount 1 ; sh:maxCount 1 ; sh:datatype xsd:date ] ,
        [ sh:path dct:issued ; sh:lessThanOrEquals dct:modified ; sh:message {_ja("更新日が公開日より前になっている")} ] ,
        [ sh:path dct:conformsTo ; sh:hasValue <{BASE}ns#> ; sh:message {_ja("語彙(ns#)への dct:conformsTo が無い")} ] ,
        [ sh:path dct:conformsTo ; sh:hasValue <{SHAPES_IRI}> ; sh:message {_ja("形(shapes)への dct:conformsTo が無い")} ] ,
        [ sh:path dcat:distribution ; sh:minCount 1 ; sh:class dcat:Distribution ] .
"""


def write(path: Path = OUT) -> None:
    path.write_text(shapes_turtle(), encoding="utf-8")


def _graph(paths: list[Path]):
    from rdflib import Graph

    g = Graph()
    for p in paths:
        g.parse(p, format="turtle")
    return g


def validate(site: str | Path, shapes_text: str | None = None) -> tuple[bool, list[str], int]:
    """公開する一式(seido.ttl と dataset.ttl)を形で検査する。(合格か, 外れた所の一覧, 見たトリプルの数)。"""
    from pyshacl import validate as shacl_validate
    from rdflib import Graph, Namespace

    site = Path(site)
    data = _graph([site / "seido.ttl", site / "dataset.ttl"])
    shapes = Graph().parse(data=shapes_text or shapes_turtle(), format="turtle")
    conforms, report, _ = shacl_validate(data, shacl_graph=shapes, inference="none", advanced=False,
                                         abort_on_first=False, allow_warnings=False)
    SH = Namespace("http://www.w3.org/ns/shacl#")
    problems = []
    for r in report.subjects(SH.resultSeverity, SH.Violation):
        focus = report.value(r, SH.focusNode)
        path = report.value(r, SH.resultPath)
        msgs = [str(m) for m in report.objects(r, SH.resultMessage)]
        jp = [m for m in msgs if isinstance(m, str) and re.search(r"[ぁ-んァ-ン一-龥]", m)]
        problems.append(f"{focus} {path or ''} {(jp or msgs or [''])[0]}".strip())
    return bool(conforms), sorted(problems), len(data)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["--check"]:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != shapes_turtle():
            print(f"{OUT} が最新でない。python -m futoko_lod.shapes を回す")
            return 1
        print(f"{OUT} は最新")
        return 0
    if args[:1] == ["--validate"]:
        site = args[1] if len(args) > 1 else "_site"
        ok, problems, n = validate(site)
        if ok:
            print(f"形(SHACL)の検査に通った({site}/seido.ttl と dataset.ttl、トリプル {n} 個)")
            return 0
        print(f"形(SHACL)の検査に落ちた({len(problems)}件):")
        print("\n".join(problems))
        return 1
    write()
    print(f"{OUT} を書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
