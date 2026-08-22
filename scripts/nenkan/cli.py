"""年間業務CLI。

    python3 -m scripts.nenkan <command>

commands: now(既定) / month <1-12> / list / done <task_id> / undone <task_id>
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from typing import Optional

from . import model


# ---------------------------------------------------------------------------
# 表示ヘルパー
# ---------------------------------------------------------------------------


def _task_lines(t: model.Task) -> list:
    lines = [f"・{t.title}（{t.id}）"]
    meta = [f"担当: {t.owner}"]
    if t.money:
        meta.append(f"予算区分: {t.money}（{t.money_ja}）")
    if t.due:
        meta.append(f"期限: {t.due}")
    lines.append("    " + " ／ ".join(meta))
    if t.skill:
        lines.append(f"    関連スキル: {t.skill}")
    if t.note:
        for nl in t.note.split("\n"):
            lines.append(f"    {nl}")
    return lines


def _print_tasks(tasks: list) -> None:
    for t in tasks:
        for line in _task_lines(t):
            print(line)
        print()


# ---------------------------------------------------------------------------
# コマンド
# ---------------------------------------------------------------------------


def cmd_now(today: Optional[date] = None) -> int:
    today = today or date.today()
    tasks = model.load_tasks()
    fy = model.fiscal_year(today)

    cur = model.current_month_tasks(tasks, today)
    overdue = model.overdue_tasks(tasks, today)
    nxt = model.next_month_tasks(tasks, today)
    nm = model.next_month(today.month)

    print(f"=== {today.isoformat()} 時点の年間業務（{fy}年度） ===\n")

    print(f"--- 今月やること（{today.month}月） ---")
    if cur:
        _print_tasks(cur)
    else:
        print("今月の新規タスクはありません。\n")

    print(f"--- ⚠️ 未完了のまま過ぎた業務（{len(overdue)}件） ---")
    if overdue:
        _print_tasks(overdue)
    else:
        print("未完了のまま過ぎた業務はありません。\n")

    print(f"--- 来月の予定（{nm}月） ---")
    if nxt:
        _print_tasks(nxt)
    else:
        print("来月の新規タスクはありません。\n")

    return 0


def cmd_month(value: int) -> int:
    if not 1 <= value <= 12:
        print(f"❌ 月は1〜12で指定してください（指定値: {value}）。")
        return 1

    tasks = model.load_tasks()
    matched = model.tasks_for_month(tasks, value)

    print(f"=== {value}月の業務 ===\n")
    if matched:
        _print_tasks(matched)
    else:
        print("この月に該当する業務はありません。")
    return 0


def cmd_list() -> int:
    tasks = model.load_tasks()
    grouped = model.group_by_month(tasks)
    months_order = list(range(4, 13)) + list(range(1, 4))  # 4月始まりの年度順

    print("=== 年間業務一覧（年度順・4月始まり） ===\n")
    for m in months_order:
        items = grouped[m]
        print(f"--- {m}月 ---")
        if items:
            _print_tasks(items)
        else:
            print("（該当なし）\n")
    return 0


def cmd_done(task_id: str, on_str: Optional[str], note: str, today: Optional[date] = None) -> int:
    today = today or date.today()
    tasks = model.load_tasks()

    if on_str:
        try:
            on = date.fromisoformat(on_str)
        except ValueError:
            print(f"❌ 日付 '{on_str}' の形式が不正です。YYYY-MM-DD の形式で指定してください。")
            return 1
    else:
        on = today

    try:
        row = model.mark_done(task_id, tasks, on, note)
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    t = model.task_by_id(tasks, task_id)
    print(f"✅ 「{t.title}」を{row['fiscal_year']}年度分の完了として記録しました（完了日: {row['completed_on']}）。")
    if note:
        print(f"  備考: {note}")
    return 0


def cmd_undone(task_id: str, today: Optional[date] = None) -> int:
    today = today or date.today()
    tasks = model.load_tasks()
    t = model.task_by_id(tasks, task_id)
    if t is None:
        print(f"❌ '{task_id}' という業務IDは annual-tasks.yml にありません。")
        return 1

    fy = model.fiscal_year(today)
    removed = model.mark_undone(task_id, fy)
    if not removed:
        print(f"「{t.title}」の{fy}年度分の完了記録は見つかりませんでした。")
        return 0

    print(f"✅ 「{t.title}」の{fy}年度分の完了記録を取り消しました。")
    return 0


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m scripts.nenkan", description="ラグビー部 年間業務ツール")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("now", help="今月やること・期限超過・来月の予定を表示する（既定）")

    month_p = sub.add_parser("month", help="指定した月の業務を表示する")
    month_p.add_argument("value", type=int, help="1〜12の月番号")

    sub.add_parser("list", help="全業務を年度順（4月始まり）に一覧表示する")

    done_p = sub.add_parser("done", help="業務を完了として記録する")
    done_p.add_argument("task_id", help="annual-tasks.yml のid")
    done_p.add_argument("--on", help="完了日 YYYY-MM-DD（省略時は今日）")
    done_p.add_argument("--note", default="", help="備考")

    undone_p = sub.add_parser("undone", help="今年度分の完了記録を取り消す")
    undone_p.add_argument("task_id", help="annual-tasks.yml のid")

    args = parser.parse_args(argv)
    command = args.command or "now"

    if command == "now":
        return cmd_now()
    if command == "month":
        return cmd_month(args.value)
    if command == "list":
        return cmd_list()
    if command == "done":
        return cmd_done(args.task_id, args.on, args.note)
    if command == "undone":
        return cmd_undone(args.task_id)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
