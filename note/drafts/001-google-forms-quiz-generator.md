<!-- メタ情報。note には貼らない -->
- ステータス: 完成（公開待ち）
- 想定読者: 小テスト・確認テスト・研修テストをGoogleフォームで作っている人
- 価格: 500円
- 有料ライン: 「ここから先は、実際のコードと設置手順です」の直前
- 公開日: 未定
- URL: 公開後に記入

---

## タイトル案

1. **スプレッドシートに書くだけ。Googleフォームの小テストを3分で作る【コード全文】** ← 推奨
2. Googleフォームの小テスト、1問ずつ手で作るのをやめました【コード全文つき】
3. 100問の小テストを、コピペ1回で自動生成する方法

---

# スプレッドシートに書くだけ。Googleフォームの小テストを3分で作る【コード全文】

Googleフォームで小テストを作ったことがある人なら、たぶん一度は思ったはずです。

**「これ、10問作るのに20分かかってないか？」**

問題文を打つ。選択肢を4つ打つ。正解にチェックを入れる。配点を1点にする。解説を入れる。必須にする。──これを1問ずつ、10回。しかも来週も再来週もやる。

この作業をやめました。いまは**スプレッドシートに問題を書いて、メニューを1回クリックするだけ**でフォームが出来上がります。10問でも100問でも、かかる時間は変わりません。

この記事では、その仕組みを丸ごと公開します。プログラミングの経験は要りません。コピペと、承認ボタンを押すだけです。

## この記事でできるようになること

- スプレッドシートに問題を並べるだけで、Googleフォームの小テストが自動で出来上がる
- 正解・配点・解説フィードバックまで、全部セットされた状態で作られる
- 問題文の使い回しができる。去年のシートをコピーして数問差し替えれば、それだけで今年の小テストになる

## なぜ作ったか

Googleフォームの小テスト機能は、よくできています。自動採点してくれるし、正解・不正解のフィードバックも出せる。生徒側の体験としては十分です。

問題は**作る側**です。

フォームの編集画面は「1問ずつ、順番に」作ることしか想定していません。ところが実際の作問は違います。問題は先にまとめて考えるし、去年のものを流用したいし、同僚と共有するならテキストで持っておきたい。**問題はリストで持ちたいのに、入力はリストでさせてくれない。** ここがずっと噛み合っていませんでした。

だったら、リストで持っている側（スプレッドシート）から、フォームを生成すればいい。それだけの話です。

## どう動くか

まず、スプレッドシートに「問題」という名前のシートを作り、こう並べます。

- A列：問題文
- B〜E列：選択肢1〜4
- F列：正解番号（1〜4）
- G列：解説

たとえば1行目を見出しにして、2行目にこう書きます。

- A列 `I ___ tennis yesterday.`
- B列 `play`
- C列 `played`
- D列 `playing`
- E列 `plays`
- F列 `2`
- G列 `yesterday があるので過去形の played を使います。`

これを必要な数だけ下に並べます。Excelで作った既存の問題リストがあるなら、貼り付けるだけです。

そのあと、スプレッドシートの上部に増えている「**フォーム作成**」メニューから「**小テストを作成する**」をクリックします。

数秒で、こういうダイアログが出ます。

```
フォームを作成しました

編集用URL:
https://docs.google.com/forms/d/……/edit

回答用URL:
https://docs.google.com/forms/d/……/viewform
```

回答用URLを配れば、それで終わりです。フォーム側にはすでに、

- 全問が4択の選択式になっている
- 各問1点が設定されている
- F列で指定した選択肢が正解として登録されている
- G列の解説が、回答後のフィードバックとして表示される
- 全問が「必須」になっている

という状態が出来上がっています。フォームの編集画面は一度も開いていません。

## 仕組みの説明

やっていることは、実はとても素直です。

1. スプレッドシートの「問題」シートを、2行目から最終行まで読む
2. 1行を1問として、問題文・選択肢・正解番号・解説に分解する
3. **読み込んだ時点で内容をチェックする**（ここが大事）
4. 問題がなければ、`FormApp` という機能で新しいフォームを作り、1問ずつ追加していく
5. 出来上がったフォームのURLを画面に出す

ポイントは3番です。

自動化ツールで一番怖いのは、**間違ったまま黙って完成してしまうこと**です。正解番号の列に `5` と打ってしまった、選択肢を1つ入れ忘れた、問題文だけ書いて選択肢が空のまま──こういうミスをそのまま通すと、出来上がったフォームは一見正常なのに中身が壊れています。生徒が解いてから気づくのが最悪のパターンです。

なので、このスクリプトは**作る前に全行を検査して、おかしければ「何行目の何がおかしいか」を名指しで止めます。**

```
5行目の正解番号は 1 から 4 の整数で入力してください。
```

```
12行目の選択肢3が空です。
```

こう出ます。フォームは作られません。直してもう一度押すだけです。

空行は無視されるので、問題と問題のあいだに空行を入れて整理しても問題ありません。ただし「途中まで入力されている行」は、書きかけの事故とみなしてエラーにしています。

ここまでが仕組みです。あとは実際のコードを入れるだけです。

<!-- ===== ここから有料 ===== -->

---

ここから先は、実際のコードと設置手順です。コピペして貼り付ければ、そのまま動きます。

---

### 設置手順

**1. スプレッドシートを用意する**

新しいGoogleスプレッドシートを作り、シート名を「**問題**」に変更します。名前は完全一致で見ています。「問題シート」「Questions」などにするとエラーになります。

1行目に見出しを書きます（内容は自由です。読み込みには使いません）。

```
問題文 / 選択肢1 / 選択肢2 / 選択肢3 / 選択肢4 / 正解番号 / 解説
```

**2. Apps Script を開く**

メニューの「**拡張機能**」→「**Apps Script**」を開きます。

「コード.gs」というファイルに `function myFunction() {}` と書かれているので、**全部消します**。

**3. 次のコードを全部貼り付ける**

```javascript
/**
 * Google Sheets の「問題」シートから Google Forms の小テストを作成します。
 *
 * 入力列:
 * A: 問題文, B-E: 選択肢1-4, F: 正解番号, G: 解説
 */
const QUESTION_SHEET_NAME = '問題';
const FORM_TITLE = '文法小テスト';

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('フォーム作成')
    .addItem('小テストを作成する', 'createGrammarQuizForm')
    .addToUi();
}

function createGrammarQuizForm() {
  const ui = SpreadsheetApp.getUi();

  try {
    const questions = readQuestionsFromSheet_();
    const form = buildQuizForm_(questions);

    ui.alert(
      'フォームを作成しました',
      '編集用URL:\n' + form.getEditUrl() + '\n\n回答用URL:\n' + form.getPublishedUrl(),
      ui.ButtonSet.OK
    );
  } catch (error) {
    ui.alert('フォームを作成できませんでした', error.message, ui.ButtonSet.OK);
  }
}

function readQuestionsFromSheet_() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName(QUESTION_SHEET_NAME);

  if (!sheet) {
    throw new Error('「' + QUESTION_SHEET_NAME + '」シートが見つかりません。');
  }

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) {
    throw new Error('2行目以降に問題を入力してください。');
  }

  const rows = sheet.getRange(2, 1, lastRow - 1, 7).getValues();
  const questions = [];

  rows.forEach(function(row, index) {
    const rowNumber = index + 2;
    const questionText = String(row[0]).trim();
    const options = row.slice(1, 5).map(function(option) {
      return String(option).trim();
    });
    const answerNumber = Number(row[5]);
    const explanation = String(row[6]).trim();

    if (!questionText && options.every(function(option) { return !option; }) && !row[5] && !explanation) {
      return;
    }

    validateQuestionRow_(rowNumber, questionText, options, answerNumber);

    questions.push({
      questionText: questionText,
      options: options,
      answerNumber: answerNumber,
      explanation: explanation
    });
  });

  if (questions.length === 0) {
    throw new Error('読み込める問題がありません。2行目以降に問題を入力してください。');
  }

  return questions;
}

function validateQuestionRow_(rowNumber, questionText, options, answerNumber) {
  if (!questionText) {
    throw new Error(rowNumber + '行目の問題文が空です。');
  }

  options.forEach(function(option, index) {
    if (!option) {
      throw new Error(rowNumber + '行目の選択肢' + (index + 1) + 'が空です。');
    }
  });

  if (!Number.isInteger(answerNumber) || answerNumber < 1 || answerNumber > 4) {
    throw new Error(rowNumber + '行目の正解番号は 1 から 4 の整数で入力してください。');
  }
}

function buildQuizForm_(questions) {
  const form = FormApp.create(FORM_TITLE);
  form.setIsQuiz(true);
  form.setDescription('Googleスプレッドシートから自動作成した文法小テストです。');

  questions.forEach(function(question, index) {
    const item = form.addMultipleChoiceItem();
    const choices = question.options.map(function(option, optionIndex) {
      return item.createChoice(option, optionIndex + 1 === question.answerNumber);
    });

    item.setTitle((index + 1) + '. ' + question.questionText)
      .setChoices(choices)
      .setPoints(1)
      .setRequired(true);

    if (question.explanation) {
      const feedback = FormApp.createFeedback()
        .setText(question.explanation)
        .build();
      item.setFeedbackForCorrect(feedback);
      item.setFeedbackForIncorrect(feedback);
    }
  });

  return form;
}
```

**4. 保存する**

フロッピーディスクのアイコン、または `Ctrl + S`（Macは `Command + S`）で保存します。

**5. スプレッドシートを再読み込みする**

スプレッドシートのタブに戻り、**ブラウザの再読み込み**をします。ここを飛ばすとメニューが出ません。

数秒待つと、メニューバーの右側に「**フォーム作成**」が増えています。

**6. 初回だけ、権限を承認する**

「フォーム作成」→「小テストを作成する」を最初に押したときだけ、Googleの承認画面が出ます。

1. 「承認が必要です」→「**権限を確認**」
2. 自分のGoogleアカウントを選ぶ
3. **「このアプリは確認されていません」と出ます。** ここで戸惑う人が多いのですが、これは「Googleの審査を受けていない個人のスクリプト」という意味で、危険という意味ではありません。自分で貼ったコードなので当然そうなります。
4. 左下の「**詳細**」→「**（プロジェクト名）に移動（安全ではないページ）**」
5. 「**許可**」

一度承認すれば、次からは出ません。

### つまずいたときの対処

**「問題」シートが見つかりません、と出る**
シート名が完全一致していません。下部のシートタブを右クリック→名前を変更で、`問題` の2文字だけにしてください。前後の空白も見られています。

**メニューに「フォーム作成」が出ない**
スプレッドシートを再読み込みしていないか、コードの保存を忘れています。保存 →スプレッドシート再読み込み、の順です。

**「◯行目の正解番号は 1 から 4 の整数で入力してください」と出る**
F列を確認します。よくあるのは、`2` のつもりで全角の `２` を入れている、空白が混ざっている、`2.0` になっている、のどれかです。F列を選択して「表示形式→数値」にしてから入れ直すと確実です。

**「◯行目の選択肢◯が空です」と出る**
その行の選択肢が埋まっていません。3択にしたい場合も、この仕組みは4択前提なのでダミーの選択肢が要ります。

**実行するたびに新しいフォームができてしまう**
仕様です。既存フォームを上書きするのではなく、毎回まっさらなフォームを作ります。**これはわざとそうしています。** 上書き方式にすると、配布済みのフォームを誤って作り直して回答が消える事故が起きます。要らないフォームは後からGoogleドライブで消せますが、消えた回答は戻りません。

**問題数が多いと時間がかかる**
100問前後までは問題なく動きます。それ以上を一度に作ると、Apps Script の実行時間の上限（6分）に近づきます。回ごとにシートを分けるのが現実的です。

### ここから先の応用

**フォームのタイトルを変える**
コード先頭の `const FORM_TITLE = '文法小テスト';` の部分を書き換えます。日付を自動で入れたいなら、こうします。

```javascript
const form = FormApp.create(FORM_TITLE + ' ' + Utilities.formatDate(new Date(), 'Asia/Tokyo', 'yyyy/MM/dd'));
```

（`buildQuizForm_` の中の `FormApp.create(FORM_TITLE)` を、この行に差し替えます。）

**配点を変える**
`.setPoints(1)` の `1` を変えます。行ごとに配点を変えたいなら、H列に配点を足して読み込む形に拡張できます。

**選択肢の数を変える**
`row.slice(1, 5)` が「B列からE列まで」を意味しています。6択にするなら `row.slice(1, 7)` にして、正解番号のチェック（`answerNumber > 4`）も合わせて直します。

**解説を「不正解のときだけ」出す**
`setFeedbackForCorrect(feedback);` の行を消せば、不正解のときだけ解説が出ます。正解した生徒に余計な文章を読ませたくない場合はこちらです。

**記述式を混ぜる**
`addMultipleChoiceItem()` を `addTextItem()` に変えると記述式になります。ただし自動採点との相性があるので、選択式と分けたフォームにするほうが運用は楽です。

---

## 浮いた17分の使い道

自動化というと大げさに聞こえますが、やっていることは「**リストで持っているものを、リストのまま扱う**」だけです。

手で20分かけていた作業が3分になると、浮いた17分で問題の中身を考えられます。省略できるのは作業であって、中身ではありません。そこだけは間違えないようにしています。

質問や「こう変えたい」があれば、コメントで教えてください。次回は、**このフォームの回答を自動採点してシートに集計する**ところを書く予定です。

──────────

作ったものは教材ストアにも置いています。
https://blitzendegen915-beep.github.io/edusup

コードの全文はこちらでも公開しています。
https://github.com/blitzendegen915-beep/edusup
