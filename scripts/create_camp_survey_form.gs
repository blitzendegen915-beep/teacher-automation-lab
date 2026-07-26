/**
 * 2026年 夏合宿 参加者アンケート フォーム自動作成スクリプト
 *
 * 使い方:
 * 1. https://script.google.com/ を開く（顧問の占部先生のGoogleアカウントでログイン）
 * 2. 「新しいプロジェクト」→ このファイルの中身を全部貼り付け
 * 3. 上部の「実行」ボタンを押す（関数 createCampSurvey を実行）
 * 4. 実行ログ（表示 → ログ）に「回答フォームURL」と「編集用URL」が出力される
 * 5. 回答フォームURLを保護者・生徒に配布する（Googleアカウント不要で回答可能）
 *
 * 注意: アレルギー・病歴・緊急連絡先という機微な個人情報を扱うため、
 * フォーム作成後は必ず「回答」タブでスプレッドシートへのリンクを設定し、
 * 回答データの閲覧権限を顧問のみに限定すること（部員・保護者には共有しない）。
 */
function createCampSurvey() {
  var form = FormApp.create('2026年 夏合宿 参加者アンケート');

  form.setDescription(
    '駒澤大学高等学校ラグビー部\n' +
    '夏合宿（8月1日〜8月7日・菅平ホテル）にあたり、安全管理のため下記の項目についてご回答をお願いいたします。\n' +
    '回答内容は顧問のみが確認し、合宿の安全管理以外の目的には使用しません。\n' +
    'Googleアカウントは不要です。'
  );

  // 集計しやすいよう、メールアドレス収集はオフのままにする（アカウント不要の原則を維持）
  form.setCollectEmail(false);
  // 個人のGoogleアカウントで作成した場合、既定でログイン不要（誰でも回答可）になる。
  // 学校のWorkspaceアカウントで作成する場合は、フォーム作成後に
  // 設定 → 回答 → 「Googleにログインが必要」がオフになっているか手動で確認すること。

  form.addListItem()
      .setTitle('学年')
      .setChoiceValues(['1年', '2年', '3年'])
      .setRequired(true);

  form.addTextItem()
      .setTitle('組')
      .setHelpText('例：C　（アルファベット1文字）')
      .setRequired(true);

  form.addTextItem()
      .setTitle('番号')
      .setHelpText('出席番号を半角数字で入力してください。')
      .setRequired(true);

  form.addTextItem()
      .setTitle('氏名')
      .setHelpText('例：山口 翼')
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('アレルギー調査')
      .setHelpText('食物アレルギー・薬品アレルギー等があれば具体的に記入してください。無い場合は「なし」と記入してください。')
      .setRequired(true);

  form.addParagraphTextItem()
      .setTitle('病歴・傷歴')
      .setHelpText('既往症、現在治療中のけが・持病、服薬中の薬等があれば記入してください。無い場合は「なし」と記入してください。')
      .setRequired(true);

  form.addTextItem()
      .setTitle('緊急連絡先①（電話番号）')
      .setHelpText('合宿中に最優先で連絡がつく番号を入力してください。例：090-1234-5678')
      .setRequired(true);

  form.addTextItem()
      .setTitle('緊急連絡先②（電話番号）')
      .setHelpText('①がつながらない場合の連絡先。')
      .setRequired(false);

  form.addTextItem()
      .setTitle('緊急連絡先③（電話番号）')
      .setHelpText('②もつながらない場合の連絡先。')
      .setRequired(false);

  Logger.log('回答フォームURL（配布用）: ' + form.getPublishedUrl());
  Logger.log('編集用URL（顧問のみ）: ' + form.getEditUrl());
}
