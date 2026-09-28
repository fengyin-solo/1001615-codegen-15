"""载重平衡复核台账的接口回归测试。

不依赖第三方测试框架，直接用 fastapi.testclient 起内存应用：
    PYTHONPATH=backend python3 backend/tests/test_loadsheet_review.py
规则覆盖：包线判限、超限拦截、同人复核不予受理、重复复核末次为准、口径一致。
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.store import store


class LoadsheetReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        store.reset()
        self.client = TestClient(app)

    def _action(self, entry_id: int, **values):
        return self.client.post(
            f"/api/loadsheet/{entry_id}/actions", json={"values": values}
        ).json()

    def test_over_limit_cannot_confirm(self) -> None:
        # LOAD-0002：B737-800 重心 34.2，超过包线上限 32，不许直接确认。
        result = self._action(2, action="确认配载", 复核人="周芸", 复核意见="ok")
        self.assertFalse(result["ok"])
        self.assertIn("超出 B737-800 机型包线上限", result["message"])

    def test_same_person_review_rejected(self) -> None:
        # LOAD-0001 配载人为王磊，复核人同名时不予受理并指出对不上项。
        result = self._action(1, action="确认配载", 复核人="王磊", 复核意见="ok")
        self.assertFalse(result["ok"])
        self.assertIn("不予受理", result["message"])
        self.assertIn("复核人 / 配载人", result["message"])

    def test_reviewer_and_comment_required(self) -> None:
        result = self._action(1, action="确认配载", 复核人="", 复核意见="x")
        self.assertIn("缺少复核人", result["message"])
        result = self._action(1, action="确认配载", 复核人="周芸", 复核意见="")
        self.assertIn("缺少复核意见", result["message"])

    def test_review_flow_and_last_conclusion_wins(self) -> None:
        # 正常确认与超限退回。
        self.assertTrue(self._action(1, action="确认配载", 复核人="周芸", 复核意见="ok")["ok"])
        self.assertTrue(self._action(2, action="退回重算", 复核人="周芸", 复核意见="超限")["ok"])
        # 提交复核照旧，不需要复核人。
        self.assertTrue(self._action(1, action="提交复核")["ok"])
        # LOAD-0003 重复送复核：先退后认，以最后一次结论为准。
        self.assertTrue(self._action(3, action="退回重算", 复核人="吴迪", 复核意见="待核")["ok"])
        self.assertTrue(self._action(3, action="确认配载", 复核人="吴迪", 复核意见="通过")["ok"])
        entry = self.client.get("/api/loadsheet/3").json()
        self.assertEqual(entry["status"], "已确认")
        self.assertEqual(entry["复核结论"], "复核通过")
        self.assertEqual(entry["复核人员"], "吴迪")

    def test_ledger_keeps_history_and_latest_view(self) -> None:
        self.assertTrue(self._action(1, action="确认配载", 复核人="周芸", 复核意见="ok")["ok"])
        self.assertTrue(self._action(2, action="退回重算", 复核人="周芸", 复核意见="超限")["ok"])
        self.assertTrue(self._action(3, action="退回重算", 复核人="吴迪", 复核意见="待核")["ok"])
        self.assertTrue(self._action(3, action="确认配载", 复核人="吴迪", 复核意见="通过")["ok"])
        # 种子 1 条 + 新增 4 条留痕。
        self.assertEqual(self.client.get("/api/loadsheet/reviews").json()["total"], 5)
        latest = {
            row["配载单号"]: row
            for row in self.client.get(
                "/api/loadsheet/reviews", params={"only_latest": "true"}
            ).json()["items"]
        }
        self.assertEqual(len(latest), 3)
        self.assertEqual(latest["LOAD-0003"]["复核结论"], "复核通过")
        self.assertEqual(
            self.client.get(
                "/api/loadsheet/reviews", params={"loadsheet_id": 3}
            ).json()["total"],
            3,
        )

    def test_register_over_limit_can_only_return(self) -> None:
        result = self.client.post("/api/loadsheet", json={"values": {
            "配载单号": "L-9", "关联航班": "HU1", "机型": "A320",
            "计算重量": "61000", "重心位置": "40", "配载人员": "赵六",
        }}).json()
        self.assertTrue(result["ok"])
        entry_id = result["entry"]["id"]
        self.assertFalse(result["entry"]["重心合规"])
        self.assertFalse(
            self._action(entry_id, action="确认配载", 复核人="周芸", 复核意见="x")["ok"]
        )
        self.assertTrue(
            self._action(entry_id, action="退回重算", 复核人="周芸", 复核意见="x")["ok"]
        )

    def test_summary_shares_one_source_of_truth(self) -> None:
        summary = self.client.get("/api/loadsheet/summary").json()
        self.assertTrue(summary["台账与列表重量一致"])
        export = self.client.get("/api/loadsheet/export").json()
        self.assertEqual(export["total"], summary["配载单总数"])
        self.assertIn("summary", export)


if __name__ == "__main__":
    unittest.main()
