"""scripts.kaikei の単体テスト。pytest不要、`python3 tests/test_kaikei.py` で実行できる。"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.kaikei import model as m  # noqa: E402
from scripts.kaikei import checks  # noqa: E402

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

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
