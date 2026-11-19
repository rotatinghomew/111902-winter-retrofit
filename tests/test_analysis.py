"""分析口径的关键不变量测试。"""

import unittest
from pathlib import Path

from analysis.core import Source, fit_baselines, load_source, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "supplies.json"
QUERY = "2026-11-19"


class Corrections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tables = load_source(DATA)

    def src(self, q):
        return Source(self.tables, q)

    def test_correction_timeline_application(self):
        # 11-10 M0：原始 440 → 11-15 起 ×1.09 → 11-19 起 ×0.8（系数相对原读数）
        self.assertEqual(self.src("2026-11-14").meter_value("M0", "2026-11-10"), (440.0, "有效"))
        self.assertEqual(self.src("2026-11-15").meter_value("M0", "2026-11-10"), (440 * 1.09, "更正换算"))
        self.assertEqual(self.src("2026-11-19").meter_value("M0", "2026-11-10"), (440 * 0.8, "更正换算"))
        # 11-11 M0：11-15 起撤销
        self.assertEqual(self.src("2026-11-14").meter_value("M0", "2026-11-11"), (327.0, "有效"))
        self.assertEqual(self.src("2026-11-15").meter_value("M0", "2026-11-11"), (None, "撤销无效"))

    def test_post_query_correction_excluded(self):
        # M1 留出撤销 2026-11-20 发布：查询日 11-19 不生效，11-20 起生效
        self.assertEqual(self.src(QUERY).meter_value("M1", "2026-02-22"), (256.0, "有效"))
        self.assertEqual(self.src("2026-11-20").meter_value("M1", "2026-02-22"), (None, "撤销无效"))

    def test_daily_knowability(self):
        src = self.src(QUERY)
        self.assertTrue(src.daily_knowable("2026-11-18"))
        self.assertFalse(src.daily_knowable("2026-11-19"))


class Baselines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(DATA, QUERY)
        cls.base = cls.res["baselines"]

    def test_holdout_never_in_fit(self):
        for b in self.base.values():
            self.assertTrue(set(b["fit_days"]).isdisjoint(h["date"] for h in b["holdout"]))

    def test_staged_evidence_only_for_not_yet_commissioned(self):
        # 分步投用期（11-01~11-07）只有活动室（未投用）的 M1 进拟合；托育点已投用不得使用
        a = self.base["活动室"]
        self.assertTrue(any(lbl == "分步投用" for lbl in a["fit_labels"].values()))
        self.assertFalse(any(lbl == "分步投用" for lbl in self.base["托育点"]["fit_labels"].values()))
        self.assertFalse(any(lbl == "分步投用" for lbl in self.base["总表"]["fit_labels"].values()))

    def test_holdout_mae_within_contract_limit(self):
        for ev in self.res["evals"]:
            mae = self.base[ev["purpose"]]["holdout_mae"]
            self.assertLessEqual(mae, ev["protocol"]["max_holdout_mae_kwh"])
        # 具体数值锚点
        self.assertAlmostEqual(self.base["活动室"]["holdout_mae"], 3.19, places=2)
        self.assertAlmostEqual(self.base["托育点"]["holdout_mae"], 8.07, places=2)


class Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(DATA, QUERY)
        cls.ev = {e["contract"]: e for e in cls.res["evals"]}

    def test_coverage(self):
        self.assertEqual((len(self.ev["X1"]["numer"]), len(self.ev["X1"]["denom"])), (6, 7))
        self.assertEqual((len(self.ev["X2"]["numer"]), len(self.ev["X2"]["denom"])), (8, 12))
        for e in self.ev.values():
            self.assertTrue(e["coverage_ok"])

    def test_savings_and_comfort_gate(self):
        self.assertAlmostEqual(self.ev["X1"]["saving_total"], 182.3, places=1)
        self.assertAlmostEqual(self.ev["X2"]["saving_total"], 207.7, places=1)
        # 温度缺测/不达标日不进可签
        x1_days = {r["date"] for r in self.ev["X1"]["claim_rows"]}
        self.assertNotIn("2026-11-09", x1_days)  # 室温缺测
        x2_days = {r["date"] for r in self.ev["X2"]["claim_rows"]}
        self.assertNotIn("2026-11-02", x2_days)  # 19℃ < 20℃
        self.assertNotIn("2026-11-05", x2_days)  # 室温缺测

    def test_closure_rules(self):
        x1 = {r["date"]: r for r in self.ev["X1"]["rows"]}
        self.assertFalse(x1["2026-11-17"]["denom"])  # 计划停用不进分母
        self.assertTrue(x1["2026-11-11"]["denom"])   # 临时停用计入分母
        self.assertFalse(x1["2026-11-11"]["numerator"])  # 但仍是缺口

    def test_no_extrapolation(self):
        for e in self.ev.values():
            for r in e["rows"]:
                if r["date"] == "2026-11-12":  # 度日 40 超出支撑
                    self.assertFalse(r["denom"])
                    self.assertIsNone(r["pred"])


class Attribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(DATA, QUERY)
        cls.attrib = {a["date"]: a for a in cls.res["attribution"]}

    def test_joint_cap_excess_flagged(self):
        a = self.attrib["2026-11-15"]
        self.assertEqual(a["status"], "归属超限")
        self.assertAlmostEqual(a["excess"], 3.4, places=1)
        self.assertAlmostEqual(a["claim_total"], 86.9, places=1)

    def test_corrected_master_days_not_jointly_usable(self):
        self.assertNotEqual(self.attrib["2026-11-10"]["joint"], "一致")  # M2 缺测 + 总表更正
        self.assertEqual(self.attrib["2026-11-11"]["joint"], "总表不可用")
        # 但独立分表证据仍在
        self.assertIn("X1", self.attrib["2026-11-10"]["claims"])
        self.assertIn("X2", self.attrib["2026-11-11"]["claims"])

    def test_consistent_day_within_cap(self):
        a = self.attrib["2026-11-13"]
        self.assertEqual(a["status"], "上限内")
        self.assertLessEqual(a["claim_total"], a["master_saving"])


class SignoffBasis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = run(DATA, QUERY)
        cls.sig = {s["record"]["contract"]: s for s in cls.res["signoffs"]}

    def test_signed_x2_basis_preserved(self):
        # 签认基准日 11-13：当时无更正，M0 11-10=440、11-11=327
        b = self.sig["X2"]["basis"]
        self.assertAlmostEqual(b["saving_total"], 120.3, places=1)
        self.assertEqual((len(b["numer"]), len(b["denom"])), (5, 7))
        m = {r["date"]: r for r in self.sig["X2"]["basis_master"]}
        self.assertEqual(m["2026-11-10"]["m0"], 440.0)
        self.assertEqual(m["2026-11-11"]["m0"], 327.0)

    def test_pending_x1_basis_was_marginal(self):
        b = self.sig["X1"]["basis"]
        self.assertEqual((len(b["numer"]), len(b["denom"])), (2, 3))
        self.assertAlmostEqual(b["saving_total"], 30.2, places=1)

    def test_post_query_holdout_revalidation(self):
        pq = self.res["post_query"]
        self.assertIsNotNone(pq)
        self.assertEqual(pq["as_of"], "2026-11-20")
        # M1 留出撤销生效后样本 8→5，MAE 仍达标
        self.assertLessEqual(pq["holdout_mae"]["活动室"], 24)
        valid = [h for h in pq["holdout"]["活动室"] if h["err"] is not None]
        self.assertEqual(len(valid), 5)


if __name__ == "__main__":
    unittest.main()
