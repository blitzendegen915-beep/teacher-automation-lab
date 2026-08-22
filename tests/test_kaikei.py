"""scripts.kaikei の単体テスト。pytest不要、`python3 tests/test_kaikei.py` で実行できる。"""
import contextlib
import io
import shutil
import sys
import tempfile
from argparse import Namespace
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.kaikei import model as m  # noqa: E402
from scripts.kaikei import checks  # noqa: E402
from scripts.kaikei import cli  # noqa: E402

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
    camp = m.load("2026-summer")

    # -- コアアルゴリズム: 食事レベルの在籍判定 -------------------------------

    full_timer = next(p for p in camp.attending_roster() if p.is_full_time)
    pres = camp.roster_presence(full_timer)
    check(
        f"全日参加者({full_timer.name})の宿泊は6泊",
        len(pres.lodging_nights) == 6,
    )
    check(f"全日参加者({full_timer.name})の昼食は7回", len(pres.lunches) == 7)
    check(f"全日参加者({full_timer.name})の朝食は6回", len(pres.breakfasts) == 6)
    check(f"全日参加者({full_timer.name})の夕食は6回", len(pres.dinners) == 6)

    yoshida = next(p for p in camp.attending_roster() if p.name == "吉田 青空")
    yoshida_pres = camp.roster_presence(yoshida)
    check("吉田青空(8/5夕食〜合流)の宿泊は2泊", len(yoshida_pres.lodging_nights) == 2)

    shiina = next(p for p in camp.attending_roster() if p.name == "椎名 薫")
    shiina_pres = camp.roster_presence(shiina)
    check("椎名薫(8/4夕食〜合流)の宿泊は3泊", len(shiina_pres.lodging_nights) == 3)

    # attends=no の生徒は除外されているか
    names_attending = {p.name for p in camp.attending_roster()}
    check("attends=noの生徒(塩貝蒼達)は除外されている", "塩貝 蒼達" not in names_attending)

    # -- 全体規約: 初日朝食なし・最終日夕食なし -------------------------------

    check("合宿初日は朝食なし", camp.meals_exist(camp.start)["breakfast"] is False)
    check("合宿最終日は夕食なし", camp.meals_exist(camp.end)["dinner"] is False)
    check("合宿最終日は朝食あり", camp.meals_exist(camp.end)["breakfast"] is True)
    check("合宿初日は夕食あり", camp.meals_exist(camp.start)["dinner"] is True)

    # -- 曜日ヘルパー ----------------------------------------------------------

    check("2026-08-01は土曜日", checks.weekday_ja(date(2026, 8, 1)) == "土")
    check("2026-08-07は金曜日", checks.weekday_ja(date(2026, 8, 7)) == "金")

    # -- 収入計算 ---------------------------------------------------------------

    inc = m.income(camp)
    full_select_totals = {
        l.total for l in inc["lines"] if l.is_full_time and l.person.role == "選手"
    }
    full_mgr_totals = {
        l.total for l in inc["lines"] if l.is_full_time and l.person.role == "マネージャー"
    }
    check("全日参加・選手の徴収額は一律¥79,090", full_select_totals == {79090})
    check("全日参加・マネージャーの徴収額は一律¥78,060", full_mgr_totals == {78060})

    yoshida_income = next(l for l in inc["lines"] if l.person.name == "吉田 青空")
    check("吉田青空の徴収額は¥33,110", yoshida_income.total == 33110)

    shiina_income = next(l for l in inc["lines"] if l.person.name == "椎名 薫")
    check("椎名薫の徴収額は¥42,250", shiina_income.total == 42250)

    check("収入合計は¥3,236,900", inc["total"] == 3236900)

    # -- 人数表 ------------------------------------------------------------------

    hc = m.headcount(camp)
    check("延べ宿泊人泊数は258人泊(名簿ベース)", hc["totals"]["lodging"] == 258)

    # -- 収支 -----------------------------------------------------------------

    bal = m.balance(camp)
    check("支出合計(ホテル+バス+小口)は¥3,034,465", bal["expense_total"] == 3034465)
    check("収支差額(残額)は¥202,435", bal["diff"] == 202435)

    # -- 立替金精算 ----------------------------------------------------------

    settle = m.settlement(camp)
    check("畠山先生の未精算立替金は¥32,675", settle["by_payer"]["畠山"]["total"] == 32675)
    check("占部先生の未精算立替金は¥1,070", settle["by_payer"]["占部"]["total"] == 1070)
    check("立替金合計は¥33,745", settle["grand_total"] == 33745)

    # -- checks.py: 既知の論点が検出されるか ------------------------------------

    findings = checks.run_all(camp)
    submitted_mismatches = [
        f for f in findings if f.code == "submitted_headcount_mismatch"
    ]
    check("8/3の申告済み人数の不一致が検出される(既知の論点)", any("8/3" in f.message for f in submitted_mismatches))
    # 名簿ベースの人数とホテルへの申告人数は5日分ずれている。
    # 原因は(1)選手1名の在籍差(2)コーチの帯同日の未確定 で、いずれも未解決の論点。
    # 数が減ったらそれは解決したということなので、テストを更新すること。
    check("申告済み人数の不一致は5日分", len(submitted_mismatches) == 5)

    error_findings = [f for f in findings if f.severity == "error"]
    check("エラーレベルのfindingは無い(想定通りの残額のため)", len(error_findings) == 0)

    missing_receipt_findings = [f for f in findings if f.code == "missing_receipts"]
    check("支出記録の無い日が3日分検出される(8/4,8/5,8/7)", len(missing_receipt_findings) == 3)
    check(
        "支出記録の無い日の警告に前年度実績(36件・¥164,602)が入っている",
        all("雑費36件" in f.message and "¥164,602" in f.message for f in missing_receipt_findings),
    )

    misc_findings = [f for f in findings if f.code.startswith("misc_vs_prior_year")]
    check("雑費(分類C)対前年比の finding が1件ある", len(misc_findings) == 1)
    # 金額そのものは領収書が追加されるたびに変わるので、値ではなく
    # 「前年比50%未満なら warn になる」という判定の振る舞いを検証する。
    camp = m.load("2026-summer")
    this_year = sum(e.amount for e in camp.expenses if e.category == "C")
    prior_total = sum(r.amount for r in m.load_prior_year_misc())
    ratio = this_year / prior_total
    check(
        f"雑費(分類C)対前年比の判定が正しい(今年¥{this_year:,}/前年¥{prior_total:,}={ratio:.0%})",
        misc_findings[0].severity == ("warn" if ratio < 0.5 else "info")
        and f"¥{this_year:,}" in misc_findings[0].message
        and f"¥{prior_total:,}" in misc_findings[0].message,
    )

    # -- 前年度雑費台帳の読み込み -------------------------------------------

    test_prior_year_misc()

    # -- add / --settle (実データを汚さないよう一時ディレクトリで検証) -----------

    test_add_and_settle()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


def test_prior_year_misc():
    prior = m.prior_year_misc_summary()
    check("前年度(2025)雑費台帳は36件", prior["count"] == 36)
    check("前年度(2025)雑費台帳の合計は¥164,602", prior["total"] == 164602)
    check(
        "前年度雑費台帳の各行はdate/item/amountを持つ",
        all(isinstance(i.date, date) and isinstance(i.item, str) and isinstance(i.amount, int) for i in prior["items"]),
    )


def _run_cmd_add(ns: Namespace):
    """cli.cmd_add を実行し、(終了コード, 標準出力)を返す。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.cmd_add(ns)
    return code, buf.getvalue()


def _add_ns(camp="2026-summer", **overrides):
    base = dict(
        camp=camp,
        date=None,
        vendor=None,
        description=None,
        amount=None,
        category=None,
        payer=None,
        receipt=None,
        note="",
        settle=None,
    )
    base.update(overrides)
    return Namespace(**base)


def test_add_and_settle():
    """model.append_expense / settle_payer_rows / cli.cmd_add を、一時コピーのCSVに対して検証する。

    real の data/rugby/expenses-2026-summer.csv には一切触れない
    (model.DATA_DIR を一時ディレクトリに差し替えて実行する)。
    """
    orig_data_dir = m.DATA_DIR
    tmpdir = Path(tempfile.mkdtemp(prefix="kaikei-test-"))
    try:
        # cli.cmd_add は model.load() で合宿期間・立替金の再計算も行うため、
        # 支出台帳だけでなく camp yml・roster も一時ディレクトリにコピーする。
        for name in ("expenses-2026-summer.csv", "camp-2026-summer.yml", "roster-2026.csv"):
            shutil.copy(orig_data_dir / name, tmpdir / name)
        m.DATA_DIR = tmpdir
        cli.model.DATA_DIR = tmpdir  # cli は `from . import model` で同じモジュールを参照している

        rows_before, fieldnames = m._read_expense_rows("2026-summer")
        check("テスト用コピーの初期行数は9行", len(rows_before) == 9)
        check(
            "既存の列順(date,vendor,description,amount,category,payer,settled,receipt,note)が保持されている",
            fieldnames == m.EXPENSE_FIELDNAMES,
        )

        # -- cli.cmd_add: 入力エラーはファイルを一切変更しない ----------------

        code, out = _run_cmd_add(_add_ns(date="2026-08-04", vendor="テスト店", description="テスト", amount=-5, category="C", payer="畠山"))
        check("金額が負ならexit 1", code == 1)
        check("金額が負ならエラーメッセージに'正の整数'を含む", "正の整数" in out)
        rows, _ = m._read_expense_rows("2026-summer")
        check("金額エラー後もファイルは9行のまま", len(rows) == 9)

        code, out = _run_cmd_add(_add_ns(date="2026-08-04", vendor="テスト店", description="テスト", amount=500, category="X", payer="畠山"))
        check("会計分類が不正ならexit 1", code == 1)
        rows, _ = m._read_expense_rows("2026-summer")
        check("会計分類エラー後もファイルは9行のまま", len(rows) == 9)

        code, out = _run_cmd_add(_add_ns(date="2026/08/04", vendor="テスト店", description="テスト", amount=500, category="C", payer="畠山"))
        check("日付形式が不正ならexit 1", code == 1)
        rows, _ = m._read_expense_rows("2026-summer")
        check("日付エラー後もファイルは9行のまま", len(rows) == 9)

        code, out = _run_cmd_add(_add_ns(date="2026-08-04", vendor="テスト店", description="テスト", amount=500, category="C", payer="   "))
        check("空のpayerならexit 1", code == 1)

        # -- cli.cmd_add: 正常な追加 --------------------------------------------

        code, out = _run_cmd_add(
            _add_ns(date="2026-08-04", vendor="テスト店", description="テスト品", amount=500, category="C", payer="畠山", note="単体テスト")
        )
        check("正常な追加はexit 0", code == 0)
        check("領収書番号が自動採番される(r010)", "r010" in out)
        check("追加行と未精算合計が出力に含まれる", "テスト品" in out and "畠山" in out)

        rows_after, _ = m._read_expense_rows("2026-summer")
        check("追加後は10行", len(rows_after) == 10)
        added_row = next(r for r in rows_after if r["receipt"] == "r010")
        check("追加行のsettledは既定でno", added_row["settled"] == "no")
        check("追加行の内容が正しい", added_row["date"] == "2026-08-04" and added_row["amount"] == "500")

        dates_sorted = [r["date"] for r in rows_after]
        check("日付でソートされている(昇順)", dates_sorted == sorted(dates_sorted))

        # -- model.append_expense: 領収書番号の重複はValueErrorでファイル未変更 ----

        raised = False
        try:
            m.append_expense(
                "2026-summer",
                {
                    "date": "2026-08-05",
                    "vendor": "x",
                    "description": "y",
                    "amount": 1,
                    "category": "C",
                    "payer": "畠山",
                    "settled": "no",
                    "receipt": "r010",
                    "note": "",
                },
            )
        except ValueError:
            raised = True
        check("重複する領収書番号を指定するとValueError", raised)
        rows_after_dup, _ = m._read_expense_rows("2026-summer")
        check("重複エラー後もファイルは10行のまま", len(rows_after_dup) == 10)

        # -- 期間外の日付は警告のみでブロックしない ------------------------------

        code, out = _run_cmd_add(
            _add_ns(date="2026-07-15", vendor="テスト店", description="期間外テスト", amount=100, category="C", payer="畠山", receipt="r999")
        )
        check("期間外の日付でもexit 0(警告のみ)", code == 0)
        check("期間外の日付は警告文言を含む", "合宿期間" in out and "外です" in out)
        rows_after_oor, _ = m._read_expense_rows("2026-summer")
        check("期間外の日付でも追加される(11行)", len(rows_after_oor) == 11)

        # -- --settle: 指定した payer の未精算行がすべて yes になる ---------------

        before_settle = m.settlement(m.load("2026-summer"))
        check("settle前の畠山の未精算額には追加分が含まれる", before_settle["by_payer"]["畠山"]["total"] == 32675 + 500 + 100)

        code, out = _run_cmd_add(_add_ns(settle="畠山"))
        check("--settle 畠山 はexit 0", code == 0)
        check("--settle の出力に精算額が含まれる", "33,275" in out or "33275" in out)

        after_settle_rows, _ = m._read_expense_rows("2026-summer")
        hatakeyama_unsettled = [r for r in after_settle_rows if r["payer"] == "畠山" and r["settled"].strip().lower() != "yes"]
        check("--settle 後は畠山の未精算行が0件", len(hatakeyama_unsettled) == 0)
        occube_unsettled = [r for r in after_settle_rows if r["payer"] == "占部" and r["settled"].strip().lower() != "yes"]
        check("--settle 畠山 は占部の行に影響しない", len(occube_unsettled) == 1)

        code, out = _run_cmd_add(_add_ns(settle="畠山"))
        check("再度 --settle しても対象0件でexit 0", code == 0)
        check("再度 --settle した旨のメッセージが出る", "未精算の立替金はありません" in out)

        code, out = _run_cmd_add(_add_ns(settle="  "))
        check("空文字の --settle はexit 1", code == 1)

    finally:
        m.DATA_DIR = orig_data_dir
        cli.model.DATA_DIR = orig_data_dir
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
