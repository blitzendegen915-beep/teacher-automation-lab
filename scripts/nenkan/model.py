"""データ読み込みと年度・進捗計算のコアロジック。

年度計算
--------
日本の学校の年度は4月始まり。ある日付 d の年度(fiscal_year)は、
    d.month >= 4 なら d.year、そうでなければ d.year - 1
1〜3月の日付は「前年の年度」に属する(例: 2027-01-15 は fiscal_year=2026)。

年度内の月の並び順は 4月=0, 5月=1, ..., 3月=11 になる
(fiscal_month_index)。「今月より年度内で前の月」＝「期限超過」の判定に使う。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "rugby"

MONEY_JA = {"A": "校友会予算", "B": "父母会予算", "C": "都度徴収"}

LOG_FIELDNAMES = ["task_id", "fiscal_year", "completed_on", "note"]

FISCAL_START_MONTH = 4


# ---------------------------------------------------------------------------
# 年度計算
# ---------------------------------------------------------------------------


def fiscal_year(d: date) -> int:
    """4月始まりの年度を返す。1〜3月の日付は前年の年度になる。"""
    return d.year if d.month >= FISCAL_START_MONTH else d.year - 1


def fiscal_month_index(month: int) -> int:
    """年度内での月の並び順を返す(4月=0 ... 3月=11)。"""
    return (month - FISCAL_START_MONTH) % 12


def next_month(month: int) -> int:
    """来月の月番号を返す(12月の次は1月)。"""
    return month % 12 + 1


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class Task:
    id: str
    title: str
    months: list  # 1-12の整数のリスト
    owner: str
    money: Optional[str]
    note: str
    skill: Optional[str]
    due: Optional[str]

    @property
    def money_ja(self) -> str:
        return MONEY_JA.get(self.money, self.money) if self.money else ""


def _expand_months(value) -> list:
    if isinstance(value, list):
        return list(value)
    return [value]


def load_tasks(path: Optional[Path] = None) -> list:
    path = path or (DATA_DIR / "annual-tasks.yml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    tasks = []
    for t in raw["tasks"]:
        tasks.append(
            Task(
                id=t["id"],
                title=t["title"],
                months=_expand_months(t["month"]),
                owner=t.get("owner", ""),
                money=t.get("money"),
                note=(t.get("note") or "").strip(),
                skill=t.get("skill"),
                due=t.get("due"),
            )
        )
    return tasks


def task_by_id(tasks: list, task_id: str) -> Optional[Task]:
    return next((t for t in tasks if t.id == task_id), None)


# ---------------------------------------------------------------------------
# 完了記録(task-log-<fiscal_year>.csv)
# ---------------------------------------------------------------------------


def log_path(fy: int) -> Path:
    return DATA_DIR / f"task-log-{fy}.csv"


def load_log(fy: int) -> list:
    """指定年度の完了記録CSVを読み込む(存在しなければ空リスト)。"""
    path = log_path(fy)
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_log(fy: int, rows: list) -> None:
    path = log_path(fy)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def completed_task_ids(fy: int) -> set:
    """指定年度で完了記録のある task_id の集合を返す。"""
    return {r["task_id"] for r in load_log(fy) if str(r.get("fiscal_year", "")).strip() == str(fy)}


def mark_done(task_id: str, tasks: list, on: date, note: str = "") -> dict:
    """task-log-<fy>.csv に1行追加する。

    on の年度に対して重複がある場合は ValueError を送出し、ファイルには一切触れない。
    task_id が annual-tasks.yml に存在しない場合も ValueError。
    """
    if task_by_id(tasks, task_id) is None:
        raise ValueError(f"'{task_id}' という業務IDは annual-tasks.yml にありません。")

    fy = fiscal_year(on)
    rows = load_log(fy)
    if any(r["task_id"] == task_id and str(r.get("fiscal_year", "")).strip() == str(fy) for r in rows):
        raise ValueError(
            f"'{task_id}' は{fy}年度分ですでに完了記録があります。"
            "修正する場合は先に undone で取り消してください。"
        )

    row = {"task_id": task_id, "fiscal_year": str(fy), "completed_on": on.isoformat(), "note": note}
    rows.append(row)
    rows.sort(key=lambda r: (r["completed_on"], r["task_id"]))
    _write_log(fy, rows)
    return row


def mark_undone(task_id: str, fy: int) -> list:
    """指定年度の完了記録から該当行を削除する。削除した行のリストを返す(0件ならファイル未変更)。"""
    rows = load_log(fy)
    removed = [r for r in rows if r["task_id"] == task_id and str(r.get("fiscal_year", "")).strip() == str(fy)]
    if not removed:
        return removed
    remaining = [r for r in rows if not (r["task_id"] == task_id and str(r.get("fiscal_year", "")).strip() == str(fy))]
    _write_log(fy, remaining)
    return removed


# ---------------------------------------------------------------------------
# 「今やるべきこと」の算出
# ---------------------------------------------------------------------------


def current_month_tasks(tasks: list, today: date) -> list:
    """今月が対象月に含まれ、かつこの年度でまだ完了していない業務。"""
    fy = fiscal_year(today)
    completed = completed_task_ids(fy)
    return [t for t in tasks if today.month in t.months and t.id not in completed]


def overdue_tasks(tasks: list, today: date) -> list:
    """今年度内で今月より前の月が対象で、まだ完了していない業務。

    年度内の並び順(fiscal_month_index)で比較するため、
    「4月の業務が8月時点で未完了」は超過扱いになるが、
    「2月の業務が8月時点で未完了」は(まだ来ていないので)超過扱いにならない。
    """
    fy = fiscal_year(today)
    completed = completed_task_ids(fy)
    cur_idx = fiscal_month_index(today.month)
    result = [
        t
        for t in tasks
        if t.id not in completed and any(fiscal_month_index(m) < cur_idx for m in t.months)
    ]
    result.sort(key=lambda t: min(fiscal_month_index(m) for m in t.months))
    return result


def next_month_tasks(tasks: list, today: date) -> list:
    """来月が対象月に含まれ、かつこの年度でまだ完了していない業務。"""
    fy = fiscal_year(today)
    completed = completed_task_ids(fy)
    nm = next_month(today.month)
    return [t for t in tasks if nm in t.months and t.id not in completed]


def tasks_for_month(tasks: list, month: int) -> list:
    """指定した暦月が対象の業務をすべて返す(完了状態は問わない)。"""
    return [t for t in tasks if month in t.months]


def group_by_month(tasks: list) -> dict:
    """月ごとにグルーピングする。キーは1〜12の月番号。"""
    grouped: dict = {m: [] for m in range(1, 13)}
    for t in tasks:
        for m in t.months:
            grouped[m].append(t)
    return grouped
