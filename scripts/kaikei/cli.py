"""合宿会計CLI。

    python3 -m scripts.kaikei <command>

commands: check / headcount / balance / settle / report
"""
from __future__ import annotations

import argparse
import sys

from . import checks, model, reports
from .checks import date_ja

SEVERITY_MARK = {"error": "❌", "warn": "⚠️", "info": "✅"}
SEVERITY_LABEL = {"error": "エラー", "warn": "要確認", "info": "OK"}
SEVERITY_ORDER = ["error", "warn", "info"]


def cmd_check(camp_id: str) -> int:
    camp = model.load(camp_id)
    findings = checks.run_all(camp)

    print(f"=== {camp.name} 会計チェック結果 ===\n")
    has_error = False
    for sev in SEVERITY_ORDER:
        items = [f for f in findings if f.severity == sev]
        if not items:
            continue
        print(f"--- {SEVERITY_MARK[sev]} {SEVERITY_LABEL[sev]}（{len(items)}件） ---")
        for f in items:
            mark = SEVERITY_MARK[sev]
            for i, line in enumerate(f.message.split("\n")):
                prefix = f"{mark} " if i == 0 else "   "
                print(f"{prefix}{line}")
        print()
        if sev == "error":
            has_error = True

    if has_error:
        print("❌ エラーがあります。会計報告書を配布する前に解決してください。")
        return 1
    print("✅ エラーはありません。⚠️の項目は内容を確認のうえ対応してください。")
    return 0


def cmd_headcount(camp_id: str) -> int:
    camp = model.load(camp_id)
    hc = model.headcount(camp)
    print(f"=== {camp.name} 日別人数表 ===\n")
    header = f"{'日付':<10}{'朝食':>6}{'昼食':>6}{'夕食':>6}{'宿泊':>6}{'申告済':>8}"
    print(header)
    print("-" * len(header))
    for d in camp.date_range():
        v = hc["per_date"][d]
        submitted = camp.submitted_headcount.get(d)
        print(
            f"{date_ja(d):<10}"
            f"{model.fmt_meal(v['breakfast']):>6}"
            f"{model.fmt_meal(v['lunch']):>6}"
            f"{model.fmt_meal(v['dinner']):>6}"
            f"{model.fmt_meal(v['lodging']):>6}"
            f"{(submitted if submitted is not None else '－'):>8}"
        )
    t = hc["totals"]
    print("-" * len(header))
    print(f"{'合計(延べ)':<10}{t['breakfast']:>6}{t['lunch']:>6}{t['dinner']:>6}{t['lodging']:>6}")
    return 0


def cmd_balance(camp_id: str) -> int:
    camp = model.load(camp_id)
    inc = model.income(camp)
    bal = model.balance(camp)
    settle = model.settlement(camp)

    print(f"=== {camp.name} 収支サマリ ===\n")
    print(f"収入合計　　: ¥{bal['income_total']:,}（{len(inc['lines'])}名）")
    print(f"支出合計　　: ¥{bal['expense_total']:,}")
    print(f"  内訳: ホテル ¥{bal['hotel_invoice_total']:,} ／ バス ¥{bal['bus_quote']:,} ／ その他支出 ¥{bal['expenses_total']:,}")
    print(f"差引残額　　: ¥{bal['diff']:,}")
    print()
    print(f"未精算の立替金合計: ¥{settle['grand_total']:,}")
    for payer, info in settle["by_payer"].items():
        print(f"  {payer}: ¥{info['total']:,}（{len(info['items'])}件）")
    return 0


def cmd_settle(camp_id: str) -> int:
    camp = model.load(camp_id)
    path = reports.write_settlement_xlsx(camp=camp)
    print(f"✅ 立替金精算表を出力しました: {path}")
    return 0


def cmd_report(camp_id: str) -> int:
    camp = model.load(camp_id)
    p1 = reports.write_camp_report_xlsx(camp=camp)
    p2 = reports.write_headcount_xlsx(camp=camp)
    print(f"✅ 収支報告書を出力しました: {p1}")
    print(f"✅ 日別人数表を出力しました: {p2}")
    return 0


COMMANDS = {
    "check": cmd_check,
    "headcount": cmd_headcount,
    "balance": cmd_balance,
    "settle": cmd_settle,
    "report": cmd_report,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m scripts.kaikei", description="ラグビー部 合宿会計ツール")
    parser.add_argument("command", choices=list(COMMANDS.keys()))
    parser.add_argument("--camp", default="2026-summer", help="合宿ID（既定: 2026-summer）")
    args = parser.parse_args(argv)
    return COMMANDS[args.command](args.camp)


if __name__ == "__main__":
    sys.exit(main())
