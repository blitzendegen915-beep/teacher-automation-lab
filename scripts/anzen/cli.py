"""安全調査CLI。

    python3 -m scripts.anzen <command>

commands: check / generate
"""
from __future__ import annotations

import argparse
import sys

from . import model, reports

PII_WARNING = (
    "\n⚠️ 生成した文書には要配慮個人情報（アレルギー・既往症等）が含まれます。\n"
    "   共有ドライブ等に置かず、合宿終了後は必ず回収して廃棄してください。"
)


def _load(survey_path) -> model.SurveyResult:
    return model.load_survey(survey_path)


def _print_survey_summary(result: model.SurveyResult) -> None:
    print(f"回答件数（CSV行数）: {result.total_rows}件")
    print(f"回答者数（重複解決後）: {len(result.responses)}名")
    if result.duplicates:
        print(f"重複回答: {len(result.duplicates)}名分（{result.dropped_count}件を破棄・最新のタイムスタンプを採用）")
        for d in result.duplicates:
            print(f"  ・{d.name}（{d.count}件 → 最新の1件を採用）")
    else:
        print("重複回答: なし")
    if result.missing_fields:
        print(f"⚠️ CSVから列を特定できなかった項目: {', '.join(result.missing_fields)}")


def cmd_check(args) -> int:
    try:
        result = _load(args.survey)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 安全調査CSVの読み込みに失敗しました: {e}")
        return 1

    print("=== 安全調査 回収状況チェック ===\n")
    _print_survey_summary(result)

    try:
        roster = model.load_roster()
    except FileNotFoundError as e:
        print(f"\n❌ 名簿の読み込みに失敗しました: {e}")
        return 1

    non_responders = model.find_non_responders(roster, result.responses)
    print(f"\n名簿人数: {len(roster)}名")
    if non_responders:
        print(f"⚠️ 未回答: {len(non_responders)}名")
        grouped = model.group_roster_by_grade_class(non_responders)
        for (grade, klass), students in grouped.items():
            names = "、".join(s.name for s in students)
            print(f"  ・{grade}年{klass}組: {names}")
    else:
        print("✅ 未回答者はいません。名簿全員が回答済みです。")

    allergy_count = sum(1 for r in result.responses if r.has_allergy)
    medical_count = sum(1 for r in result.responses if r.has_medical)
    print(f"\nアレルギーの申告あり: {allergy_count}名")
    print(f"病歴・傷歴の申告あり: {medical_count}名")

    if non_responders:
        print("\n⚠️ 合宿前に未回答者への督促が必要です。")
    return 0


def cmd_generate(args) -> int:
    try:
        result = _load(args.survey)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ 安全調査CSVの読み込みに失敗しました: {e}")
        return 1

    print("=== 安全調査ドキュメント生成 ===\n")
    _print_survey_summary(result)

    try:
        roster = model.load_roster()
        non_responders = model.find_non_responders(roster, result.responses)
    except FileNotFoundError as e:
        print(f"⚠️ 名簿の読み込みに失敗したため未回答者一覧はスキップします: {e}")
        non_responders = []

    print()
    p1 = reports.write_emergency_sheet(result.responses)
    print(f"✅ 緊急時対応シートを出力しました: {p1}")
    p2 = reports.write_allergy_list(result.responses)
    print(f"✅ アレルギー一覧を出力しました: {p2}")
    p3 = reports.write_non_responders(non_responders)
    print(f"✅ 未回答者一覧を出力しました: {p3}")

    print(PII_WARNING)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m scripts.anzen", description="ラグビー部 安全調査ツール")
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="回収状況（回答数・重複・未回答・アレルギー/病歴件数）を確認する")
    check_p.add_argument("--survey", default=None, help="安全調査CSVのパス（既定: data/rugby/survey-sample.csv）")

    gen_p = sub.add_parser("generate", help="緊急時対応シート・アレルギー一覧・未回答者一覧を生成する")
    gen_p.add_argument("--survey", default=None, help="安全調査CSVのパス（既定: data/rugby/survey-sample.csv）")

    args = parser.parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    return cmd_generate(args)


if __name__ == "__main__":
    sys.exit(main())
