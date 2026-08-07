# edusup

高校英語教員の校務・教材制作・授業準備を自動化するためのツール置き場です。

## タスク運用

タスク指示書は `tasks/` 配下の作業レーンで管理します。

- `tasks/todo/`: 未着手タスクを置く
- `tasks/doing/`: 作業開始時にタスクを移動する
- `tasks/done/`: 実装完了後にタスクを移動する

実装時は `AGENTS.md` の方針に従います。完了後は、必要に応じて `README.md` と `docs/` も更新します。

## note 記事の生産ライン

note で公開・販売する記事の原稿とネタ出しは `note/` 配下で管理します。

- `note/README.md`: 執筆から公開までの手順・価格の付け方
- `note/backlog.md`: ネタ出しリスト（書く前にここから選ぶ）
- `note/templates/`: 記事のひな型
- `note/drafts/`: 原稿

## ツール

### Google Forms 小テスト自動作成

Googleスプレッドシートの「問題」シートに入力した文法問題から、Google Forms の小テストを自動作成します。

- コード: `gas/form_generator.gs`
- 使い方: `docs/google_forms_generator.md`
- タスク指示書: `tasks/done/001-google-forms-generator.md`

### 教材ストア（販売サイト）

自作教材（PDF・Excelなど）を販売する自前ストアサイトです。商品を `products.json` に書いて push するだけで GitHub Pages に自動公開されます。Google検索向けのSEO対応（商品ごとの個別ページ・構造化データ・sitemap.xml）と、Stripe 支払いリンクによる決済に対応しています。

- コード: `web/shop/`
- 使い方: `docs/material_shop.md`
- タスク指示書: `tasks/done/002-material-shop-site.md`
