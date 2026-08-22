"""scripts.nenkan の単体テスト。pytest不要、`python3 tests/test_nenkan.py` で実行できる。"""
import shutil
import sys
import tempfile
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.nenkan import model as m  # noqa: E402
from scripts.nenkan import cli  # noqa: E402

PASS = 0
FAIL = 0


def check(label, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"OK   {label}")
    else:
        FAIL += 1
        print(f"FAIL {label}")


def main():
    # -- 年度計算(fiscal_year): 4月境界とまたぎ、1月の扱い ---------------------

    check("2026-04-01は2026年度", m.fiscal_year(date(2026, 4, 1)) == 2026)
    check("2026-03-31は2025年度(4月境界の前日)", m.fiscal_year(date(2026, 3, 31)) == 2025)
    check("2027-01-15は2026年度(1月は前年度)", m.fiscal_year(date(2027, 1, 15)) == 2026)
    check("2026-08-22は2026年度", m.fiscal_year(date(2026, 8, 22)) == 2026)
    check("2026-12-31は2026年度", m.fiscal_year(date(2026, 12, 31)) == 2026)

    # -- 年度内の月順(fiscal_month_index): 4月=0, 3月=11 -----------------------

    check("4月の年度内インデックスは0", m.fiscal_month_index(4) == 0)
    check("3月の年度内インデックスは11", m.fiscal_month_index(3) == 11)
    check("8月の年度内インデックスは4", m.fiscal_month_index(8) == 4)
    check("1月の年度内インデックスは9", m.fiscal_month_index(1) == 9)

    # -- 来月計算(next_month): 12月をまたぐ -------------------------------------

    check("8月の来月は9月", m.next_month(8) == 9)
    check("12月の来月は1月(年またぎ)", m.next_month(12) == 1)

    # -- 実データの読み込み ----------------------------------------------------

    tasks = m.load_tasks()
    check("annual-tasks.ymlは16件のタスクを持つ", len(tasks) == 16)

    # -- 月リストの展開(_expand_months) ------------------------------------------

    single = m.task_by_id(tasks, "kotairen-touroku")
    check("単一月(4)はリスト[4]に展開される", single.months == [4])

    multi = m.task_by_id(tasks, "wear-shiharai")
    check("複数月[6,7]はそのままリストになる", multi.months == [6, 7])

    aki = m.task_by_id(tasks, "aki-taikai")
    check("aki-taikaiは4か月([9,10,11,12])にまたがる", aki.months == [9, 10, 11, 12])

    # -- money_ja のスペルアウト -------------------------------------------------

    check("money=Aは校友会予算", single.money_ja == "校友会予算")
    fubokai = m.task_by_id(tasks, "fubokai-soukai")
    check("money=Bは父母会予算", fubokai.money_ja == "父母会予算")
    check("money無しのタスクはmoney_jaが空文字", m.task_by_id(tasks, "shinnyubu-touroku").money_ja == "")

    # -- シード済みタスクは完了扱いになっているか(実データ) -----------------------

    completed_2026 = m.completed_task_ids(2026)
    seeded_ids = {
        "kotairen-touroku",
        "kouyukai-karibarai",
        "shinnyubu-touroku",
        "fubokai-soukai",
        "wear-shiharai",
        "gasshuku-junbi",
        "gasshuku-genkin",
        "natsu-gasshuku",
    }
    check("シードした8件がすべて2026年度で完了扱い", seeded_ids <= completed_2026)

    log_rows = m.load_log(2026)
    natsu_row = next(r for r in log_rows if r["task_id"] == "natsu-gasshuku")
    check("natsu-gasshukuの完了日は2026-08-07", natsu_row["completed_on"] == "2026-08-07")

    # -- 今月/期限超過/来月の算出(2026-08-22時点) ---------------------------------

    today = date(2026, 8, 22)
    cur = m.current_month_tasks(tasks, today)
    cur_ids = {t.id for t in cur}
    check(
        "8/22時点の今月やることはgasshuku-kaikeiとtaikai-seikyu(natsu-gasshukuは完了済みなので除外)",
        cur_ids == {"gasshuku-kaikei", "taikai-seikyu"},
    )

    overdue = m.overdue_tasks(tasks, today)
    check("8/22時点で未完了のまま過ぎた業務は0件(シード済みのため)", overdue == [])

    nxt = m.next_month_tasks(tasks, today)
    nxt_ids = {t.id for t in nxt}
    check(
        "8/22時点の来月(9月)予定はgasshuku-kaikei/aki-taikai/fuyu-wear",
        nxt_ids == {"gasshuku-kaikei", "aki-taikai", "fuyu-wear"},
    )

    # -- 期限超過の算出を、未完了データで直接検証(実データを汚さない一時コピー) ----

    test_overdue_with_incomplete_data()

    # -- グルーピング(list向け) --------------------------------------------------

    grouped = m.group_by_month(tasks)
    check("4月には3件のタスクがある", len(grouped[4]) == 3)
    check("9月にはgasshuku-kaikei/aki-taikai/fuyu-wearの3件がある", {t.id for t in grouped[9]} == {"gasshuku-kaikei", "aki-taikai", "fuyu-wear"})

    matched_month8 = m.tasks_for_month(tasks, 8)
    check(
        "month(8)はnatsu-gasshuku/gasshuku-kaikei/taikai-seikyuの3件(完了状態は問わない)",
        {t.id for t in matched_month8} == {"natsu-gasshuku", "gasshuku-kaikei", "taikai-seikyu"},
    )

    # -- CLIコマンドの終了コード(実データに対してでも副作用のないもの) --------------

    check("cmd_month(13)は範囲外でexit 1", cli.cmd_month(13) == 1)
    check("cmd_month(8)は正常でexit 0", cli.cmd_month(8) == 0)
    check("cmd_list()は正常でexit 0", cli.cmd_list() == 0)
    check("cmd_now()は正常でexit 0", cli.cmd_now(today=today) == 0)

    # -- done / undone のラウンドトリップ(一時コピーで検証、実ファイルは触らない) --

    test_done_and_undone_roundtrip()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_overdue_with_incomplete_data():
    """完了記録が無い状態でoverdue_tasksが正しく「年度内で今月より前の月」を拾うか検証する。

    task-log-2027.csv は実データに存在しないため、2027年度は完了記録ゼロの
    状態として扱われる(load_log は無いファイルに対して空リストを返す)。
    月の並びは暦年に依存しないので、2026年度の判定と同じ集合になるはず。
    """
    tasks = m.load_tasks()
    today = date(2027, 8, 22)  # 2027年度・年度内インデックス4(8月)、完了記録ファイルが存在しない年度

    overdue = m.overdue_tasks(tasks, today)
    overdue_ids = {t.id for t in overdue}
    check(
        "完了記録が無ければ4〜7月の業務がすべて期限超過扱い",
        overdue_ids
        == {
            "kotairen-touroku",
            "kouyukai-karibarai",
            "shinnyubu-touroku",
            "fubokai-soukai",
            "wear-shiharai",
            "gasshuku-junbi",
            "gasshuku-genkin",
        },
    )
    check(
        "2〜3月(次年度)の業務(kessan等)は8月時点ではまだ期限超過にならない",
        "kessan" not in overdue_ids and "haru-gasshuku" not in overdue_ids,
    )
    check(
        "期限超過リストは年度内の月順(4月起点)でソートされている",
        [m.fiscal_month_index(min(t.months)) for t in overdue] == sorted(m.fiscal_month_index(min(t.months)) for t in overdue),
    )


def test_done_and_undone_roundtrip():
    """model.mark_done / mark_undone / cli.cmd_done / cmd_undone を一時コピーのCSVで検証する。

    実データ(data/rugby/task-log-2026.csv)には一切触れない
    (model.DATA_DIR を一時ディレクトリに差し替えて実行する)。
    """
    orig_data_dir = m.DATA_DIR
    tmpdir = Path(tempfile.mkdtemp(prefix="nenkan-test-"))
    try:
        shutil.copy(orig_data_dir / "annual-tasks.yml", tmpdir / "annual-tasks.yml")
        shutil.copy(orig_data_dir / "task-log-2026.csv", tmpdir / "task-log-2026.csv")
        m.DATA_DIR = tmpdir
        cli.model.DATA_DIR = tmpdir  # cli は `from . import model` で同じモジュールを参照している

        tasks = m.load_tasks()
        rows_before = m.load_log(2026)
        check("テスト用コピーの初期完了件数は8件", len(rows_before) == 8)

        # -- 存在しないtask_idはValueError、ファイル未変更 ------------------------

        raised = False
        try:
            m.mark_done("nonexistent-task", tasks, date(2026, 8, 22))
        except ValueError:
            raised = True
        check("存在しないtask_idはValueError", raised)
        check("エラー後もファイルは8件のまま", len(m.load_log(2026)) == 8)

        # -- 同一年度の重複登録はValueError、ファイル未変更 ------------------------

        raised = False
        try:
            m.mark_done("natsu-gasshuku", tasks, date(2026, 8, 22))
        except ValueError:
            raised = True
        check("同一年度への重複登録はValueError", raised)
        check("重複エラー後もファイルは8件のまま", len(m.load_log(2026)) == 8)

        # -- cli.cmd_done: 未知のidはexit 1 ---------------------------------------

        code = cli.cmd_done("nonexistent-task", None, "", today=date(2026, 8, 22))
        check("cli.cmd_done(未知のid)はexit 1", code == 1)

        # -- cli.cmd_done: 不正な日付形式はexit 1、ファイル未変更 -------------------

        code = cli.cmd_done("taikai-seikyu", "2026/08/20", "", today=date(2026, 8, 22))
        check("cli.cmd_done(不正な日付)はexit 1", code == 1)
        check("日付エラー後もファイルは8件のまま", len(m.load_log(2026)) == 8)

        # -- 正常な追加(cli経由、--onを指定) --------------------------------------

        code = cli.cmd_done("taikai-seikyu", "2026-08-20", "テスト登録", today=date(2026, 8, 22))
        check("cli.cmd_done(正常)はexit 0", code == 0)
        rows_after = m.load_log(2026)
        check("追加後は9件", len(rows_after) == 9)
        added = next(r for r in rows_after if r["task_id"] == "taikai-seikyu")
        check("追加行のfiscal_yearは2026", added["fiscal_year"] == "2026")
        check("追加行のcompleted_onは指定日", added["completed_on"] == "2026-08-20")
        check("追加行のnoteが保存されている", added["note"] == "テスト登録")

        # -- --onを省略するとtoday(注入した値)が使われる ----------------------------

        code = cli.cmd_done("jinendo-yosan", None, "", today=date(2027, 2, 10))
        check("--on省略時はtodayを使う: exit 0", code == 0)
        rows_2026_after_feb = m.load_log(2026)
        added_feb = next(r for r in rows_2026_after_feb if r["task_id"] == "jinendo-yosan")
        check(
            "2027-02-10は2026年度なのでtask-log-2026.csvに追記される",
            added_feb["completed_on"] == "2027-02-10" and added_feb["fiscal_year"] == "2026",
        )

        # -- undone: 存在しないtask_idはexit 1 -------------------------------------

        code = cli.cmd_undone("nonexistent-task", today=date(2026, 8, 22))
        check("cli.cmd_undone(未知のid)はexit 1", code == 1)

        # -- undone: 記録の無いtask_idはexit 0・件数変わらず(見つからない旨のメッセージ) -

        rows_before_noop = len(m.load_log(2026))
        code = cli.cmd_undone("aki-taikai", today=date(2026, 8, 22))
        check("cli.cmd_undone(記録の無いid)はexit 0", code == 0)
        check("記録の無いidを取り消しても件数は変わらない", len(m.load_log(2026)) == rows_before_noop)

        # -- undone: 正常に取り消し、ラウンドトリップ完了 -----------------------------

        code = cli.cmd_undone("taikai-seikyu", today=date(2026, 8, 22))
        check("cli.cmd_undone(正常)はexit 0", code == 0)
        rows_final = m.load_log(2026)
        check("取り消し後は9件(8件のシード+jinendo-yosanが残っている)", len(rows_final) == 9)
        check("taikai-seikyuの記録は消えている", not any(r["task_id"] == "taikai-seikyu" for r in rows_final))
        check("jinendo-yosanの記録は残っている", any(r["task_id"] == "jinendo-yosan" for r in rows_final))

    finally:
        m.DATA_DIR = orig_data_dir
        cli.model.DATA_DIR = orig_data_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
