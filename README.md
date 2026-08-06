# edusup

高校英語教員の校務・教材制作・授業準備を自動化するためのツール置き場です。

## タスク運用

タスク指示書は `tasks/` 配下の作業レーンで管理します。

- `tasks/todo/`: 未着手タスクを置く
- `tasks/doing/`: 作業開始時にタスクを移動する
- `tasks/done/`: 実装完了後にタスクを移動する

実装時は `AGENTS.md` の方針に従います。完了後は、必要に応じて `README.md` と `docs/` も更新します。

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

### 部活動ハイライト動画（AviUtl）

部活動のかっこいいハイライト動画を AviUtl で作るための、スクリプトと手順書です。曲のビートにカットを合わせる「音ハメ」、スローモーション、シネマティックな色味、テロップ演出を扱います。撮影のカメラ設定と、公開前の著作権・肖像権の確認事項もまとめてあります。

- スクリプト: `aviutl/beat_punch.anm`（ビートパンチ）／`aviutl/impact_shake.anm`（衝撃シェイク）／`aviutl/telop_kick.anm`（テロップキック）
- 音ハメ計算機: `aviutl/beatgrid.html`（ブラウザで開くだけ。BPMからカット位置のフレーム番号を出す）
- 使い方: `docs/rugby_hype_video.md`
- タスク指示書: `tasks/done/006-rugby-hype-video.md`
