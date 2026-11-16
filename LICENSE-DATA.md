# データのライセンス

`data/` にあるデータ(CSV、JSON-LD)は、クリエイティブ・コモンズ 表示 4.0 国際(CC BY 4.0)で公開する。**ただし `data/rinsetsu.csv`(隣り合う市町村の表)だけは、クリエイティブ・コモンズ 表示-継承 3.0(CC BY-SA 3.0)** とする(下の「ほかから引いたデータ」)。

- ライセンスの全文: https://creativecommons.org/licenses/by/4.0/legalcode.ja
- 表示の例: 「不登校支援制度LOD(h-kazuki-pixel)、CC BY 4.0」

コード(`data/` 以外)は MIT ライセンス。`LICENSE` を見る。

## データの中身について

- 各市町村・県の公式ページにある事実(制度の有無、金額、対象、時期)を、項目に直したもの。公式ページの文章は写していない。
- 制度は変わる。使う前に、各行の「出典URL」と「確認日」を確かめてほしい。申請できるかどうかは、必ず市町村の窓口で確かめてほしい。
- 誤りを見つけたら、GitHub の Issue で知らせてほしい。

## ほかから引いたデータ

- `data/kumiawase/jidou_seito.csv` の児童数・生徒数は、e-Stat 統計LOD(総務省統計局・独立行政法人統計センター、https://data.e-stat.go.jp/lodw/ )の「社会・人口統計体系」から引いて、表に直したもの。このリポジトリが作った数字ではない。使うときは、e-Stat 統計LOD を出典として示してほしい。統計LOD のサイトのトップページに「注があるものを除いて、このサイトの内容物は クリエイティブ・コモンズ 表示 4.0 ライセンスの下に提供されています」とある(2026-11-16 に読んだ)。出典の書き方や加工したときの決まりを書いたページは、トップページからは見つからなかった。
- `data/dbpedia.csv` は、DBpedia Japanese(http://ja.dbpedia.org )の市町村の資源の URI と名前を、確かめた結果と一緒に記録したもの。URI と名前は DBpedia Japanese によるもの。
- `data/rinsetsu.csv` は、DBpedia Japanese の市町村の資源が持つ「隣接自治体」(元は2022年12月の Wikipedia 日本語版)を引き、地方公共団体コードに直したもの。DBpedia Japanese のライセンス(CC BY-SA 3.0、https://creativecommons.org/licenses/by-sa/3.0/deed.ja )を引き継ぐので、このファイルだけ CC BY-SA 3.0 で公開する。データ本体(`seido.csv`、`seido.jsonld`、公開する Turtle)には入れていない。公開ページの1件ごとのページと組み合わせの例で隣の市町村と並べている部分も、この表から作っている(ページにその旨を書いている)。
