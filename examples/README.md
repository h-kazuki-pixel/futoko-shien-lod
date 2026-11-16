# 使い方の例

不登校支援制度LOD を、プログラムから読む例です。データは CC BY 4.0 です(隣接の表 `rinsetsu.csv` だけ CC BY-SA 3.0)。使うときは「不登校支援制度LOD(h-kazuki-pixel)」と出典を示してください。

制度は変わります。使う前に、必ず市町村の窓口で確かめてください。「確認できず」は、制度が無いという意味ではありません。

## 1. Python と SPARQL で読む(`tsukaikata.py`)

```
pip install rdflib
python examples/tsukaikata.py 大野城市
```

公開している `seido.ttl`(全件)と `ns.ttl`(語彙)を読み、SPARQL で次の3つを出します。

- 選んだ市町村の、種類ごとの状態・制度名・出典・確認日
- 状態ごとの件数(「なし」と「確認できず」を分けて数える)
- 「確認できず」の行と、探したページの数

問い合わせの1つ目は、次の形です。市町村は `schema:areaServed` で e-Stat 統計LOD の標準地域コードの URI を指し、その名前で選んでいます。

```sparql
PREFIX schema: <https://schema.org/>
PREFIX dct: <http://purl.org/dc/terms/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX fsl: <https://h-kazuki-pixel.github.io/futoko-shien-lod/ns#>

SELECT ?kindLabel ?statusLabel ?name ?source WHERE {
  ?r a fsl:Record ;
     schema:areaServed/schema:name "大野城市"@ja ;
     fsl:kind/skos:prefLabel ?kindLabel ;
     fsl:status/skos:prefLabel ?statusLabel .
  OPTIONAL { ?r schema:name ?name }
  OPTIONAL { ?r dct:source ?source }
}
```

制度があると確かめた記録だけが `schema:GovernmentService` の型を持ちます。「なし」「確認できず」の記録は `fsl:Record` だけです。制度を数えるときは `?r a schema:GovernmentService` で絞ってください。

## 2. CSV だけで読む(追加の部品は要りません)

```python
import csv, io, urllib.request

url = "https://h-kazuki-pixel.github.io/futoko-shien-lod/seido.csv"
text = urllib.request.urlopen(url).read().decode("utf-8")
for r in csv.DictReader(io.StringIO(text)):
    if r["市町村"] == "大野城市":
        print(r["制度の種類"], r["状態"], r["出典URL"])
```

列の意味は `docs/データの項目.md` にあります。

## 3. 1件だけ取る

1件ごとに URI があり、`.ttl` か `.jsonld` を付けるとその1件が取れます。

```
https://h-kazuki-pixel.github.io/futoko-shien-lod/id/40219-fs-hojo.jsonld
```

## この例が動くことの確かめ

`tests/test_examples.py` が、公開物を手元で作り、この例の3つの問い合わせを走らせて、件数が CSV と合うことを確かめています。データや公開の形を変えて例が動かなくなれば、テストが落ちます。
