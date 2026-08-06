/**
 * 転職サイトから届く求人メールを毎日読み、大学・学校法人の求人だけを抜き出して
 * 1通のダイジェストにまとめて通知します。
 *
 * 求人サイトは自動アクセスを制限しているため直接巡回できません。
 * すでに受信しているメールを情報源にすることで、確実に取りこぼしを防ぎます。
 *
 * シート構成:
 * - 抽出設定  : 検索条件・抽出キーワード・除外キーワード
 * - 抽出結果  : 抽出した求人の記述
 * - 既出記録  : 通知済みの記述（重複通知を防ぐ。手動で編集しない）
 *
 * 使い方は docs/university_job_mail_digest.md を参照してください。
 */

const CONFIG_SHEET_NAME = '抽出設定';
const DIGEST_RESULT_SHEET_NAME = '抽出結果';
const SEEN_SHEET_NAME = '既出記録';

/** 既定の検索条件（Gmailの検索構文） */
const DEFAULT_QUERY = 'newer_than:2d (大学 OR 学校法人 OR 学園 OR 短期大学 OR 高等専門学校)';

/** この語を含む行を求人候補とする */
const DEFAULT_INCLUDE = '大学職員,学校法人,大学事務,学園,短期大学,教務,入試,学生支援,キャリアセンター,国際交流,産学連携,法人事務局';

/** この語を含む行は除く（教員公募・塾講師などを落とす） */
const DEFAULT_EXCLUDE = '教員,講師,教授,准教授,助教,塾,予備校,家庭教師,保育士,調理,警備,清掃,ドライバー';

/** 1通のメールから拾う最大行数 */
const MAX_LINES_PER_MAIL = 12;

/** 1回の実行で処理する最大スレッド数 */
const MAX_THREADS = 60;

/** 既出記録を保持する日数 */
const SEEN_RETENTION_DAYS = 60;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('求人メール抽出')
    .addItem('初期設定（シートを作成）', 'setupDigestSheets')
    .addSeparator()
    .addItem('今すぐ抽出する', 'runMailDigest')
    .addSeparator()
    .addItem('毎日の自動抽出を設定', 'installDigestTrigger')
    .addItem('自動抽出を解除', 'removeDigestTrigger')
    .addToUi();
}

/**
 * 必要なシートを作成し、既定の設定を書き込みます。
 */
function setupDigestSheets() {
  const ui = SpreadsheetApp.getUi();

  try {
    const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();

    const configSheet = getOrCreateDigestSheet_(spreadsheet, CONFIG_SHEET_NAME);
    if (configSheet.getLastRow() === 0) {
      configSheet.getRange(1, 1, 4, 2).setValues([
        ['項目', '値'],
        ['検索条件', DEFAULT_QUERY],
        ['抽出キーワード（カンマ区切り）', DEFAULT_INCLUDE],
        ['除外キーワード（カンマ区切り）', DEFAULT_EXCLUDE]
      ]);
      configSheet.setColumnWidth(1, 240);
      configSheet.setColumnWidth(2, 560);
      configSheet.setFrozenRows(1);
    }

    const resultSheet = getOrCreateDigestSheet_(spreadsheet, DIGEST_RESULT_SHEET_NAME);
    if (resultSheet.getLastRow() === 0) {
      resultSheet.getRange(1, 1, 1, 6).setValues([
        ['抽出日時', '受信日', '差出人', '件名', '抽出した記述', '確認状況']
      ]);
      resultSheet.setColumnWidth(4, 300);
      resultSheet.setColumnWidth(5, 420);
      resultSheet.setFrozenRows(1);
    }

    const seenSheet = getOrCreateDigestSheet_(spreadsheet, SEEN_SHEET_NAME);
    if (seenSheet.getLastRow() === 0) {
      seenSheet.getRange(1, 1, 1, 2).setValues([['ハッシュ', '記録日時']]);
      seenSheet.setFrozenRows(1);
    }

    ui.alert(
      '初期設定が完了しました',
      '「' + CONFIG_SHEET_NAME + '」シートの検索条件とキーワードを必要に応じて調整してから、\n' +
      '「今すぐ抽出する」を実行してください。',
      ui.ButtonSet.OK
    );
  } catch (error) {
    ui.alert('初期設定に失敗しました', error.message, ui.ButtonSet.OK);
  }
}

/**
 * 求人メールを検索し、大学・学校法人の記述を抽出して通知します。
 */
function runMailDigest() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const config = readConfig_(spreadsheet);

  if (!config.query) {
    notifyOrThrowDigest_('「' + CONFIG_SHEET_NAME + '」シートがありません。先に「初期設定」を実行してください。');
    return;
  }

  const seen = readSeen_(spreadsheet);
  const threads = GmailApp.search(config.query, 0, MAX_THREADS);
  const findings = [];
  const now = new Date();

  threads.forEach(function(thread) {
    thread.getMessages().forEach(function(message) {
      const lines = extractJobLines_(message.getPlainBody(), config);
      if (lines.length === 0) {
        return;
      }

      const newLines = [];
      lines.forEach(function(line) {
        const hash = computeDigestHash_(line.text);
        if (seen[hash]) {
          return;
        }
        seen[hash] = true;
        newLines.push(line);
      });

      if (newLines.length > 0) {
        findings.push({
          date: message.getDate(),
          from: message.getFrom(),
          subject: message.getSubject(),
          lines: newLines
        });
      }
    });
  });

  if (findings.length > 0) {
    recordFindings_(spreadsheet, findings, now);
    saveSeen_(spreadsheet, findings, now);
  }

  pruneSeen_(spreadsheet, now);
  sendDigest_(findings, now);
}

/**
 * メール本文から求人らしい行を抜き出します。
 * 直後の行がURLの場合は併せて拾います。
 */
function extractJobLines_(body, config) {
  const rawLines = String(body).split('\n').map(function(line) {
    return line.replace(/[ \t　]+/g, ' ').trim();
  });

  const results = [];
  const seenInMail = {};

  for (let i = 0; i < rawLines.length; i++) {
    if (results.length >= MAX_LINES_PER_MAIL) {
      break;
    }

    const line = rawLines[i];
    if (line.length < 8 || line.length > 160) {
      continue;
    }
    if (seenInMail[line]) {
      continue;
    }
    if (!containsAnyWord_(line, config.include)) {
      continue;
    }
    if (containsAnyWord_(line, config.exclude)) {
      continue;
    }
    if (line.indexOf('http') === 0) {
      continue;
    }

    let url = '';
    for (let j = i + 1; j < Math.min(i + 4, rawLines.length); j++) {
      if (rawLines[j].indexOf('http') === 0) {
        url = rawLines[j];
        break;
      }
    }

    seenInMail[line] = true;
    results.push({ text: line, url: url });
  }

  return results;
}

function containsAnyWord_(text, words) {
  for (let i = 0; i < words.length; i++) {
    if (words[i] && text.indexOf(words[i]) !== -1) {
      return true;
    }
  }
  return false;
}

function readConfig_(spreadsheet) {
  const sheet = spreadsheet.getSheetByName(CONFIG_SHEET_NAME);
  if (!sheet || sheet.getLastRow() < 4) {
    return { query: '', include: [], exclude: [] };
  }

  const values = sheet.getRange(2, 2, 3, 1).getValues();
  return {
    query: String(values[0][0]).trim(),
    include: splitWords_(values[1][0]),
    exclude: splitWords_(values[2][0])
  };
}

function splitWords_(value) {
  return String(value).split(/[,、]/).map(function(word) {
    return word.trim();
  }).filter(function(word) {
    return word.length > 0;
  });
}

function readSeen_(spreadsheet) {
  const sheet = getOrCreateDigestSheet_(spreadsheet, SEEN_SHEET_NAME);
  const lastRow = sheet.getLastRow();
  const seen = {};

  if (lastRow < 2) {
    return seen;
  }

  sheet.getRange(2, 1, lastRow - 1, 1).getValues().forEach(function(row) {
    seen[String(row[0])] = true;
  });

  return seen;
}

function saveSeen_(spreadsheet, findings, now) {
  const sheet = getOrCreateDigestSheet_(spreadsheet, SEEN_SHEET_NAME);
  const rows = [];

  findings.forEach(function(finding) {
    finding.lines.forEach(function(line) {
      rows.push([computeDigestHash_(line.text), now]);
    });
  });

  if (rows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 2).setValues(rows);
  }
}

/**
 * 古い既出記録を削除し、シートの肥大化を防ぎます。
 */
function pruneSeen_(spreadsheet, now) {
  const sheet = getOrCreateDigestSheet_(spreadsheet, SEEN_SHEET_NAME);
  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    return;
  }

  const limit = now.getTime() - SEEN_RETENTION_DAYS * 24 * 60 * 60 * 1000;
  const values = sheet.getRange(2, 1, lastRow - 1, 2).getValues();
  const kept = values.filter(function(row) {
    const recorded = row[1] instanceof Date ? row[1].getTime() : 0;
    return recorded >= limit;
  });

  if (kept.length === values.length) {
    return;
  }

  sheet.getRange(2, 1, lastRow - 1, 2).clearContent();
  if (kept.length > 0) {
    sheet.getRange(2, 1, kept.length, 2).setValues(kept);
  }
}

function recordFindings_(spreadsheet, findings, now) {
  const sheet = getOrCreateDigestSheet_(spreadsheet, DIGEST_RESULT_SHEET_NAME);
  const rows = [];

  findings.forEach(function(finding) {
    finding.lines.forEach(function(line) {
      const text = line.url ? line.text + '\n' + line.url : line.text;
      rows.push([now, finding.date, finding.from, finding.subject, text, '未確認']);
    });
  });

  if (rows.length > 0) {
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, 6).setValues(rows);
  }
}

function computeDigestHash_(text) {
  const bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, text, Utilities.Charset.UTF_8);
  return bytes.map(function(byte) {
    return ('0' + (byte & 0xff).toString(16)).slice(-2);
  }).join('');
}

function sendDigest_(findings, now) {
  const address = Session.getActiveUser().getEmail();
  if (!address) {
    return;
  }

  const dateLabel = Utilities.formatDate(now, 'Asia/Tokyo', 'yyyy/MM/dd');
  const lines = [];
  let count = 0;

  findings.forEach(function(finding) {
    count += finding.lines.length;
  });

  lines.push('求人メールからの大学・学校法人案件（' + dateLabel + '）');
  lines.push('');

  if (findings.length === 0) {
    lines.push('■ 新しい該当案件はありませんでした。');
  } else {
    lines.push('■ 新規 ' + count + '件');
    lines.push('');
    findings.forEach(function(finding) {
      const received = Utilities.formatDate(finding.date, 'Asia/Tokyo', 'MM/dd');
      lines.push('【' + received + '｜' + finding.subject + '】');
      finding.lines.forEach(function(line) {
        lines.push('  ・' + line.text);
        if (line.url) {
          lines.push('    ' + line.url);
        }
      });
      lines.push('');
    });
    lines.push('※ 抽出は自動判定です。雇用形態・応募資格・締切は必ず求人票の本文で確認してください。');
  }

  const subject = findings.length > 0
    ? '【大学求人メール】' + dateLabel + ' 新規 ' + count + '件'
    : '【大学求人メール】' + dateLabel + ' 該当なし';

  MailApp.sendEmail(address, subject, lines.join('\n'));
}

function installDigestTrigger() {
  const ui = SpreadsheetApp.getUi();

  try {
    removeDigestTriggers_();
    ScriptApp.newTrigger('runMailDigest')
      .timeBased()
      .atHour(7)
      .everyDays(1)
      .create();

    ui.alert('自動抽出を設定しました', '毎日7時台に求人メールを確認し、結果をメールで送ります。', ui.ButtonSet.OK);
  } catch (error) {
    ui.alert('トリガーを設定できませんでした', error.message, ui.ButtonSet.OK);
  }
}

function removeDigestTrigger() {
  const ui = SpreadsheetApp.getUi();

  try {
    const count = removeDigestTriggers_();
    ui.alert('自動抽出を解除しました', '解除したトリガー: ' + count + '件', ui.ButtonSet.OK);
  } catch (error) {
    ui.alert('トリガーを解除できませんでした', error.message, ui.ButtonSet.OK);
  }
}

function removeDigestTriggers_() {
  let count = 0;

  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === 'runMailDigest') {
      ScriptApp.deleteTrigger(trigger);
      count++;
    }
  });

  return count;
}

function getOrCreateDigestSheet_(spreadsheet, name) {
  const sheet = spreadsheet.getSheetByName(name);
  return sheet ? sheet : spreadsheet.insertSheet(name);
}

function notifyOrThrowDigest_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (error) {
    throw new Error(message);
  }
}
