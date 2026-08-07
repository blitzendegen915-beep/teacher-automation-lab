/**
 * note 原稿の「AIっぽさ」チェッカー
 *
 * 使い方:
 *   node note/tools/ai-check.js note/drafts/001-google-forms-quiz-generator.md
 *   node note/tools/ai-check.js note/drafts/*.md
 *
 * ChatGPT等が出力した原稿を人間が書いたように直すために、
 * 機械的に拾える箇所だけを指摘します。判断は最後に人間がします。
 *
 * Node.js の標準機能だけで動きます。npm install は不要です。
 * 直し方は note/style-guide.md を参照してください。
 */

const fs = require("fs");
const path = require("path");

// ---------------------------------------------------------------------------
// 検出ルール
// ---------------------------------------------------------------------------

/** 原則すべて消す、AI原稿に特徴的な定型表現 */
const CLICHE_PATTERNS = [
  { re: /いかがでし(たか|ょうか)/g, fix: "消す。締めの挨拶は書かない" },
  { re: /ぜひ[^。]{0,20}(みてください|ください)/g, fix: "消す。読者に念を押さない" },
  { re: /と言え(るでしょう|ます)/g, fix: "言い切る。「〜です」" },
  { re: /ではないでしょうか/g, fix: "言い切る。逃げの語尾" },
  { re: /(近年|昨今|現代社会において|今日の社会において)/g, fix: "消す。書き出しの常套句" },
  { re: /(効率的に|効果的に|最適化)/g, fix: "具体的に何がどうなるかを書く" },
  { re: /を活用(して|し|します)/g, fix: "「を使って」" },
  { re: /を実現(する|します|できます)/g, fix: "「〜できます」「〜になります」" },
  { re: /(劇的に|飛躍的に|革新的な|画期的な)/g, fix: "誇張。消すか数字にする" },
  { re: /(ポイント|コツ|理由|方法|手順)[はを][0-9０-９一二三四五六七八九]+つ/g, fix: "数を先に宣言しない。3つに揃えるのがAIの癖" },
  { re: /以下の[0-9０-９一二三四五六七八九]+つ/g, fix: "数を先に宣言しない" },
  { re: /ご紹介し(ます|ました)/g, fix: "「紹介します」。過剰敬語" },
  { re: /まとめると/g, fix: "要約で締めない" },
  { re: /さまざまな|様々な/g, fix: "何と何かを具体的に書く" },
  { re: /(と思われます|と考えられます)/g, fix: "言い切るか、誰がそう考えるのかを書く" },
];

/** 冗長表現。置換すれば済むもの */
const VERBOSE_PATTERNS = [
  { re: /することができます/g, fix: "「できます」" },
  { re: /することが可能です/g, fix: "「できます」" },
  { re: /を行(う|います|った|い、|うこと)/g, fix: "「〜する」。名詞化をほどく" },
  { re: /という点(において|で)/g, fix: "「〜は」" },
  { re: /における/g, fix: "「〜の」" },
  { re: /する上で/g, fix: "「〜するとき」" },
  { re: /となっています/g, fix: "「です」" },
  { re: /していきましょう/g, fix: "「します」。指導口調を外す" },
  { re: /必要があります/g, fix: "「要ります」「〜してください」" },
  { re: /(私たちは|私たちが|あなたが|あなたは|あなたの)/g, fix: "主語を落とす。英語直訳の癖" },
  { re: /に関して(は|、)/g, fix: "「〜は」" },
  { re: /することにより/g, fix: "「〜すると」" },
];

/** 文頭に置かれると翻訳調になる接続詞 */
const CONNECTIVES = [
  "また、", "さらに、", "そして、", "一方で、", "加えて、", "しかしながら、",
  "したがって、", "そのため、", "つまり、", "このように、",
  "まず、", "次に、", "最後に、", // 「3つのポイント」型の順序づけ。AI原稿に頻出
];

const LONG_SENTENCE = 60; // 字。これを超えたら分割候補
const SHORT_SENTENCE = 10; // 字。これ以下の文が無いと単調
const CONNECTIVE_RATIO_LIMIT = 0.1; // 文頭接続詞が1割を超えると翻訳調

// ---------------------------------------------------------------------------
// 本文の取り出し
// ---------------------------------------------------------------------------

/**
 * コードブロック・メタ情報・HTMLコメントを除いた「地の文」だけを取り出します。
 * 行番号を保つため、除外した行は空文字に置き換えます。
 */
function extractProse(source) {
  const lines = source.split("\n");
  const prose = [];
  let inCodeBlock = false;
  let inComment = false;

  lines.forEach(function (line) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      prose.push("");
      return;
    }
    if (inCodeBlock) {
      prose.push("");
      return;
    }
    if (trimmed.includes("<!--")) inComment = true;
    if (inComment) {
      if (trimmed.includes("-->")) inComment = false;
      prose.push("");
      return;
    }
    // 見出し記号・引用記号・箇条書き記号は落とし、文字だけ残す
    prose.push(line.replace(/^\s*(#{1,6}|>|[-*+]|\d+\.)\s*/, ""));
  });

  return prose;
}

/** 「。」で文に割り、各文に行番号を持たせます */
function splitSentences(proseLines) {
  const sentences = [];

  proseLines.forEach(function (line, index) {
    const lineNumber = index + 1;
    const text = line.trim();
    if (!text) return;
    if (/^[|─=+\s]+$/.test(text)) return; // 罫線・表の区切り

    text
      .split(/(?<=。)/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean)
      .forEach(function (s) {
        sentences.push({ line: lineNumber, text: s });
      });
  });

  return sentences;
}

// ---------------------------------------------------------------------------
// 検査
// ---------------------------------------------------------------------------

function findPatterns(proseLines, patterns) {
  const hits = [];

  proseLines.forEach(function (line, index) {
    patterns.forEach(function (rule) {
      rule.re.lastIndex = 0;
      let match;
      while ((match = rule.re.exec(line)) !== null) {
        hits.push({ line: index + 1, word: match[0], fix: rule.fix });
        if (match.index === rule.re.lastIndex) rule.re.lastIndex++;
      }
    });
  });

  return hits;
}

function checkRhythm(sentences) {
  const lengths = sentences.map(function (s) { return s.text.length; });
  const longOnes = sentences.filter(function (s) { return s.text.length > LONG_SENTENCE; });
  const shortOnes = sentences.filter(function (s) { return s.text.length <= SHORT_SENTENCE; });

  const average = lengths.length
    ? lengths.reduce(function (a, b) { return a + b; }, 0) / lengths.length
    : 0;

  // ばらつき（標準偏差）。小さいほど機械的
  const variance = lengths.length
    ? lengths.reduce(function (a, b) { return a + Math.pow(b - average, 2); }, 0) / lengths.length
    : 0;
  const deviation = Math.sqrt(variance);

  // 同じ文末が3つ以上続く箇所
  const endingRuns = [];
  let runStart = 0;
  for (let i = 1; i <= sentences.length; i++) {
    const prev = endingOf(sentences[i - 1].text);
    const curr = i < sentences.length ? endingOf(sentences[i].text) : null;
    if (curr !== prev || i === sentences.length) {
      const runLength = i - runStart;
      if (prev && runLength >= 3) {
        endingRuns.push({ line: sentences[runStart].line, ending: prev, count: runLength });
      }
      runStart = i;
    }
  }

  const connectiveHits = sentences.filter(function (s) {
    return CONNECTIVES.some(function (c) { return s.text.startsWith(c); });
  });

  return { average, deviation, longOnes, shortOnes, endingRuns, connectiveHits };
}

function endingOf(text) {
  const match = text.match(/(です。|ます。|ました。|でした。|ません。|である。)$/);
  return match ? match[1] : null;
}

/**
 * 見出しと箇条書きの「型の揃いすぎ」を見ます。
 * AIは見出しを同じ品詞で揃え、箇条書きを3つか5つに揃える癖があります。
 */
function checkStructure(source) {
  const lines = source.split("\n");
  const headings = [];
  const listSizes = [];
  let inCodeBlock = false;
  let currentList = 0;

  lines.forEach(function (line, index) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      inCodeBlock = !inCodeBlock;
      return;
    }
    if (inCodeBlock) return;

    const heading = trimmed.match(/^(#{2,6})\s+(.+)$/);
    if (heading) {
      headings.push({ line: index + 1, text: heading[2].trim() });
    }

    if (/^\s*([-*+]|\d+\.)\s+\S/.test(line)) {
      currentList++;
    } else if (trimmed === "") {
      if (currentList > 0) listSizes.push(currentList);
      currentList = 0;
    }
  });
  if (currentList > 0) listSizes.push(currentList);

  // 最後の見出しが要約系か
  const last = headings[headings.length - 1];
  const closingSummary = last && /^(まとめ|おわりに|終わりに|最後に|結論)$/.test(last.text.replace(/[【】\s]/g, ""))
    ? last
    : null;

  // 見出しがすべて体言止めか（＝形が揃いすぎ）
  const nominal = headings.filter(function (h) {
    return !/(です|ます|ました|でした|か|？|\?|。)$/.test(h.text);
  });
  const allNominal = headings.length >= 3 && nominal.length === headings.length;

  // 3つ・5つに揃った箇条書き
  const tidyLists = listSizes.filter(function (n) { return n === 3 || n === 5; });

  return { headings, closingSummary, allNominal, listSizes, tidyLists };
}

function checkConcreteness(proseLines) {
  const body = proseLines.join("\n");
  const digits = (body.match(/[0-9０-９]+/g) || []).length;
  const charCount = body.replace(/\s/g, "").length;
  return { digits, charCount };
}

// ---------------------------------------------------------------------------
// 出力
// ---------------------------------------------------------------------------

function printSection(title, note) {
  console.log("");
  console.log("【" + title + "】" + (note ? "  " + note : ""));
}

function printHits(hits, limit) {
  const shown = hits.slice(0, limit);
  shown.forEach(function (h) {
    console.log("  L" + String(h.line).padEnd(5) + h.word.padEnd(16) + "→ " + h.fix);
  });
  if (hits.length > shown.length) {
    console.log("  … ほか " + (hits.length - shown.length) + " 件");
  }
}

function lineList(items, limit) {
  const lines = items.slice(0, limit).map(function (s) { return "L" + s.line; });
  const rest = items.length - lines.length;
  return lines.join(", ") + (rest > 0 ? " ほか" + rest + "件" : "");
}

function checkFile(filePath) {
  let source;
  try {
    source = fs.readFileSync(filePath, "utf8");
  } catch (err) {
    console.error("エラー: " + filePath + " を読み込めませんでした。");
    console.error(err.message);
    return 1;
  }

  const proseLines = extractProse(source);
  const sentences = splitSentences(proseLines);

  console.log("");
  console.log("=".repeat(64));
  console.log(path.basename(filePath));
  console.log("=".repeat(64));

  if (sentences.length === 0) {
    console.log("地の文が見つかりませんでした。コードブロックだけのファイルかもしれません。");
    return 0;
  }

  const cliches = findPatterns(proseLines, CLICHE_PATTERNS);
  const verbose = findPatterns(proseLines, VERBOSE_PATTERNS);
  const rhythm = checkRhythm(sentences);
  const structure = checkStructure(source);
  const concrete = checkConcreteness(proseLines);

  console.log(
    "本文 " + concrete.charCount.toLocaleString() + "字 / " +
    sentences.length + "文 / 平均 " + rhythm.average.toFixed(1) + "字"
  );

  // --- 定型表現 ---
  if (cliches.length > 0) {
    printSection("要修正：AIっぽい定型表現", cliches.length + "件");
    printHits(cliches, 20);
  } else {
    printSection("要修正：AIっぽい定型表現", "なし");
  }

  // --- 冗長表現 ---
  if (verbose.length > 0) {
    printSection("要検討：冗長表現・翻訳調", verbose.length + "件");
    printHits(verbose, 20);
  } else {
    printSection("要検討：冗長表現・翻訳調", "なし");
  }

  // --- リズム ---
  printSection("文体のリズム");

  if (rhythm.shortOnes.length === 0) {
    console.log("  ✗ 10字以下の短い文が1つもありません。これが最大のAI臭です。");
    console.log("    短い言い切りを数か所に入れてください。例:「この作業をやめました。」");
  } else {
    console.log("  ✓ 短い文 " + rhythm.shortOnes.length + "件（" + lineList(rhythm.shortOnes, 6) + "）");
  }

  if (rhythm.deviation < 15) {
    console.log("  ✗ 文の長さのばらつきが小さい（標準偏差 " + rhythm.deviation.toFixed(1) + "）。均一＝機械的に見えます。");
    console.log("    目安は20以上。長い文を割り、短い文を足してください。");
  } else {
    console.log("  ✓ 文の長さのばらつき 標準偏差 " + rhythm.deviation.toFixed(1));
  }

  if (rhythm.longOnes.length > 0) {
    console.log("  ・" + LONG_SENTENCE + "字超の文 " + rhythm.longOnes.length + "件（" + lineList(rhythm.longOnes, 8) + "）");
    console.log("    読点で2文に割れないか見てください。");
  }

  if (rhythm.endingRuns.length > 0) {
    console.log("  ・同じ文末の連続 " + rhythm.endingRuns.length + "か所");
    rhythm.endingRuns.slice(0, 6).forEach(function (r) {
      console.log("    L" + String(r.line).padEnd(5) + "「" + r.ending + "」が" + r.count + "連続");
    });
    console.log("    体言止め・過去形・疑問形を1つ混ぜて崩してください。");
  }

  const ratio = rhythm.connectiveHits.length / sentences.length;
  if (ratio > CONNECTIVE_RATIO_LIMIT) {
    console.log("  ✗ 文頭の接続詞が多い " + rhythm.connectiveHits.length + "/" + sentences.length +
      "（" + (ratio * 100).toFixed(1) + "%）。1割を超えると翻訳調に見えます。");
    console.log("    " + lineList(rhythm.connectiveHits, 8));
    console.log("    「また、」「さらに、」は大半が削れます。");
  }

  // --- 構造 ---
  printSection("構造");

  if (structure.closingSummary) {
    console.log("  ✗ L" + structure.closingSummary.line + " 最後の見出しが「" + structure.closingSummary.text + "」です。");
    console.log("    要約で締めるのはAIの型。言い切り・引っかかり・次への振りで終わらせてください。");
  } else {
    console.log("  ✓ 要約見出しで終わっていません");
  }

  if (structure.allNominal) {
    console.log("  ✗ 見出し" + structure.headings.length + "個がすべて体言止めです。形が揃いすぎています。");
    console.log("    疑問形（「なぜ作ったか」）や会話文を混ぜて崩してください。");
  } else {
    console.log("  ✓ 見出しの形はばらけています（" + structure.headings.length + "個）");
  }

  if (structure.listSizes.length >= 2 && structure.tidyLists.length === structure.listSizes.length) {
    console.log("  ✗ 箇条書きが全部3つか5つです（" + structure.listSizes.join(", ") + "）。");
    console.log("    2つでも6つでもいい。そもそも地の文で書ける箇所もあります。");
  }

  // --- 具体性 ---
  printSection("具体性");
  const per1000 = concrete.charCount ? (concrete.digits / concrete.charCount) * 1000 : 0;
  console.log("  数字の出現 " + concrete.digits + "回（1000字あたり " + per1000.toFixed(1) + "回）");
  if (per1000 < 3) {
    console.log("  ✗ 数字が少なすぎます。「かなり時間がかかる」ではなく「20分」と書いてください。");
    console.log("    ただし、思い出せない数字を作らないこと。");
  }

  // --- 手作業で確認する部分 ---
  printSection("ここからは手で見る");
  console.log("  □ 失敗した話・うまくいかなかった話が入っているか");
  console.log("  □ 各セクションに、自分にしか書けない一文があるか");
  console.log("  □ 最後が要約で終わっていないか");
  console.log("  □ 見出しの形が揃いすぎていないか");
  console.log("  □ 1行だけの段落があるか");
  console.log("  □ 音読して詰まらないか");
  console.log("");
  console.log("  直し方: note/style-guide.md");

  return cliches.length > 0 ? 1 : 0;
}

// ---------------------------------------------------------------------------
// 実行
// ---------------------------------------------------------------------------

function main() {
  const files = process.argv.slice(2);

  if (files.length === 0) {
    console.error("使い方: node note/tools/ai-check.js <原稿.md> [<原稿.md> ...]");
    process.exit(2);
  }

  let worst = 0;
  files.forEach(function (file) {
    const code = checkFile(file);
    if (code > worst) worst = code;
  });

  console.log("");
  process.exit(worst);
}

main();
