/**
 * 大学の採用ページを毎日巡回し、更新を検知してメールで通知します。
 *
 * 転職サイトに掲載されない大学職員求人を取りこぼさないための監視ツールです。
 *
 * シート構成:
 * - 監視先        : 巡回する大学と採用ページURLの一覧
 * - 検知結果      : 更新を検知した行の記録
 * - スナップショット: 前回取得した本文（差分比較用。手動で編集しない）
 *
 * 使い方は docs/university_job_watcher.md を参照してください。
 */

const WATCH_SHEET_NAME = '監視先';
const RESULT_SHEET_NAME = '検知結果';
const SNAPSHOT_SHEET_NAME = 'スナップショット';

/** 求人らしい行を拾うためのキーワード */
const INCLUDE_KEYWORDS = [
  '職員', '事務', '採用', '募集', '求人', '専任', '契約職員',
  '嘱託', '事務局', 'キャリア採用', '中途', 'スタッフ'
];

/** 教員公募など、大学職員の応募先として不要な行を除くキーワード */
const EXCLUDE_KEYWORDS = [
  '教授', '准教授', '助教', '助手', '非常勤講師', '研究員', '教員公募', 'ポスドク'
];

/** 1ページあたりの通知行数の上限 */
const MAX_LINES_PER_SITE = 15;

/** スナップショットとして保存する本文の最大文字数（セルの上限対策） */
const MAX_SNAPSHOT_LENGTH = 40000;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('大学求人監視')
    .addItem('初期設定（シートを作成）', 'setupSheets')
    .addSeparator()
    .addItem('今すぐチェックする', 'checkAllSites')
    .addSeparator()
    .addItem('毎日の自動チェックを設定', 'installDailyTrigger')
    .addItem('自動チェックを解除', 'removeDailyTrigger')
    .addToUi();
}

/**
 * 必要なシートを作成し、見出しとサンプル行を入れます。
 */
function setupSheets() {
  const ui = SpreadsheetApp.getUi();

  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

    const watchSheet = getOrCreateSheet_(spreadsheet, WATCH_SHEET_NAME);
    if (watchSheet.getLastRow() === 0) {
      watchSheet.getRange(1, 1, 1, 6).setValues([
        ['大学名', '採用ページURL', 'メモ', '有効', '最終確認日時', '前回の状態']
      ]);
      watchSheet.getRange(2, 1, 2, 4).setValues([
        ['サンプル大学', 'https://example.ac.jp/recruit/', '記入例。実際のURLに置き換えてください', false],
        ['サンプル大学（法人）', 'https://example.ac.jp/about/employment/', '法人事務局の採用ページ', false]
      ]);
      watchSheet.setFrozenRows(1);
      watchSheet.setColumnWidth(2, 320);
    }

    const resultSheet = getOrCreateSheet_(spreadsheet, RESULT_SHEET_NAME);
    if (resultSheet.getLastRow() === 0) {
      resultSheet.getRange(1, 1, 1, 5).setValues([
        ['検知日時', '大学名', '検知した記述', 'ページURL', '確認状況']
      ]);
      resultSheet.setFrozenRows(1);
      resultSheet.setColumnWidth(3, 420);
      resultSheet.setColumnWidth(4, 320);
    }

    const snapshotSheet = getOrCreateSheet_(spreadsheet, SNAPSHOT_SHEET_NAME);
    if (snapshotSheet.getLastRow() === 0) {
      snapshotSheet.getRange(1, 1, 1, 4).setValues([
        ['大学名', 'URL', 'ハッシュ', '本文（自動保存・編集しない）']
      ]);
      snapshotSheet.setFrozenRows(1);
    }

    ui.alert(
      '初期設定が完了しました',
      '「' + WATCH_SHEET_NAME + '」シートに、巡回したい大学名と採用ページURLを入力してください。\n' +
      '「有効」列にチェックを入れた行だけを巡回します。',
      ui.ButtonSet.OK
    );
  } catch (error) {
    ui.alert('初期設定に失敗しました', error.message, ui.ButtonSet.OK);
  }
}

/**
 * 監視先シートの全ページを巡回します。トリガーからも呼ばれます。
 */
function checkAllSites() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const watchSheet = spreadsheet.getSheetByName(WATCH_SHEET_NAME);

  if (!watchSheet) {
    notifyOrThrow_('「' + WATCH_SHEET_NAME + '」シートがありません。先に「初期設定」を実行してください。');
    return;
  }

  const lastRow = watchSheet.getLastRow();
  if (lastRow < 2) {
    notifyOrThrow_('監視先が登録されていません。');
    return;
  }

  const rows = watchSheet.getRange(2, 1, lastRow - 1, 4).getValues();
  const snapshots = readSnapshots_(spreadsheet);
  const updates = [];
  const errors = [];
  const now = new Date();

  rows.forEach(function(row, index) {
    const rowNumber = index + 2;
    const name = String(row[0]).trim();
    const url = String(row[1]).trim();
    const enabled = row[3] === true || String(row[3]).toUpperCase() === 'TRUE';

    if (!name || !url || !enabled) {
      return;
    }

    let status;
    try {
      const text = fetchPageText_(url);
      const hash = computeHash_(text);
      const key = name + '\t' + url;
      const previous = snapshots[key];

      if (!previous) {
        status = '初回登録';
      } else if (previous.hash === hash) {
        status = '変更なし';
      } else {
        const lines = extractNewLines_(text, previous.text);
        status = lines.length > 0 ? '更新あり（' + lines.length + '件）' : '更新あり（該当語なし）';
        updates.push({ name: name, url: url, lines: lines });
      }

      saveSnapshot_(spreadsheet, key, name, url, hash, text);
    } catch (error) {
      status = 'エラー: ' + error.message;
      errors.push(name + '（' + url + '）: ' + error.message);
    }

    watchSheet.getRange(rowNumber, 5).setValue(now);
    watchSheet.getRange(rowNumber, 6).setValue(status);

    Utilities.sleep(1500);
  });

  if (updates.length > 0) {
    recordUpdates_(spreadsheet, updates, now);
  }

  sendDigestEmail_(updates, errors, now);
}

/**
 * ページを取得し、本文をテキスト化します。
 */
function fetchPageText_(url) {
  const response = UrlFetchApp.fetch(url, {
    muteHttpExceptions: true,
    followRedirects: true,
    validateHttpsCertificates: true
  });

  const code = response.getResponseCode();
  if (code !== 200) {
    throw new Error('HTTP ' + code);
  }

  return htmlToText_(response.getContentText());
}

/**
 * HTMLから本文テキストを取り出します。
 */
function htmlToText_(html) {
  let text = String(html);

  text = text.replace(/<script[\s\S]*?<\/script>/gi, ' ');
  text = text.replace(/<style[\s\S]*?<\/style>/gi, ' ');
  text = text.replace(/<!--[\s\S]*?-->/g, ' ');
  text = text.replace(/<\/(p|div|li|tr|h1|h2|h3|h4|h5|table|section|article)>/gi, '\n');
  text = text.replace(/<br\s*\/?>/gi, '\n');
  text = text.replace(/<[^>]+>/g, ' ');

  text = text.replace(/&nbsp;/gi, ' ');
  text = text.replace(/&amp;/gi, '&');
  text = text.replace(/&lt;/gi, '<');
  text = text.replace(/&gt;/gi, '>');
  text = text.replace(/&quot;/gi, '"');
  text = text.replace(/&#39;/gi, "'");

  const lines = text.split('\n').map(function(line) {
    return line.replace(/[ \t　]+/g, ' ').trim();
  }).filter(function(line) {
    return line.length > 0;
  });

  return lines.join('\n');
}

/**
 * 前回本文に無かった行のうち、求人らしいものを返します。
 */
function extractNewLines_(newText, oldText) {
  const oldLines = {};
  String(oldText).split('\n').forEach(function(line) {
    oldLines[line] = true;
  });

  const seen = {};
  const results = [];

  newText.split('\n').forEach(function(line) {
    if (results.length >= MAX_LINES_PER_SITE) {
      return;
    }
    if (oldLines[line] || seen[line]) {
      return;
    }
    if (line.length < 6 || line.length > 200) {
      return;
    }
    if (!containsAny_(line, INCLUDE_KEYWORDS)) {
      return;
    }
    if (containsAny_(line, EXCLUDE_KEYWORDS)) {
      return;
    }

    seen[line] = true;
    results.push(line);
  });

  return results;
}

function containsAny_(text, keywords) {
  for (let i = 0; i < keywords.length; i++) {
    if (text.indexOf(keywords[i]) !== -1) {
      return true;
    }
  }
  return false;
}

function computeHash_(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, text, Utilities.Charset.UTF_8);
  return bytes.map(function(byte) {
    return ('0' + (byte & 0xff).toString(16)).slice(-2);
  }).join('');
}

function readSnapshots_(spreadsheet) {
  const sheet = getOrCreateSheet_(spreadsheet, SNAPSHOT_SHEET_NAME);
  const lastRow = sheet.getLastRow();
  const snapshots = {};

  if (lastRow < 2) {
    return snapshots;
  }

  const rows = sheet.getRange(2, 1, lastRow - 1, 4).getValues();
  rows.forEach(function(row, index) {
    const key = String(row[0]) + '\t' + String(row[1]);
    snapshots[key] = {
      rowNumber: index + 2,
      hash: String(row[2]),
      text: String(row[3])
    };
  });

  return snapshots;
}

function saveSnapshot_(spreadsheet, key, name, url, hash, text) {
  const sheet = getOrCreateSheet_(spreadsheet, SNAPSHOT_SHEET_NAME);
  const snapshots = readSnapshots_(spreadsheet);
  const stored = text.length > MAX_SNAPSHOT_LENGTH ? text.substring(0, MAX_SNAPSHOT_LENGTH) : text;
  const values = [[name, url, hash, stored]];

  if (snapshots[key]) {
    sheet.getRange(snapshots[key].rowNumber, 1, 1, 4).setValues(values);
  } else {
    sheet.getRange(sheet.getLastRow() + 1, 1, 1, 4).setValues(values);
  }
}

function recordUpdates_(spreadsheet, updates, now) {
  const sheet = getOrCreateSheet_(spreadsheet, RESULT_SHEET_NAME);
  const rows = [];

  updates.forEach(function(update) {
    if (update.lines.length === 0) {
      rows.push([now, update.name, '（ページが更新されましたが、該当語を含む行はありません）', update.url, '未確認']);
      return;
    }
    update.lines.forEach(function(line) {
      rows.push([now, update.name, line, update.url, '未確認']);
    });
  });

  if (rows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 5).setValues(rows);
  }
}

function sendDigestEmail_(updates, errors, now) {
  const address = Session.getActiveUser().getEmail();
  if (!address) {
    return;
  }

  const dateLabel = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy/MM/dd');
  const lines = [];

  lines.push('大学採用ページ 巡回結果（' + dateLabel + '）');
  lines.push('');

  if (updates.length === 0) {
    lines.push('■ 更新は検知されませんでした。');
  } else {
    lines.push('■ 更新を検知した大学: ' + updates.length + '件');
    lines.push('');
    updates.forEach(function(update) {
      lines.push('【' + update.name + '】');
      lines.push(update.url);
      if (update.lines.length === 0) {
        lines.push('  ページは更新されましたが、求人に関する語を含む行はありませんでした。');
      } else {
        update.lines.forEach(function(line) {
          lines.push('  ・' + line);
        });
      }
      lines.push('');
    });
    lines.push('※ 検知は自動判定です。応募要項・締切・雇用形態は必ず大学公式ページ本文で確認してください。');
  }

  if (errors.length > 0) {
    lines.push('');
    lines.push('■ 取得できなかったページ: ' + errors.length + '件');
    errors.forEach(function(message) {
      lines.push('  ・' + message);
    });
    lines.push('  URLの変更、またはアクセス制限の可能性があります。');
  }

  const subject = updates.length > 0
    ? '【大学求人】' + dateLabel + ' 更新 ' + updates.length + '件'
    : '【大学求人】' + dateLabel + ' 更新なし';

  MailApp.sendEmail(address, subject, lines.join('\n'));
}

/**
 * 毎日1回、自動でチェックするトリガーを設定します。
 */
function installDailyTrigger() {
  const ui = SpreadsheetApp.getUi();

  try {
    removeTriggers_();
    ScriptApp.newTrigger('checkAllSites')
      .timeBased()
      .atHour(7)
      .everyDays(1)
      .create();

    ui.alert('自動チェックを設定しました', '毎日7時台に巡回し、結果をメールで送ります。', ui.ButtonSet.OK);
  } catch (error) {
    ui.alert('トリガーを設定できませんでした', error.message, ui.ButtonSet.OK);
  }
}

function removeDailyTrigger() {
  const ui = SpreadsheetApp.getUi();

  try {
    const count = removeTriggers_();
    ui.alert('自動チェックを解除しました', '解除したトリガー: ' + count + '件', ui.ButtonSet.OK);
  } catch (error) {
    ui.alert('トリガーを解除できませんでした', error.message, ui.ButtonSet.OK);
  }
}

function removeTriggers_() {
  const triggers = ScriptApp.getProjectTriggers();
  let count = 0;

  triggers.forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'checkAllSites') {
      ScriptApp.deleteTrigger(trigger);
      count++;
    }
  });

  return count;
}

function getOrCreateSheet_(spreadsheet, name) {
  const sheet = spreadsheet.getSheetByName(name);
  return sheet ? sheet : spreadsheet.insertSheet(name);
}

/**
 * 画面から実行したときはダイアログ、トリガー実行時は例外として記録します。
 */
function notifyOrThrow_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    throw new Error(message);
  }
}
