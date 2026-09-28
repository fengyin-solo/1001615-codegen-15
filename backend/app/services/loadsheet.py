"""载重平衡业务规则：配载单状态流转、机型包线判限与复核台账都收在这里。

复核口径：
- 登记配载单时计算重量与重心位置一并录入，按机型在重心包线上限内才算合规；
- 重心超出包线上限的不允许直接确认配载，须先退回重算；
- 复核人与配载人同一人时不予受理，并指出对不上的项；
- 同一张配载单重复送复核的，以台账中最后一次结论为准；
- 台账、列表与汇总共用 store 里的同一份配载单数据，不另记重量。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "loadsheet"
LEDGER_MODULE = "loadsheet_review"
REQUIRED_FIELDS = ["配载单号", "关联航班", "机型", "计算重量", "重心位置", "配载人员"]
STATUS_ORDER = ["待计算", "待复核", "已确认", "已退回"]
ACTION_RULES = {"提交复核": "待复核", "确认配载": "已确认", "退回重算": "已退回"}
NEGATIVE_ACTIONS = ["退回重算"]

# 机型重心包线：取当前重量下允许的重心位置上限（%MAC）。
# 真实包线是随重量变化的折线，这里按机型给判定上限，落点超限即不合规。
AIRCRAFT_ENVELOPE: dict[str, dict[str, Any]] = {
    "A320": {"重心上限": 33.0, "单位": "%MAC", "说明": "A320 重心包线上限"},
    "A321": {"重心上限": 34.0, "单位": "%MAC", "说明": "A321 重心包线上限"},
    "A330-300": {"重心上限": 36.5, "单位": "%MAC", "说明": "A330-300 重心包线上限"},
    "B737-800": {"重心上限": 32.0, "单位": "%MAC", "说明": "B737-800 重心包线上限"},
    "B737MAX8": {"重心上限": 32.5, "单位": "%MAC", "说明": "B737 MAX 8 重心包线上限"},
    "B777-300ER": {"重心上限": 38.0, "单位": "%MAC", "说明": "B777-300ER 重心包线上限"},
}

LEDGER_CONCLUSION_PASS = "复核通过"
LEDGER_CONCLUSION_FAIL = "复核不通过"
LEDGER_DECISIONS = {"确认": LEDGER_CONCLUSION_PASS, "退回": LEDGER_CONCLUSION_FAIL}


def _to_float(value: Any) -> float | None:
    """把录入值转成数字；空值或非数字返回 None，由调用方决定怎么提示。"""
    text = str(value or "").strip().rstrip("%")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class LoadsheetService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("配载单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---- 机型包线 ----------------------------------------------------------

    def list_envelope(self) -> list[dict[str, Any]]:
        return [{"机型": name, **rule} for name, rule in AIRCRAFT_ENVELOPE.items()]

    def envelope_limit(self, aircraft: str) -> float | None:
        rule = AIRCRAFT_ENVELOPE.get(str(aircraft or "").strip().upper())
        return None if rule is None else float(rule["重心上限"])

    def check_cg(self, aircraft: str, cg_value: Any) -> tuple[bool, str]:
        """按机型包线上限判重心是否合规，返回（是否合规、说明）。"""
        cg = _to_float(cg_value)
        if cg is None:
            return False, f"重心位置「{cg_value}」不是有效数值，无法按包线判限"
        limit = self.envelope_limit(aircraft)
        if limit is None:
            return False, f"机型「{aircraft}」未配置重心包线上限，不能判定重心合规性"
        if cg > limit:
            return False, f"重心位置 {cg:g}%MAC 超出 {aircraft} 机型包线上限 {limit:g}%MAC，须退回重算"
        return True, f"重心位置 {cg:g}%MAC 在 {aircraft} 机型包线上限 {limit:g}%MAC 以内"

    # ---- 登记 --------------------------------------------------------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["油量数据"] = str(values.get("油量数据") or "").strip()
        compliant, reason = self.check_cg(entry["机型"], entry["重心位置"])
        entry["重心合规"] = compliant
        entry["判限说明"] = reason
        entry["复核人员"] = ""
        entry["复核意见"] = ""
        entry["复核结论"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于载重平衡可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"配载单已{action}"

    # ---- 复核台账 ----------------------------------------------------------

    def latest_reviews(self) -> list[dict[str, Any]]:
        """每张配载单取台账里最后一次复核记录；台账重量口径以此为准。"""
        latest: dict[int, dict[str, Any]] = {}
        for row in store.rows(LEDGER_MODULE):
            entry_id = int(row.get("配载单ID", 0))
            if entry_id not in latest or int(row.get("id", 0)) > int(latest[entry_id].get("id", 0)):
                latest[entry_id] = row
        return sorted(latest.values(), key=lambda row: int(row.get("id", 0)), reverse=True)

    def list_reviews(
        self,
        *,
        loadsheet_id: int | None = None,
        keyword: str | None = None,
        only_latest: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.latest_reviews() if only_latest else sorted(
            store.rows(LEDGER_MODULE), key=lambda row: int(row.get("id", 0)), reverse=True
        )
        if loadsheet_id is not None:
            rows = [row for row in rows if int(row.get("配载单ID", 0)) == loadsheet_id]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("配载单号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def submit_review(
        self,
        entry_id: int,
        *,
        decision: str,
        reviewer: str,
        comment: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """送复核并登记台账。decision 取「确认」或「退回」。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        decision = str(decision or "").strip()
        if decision not in LEDGER_DECISIONS:
            return None, "复核结论须为「确认」或「退回」，本入口只接受确认配载与退回重算"
        reviewer = str(reviewer or "").strip()
        comment = str(comment or "").strip()
        if not reviewer:
            return None, "缺少复核人，台账不予登记"
        if not comment:
            return None, "缺少复核意见，台账不予登记"

        loader = str(entry.get("配载人员") or "").strip()
        # 复核人与配载人同人：不予受理，并指出对不上的项。
        if loader and reviewer == loader:
            return None, (
                f"不予受理：复核人「{reviewer}」与配载人「{loader}」为同一人，"
                "对不上的项为「复核人 / 配载人」，须换人复核"
            )

        compliant, cg_reason = self.check_cg(entry.get("机型", ""), entry.get("重心位置"))
        if decision == "确认" and not compliant:
            # 超出包线上限不许直接确认，必须先退回重算；判限说明里已写明原因。
            return None, f"不予确认：{cg_reason}"

        passed = LEDGER_DECISIONS[decision] == LEDGER_CONCLUSION_PASS
        action = "确认配载" if passed else "退回重算"
        ledger_rows = store.rows(LEDGER_MODULE)
        record = {
            "id": max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1,
            "配载单ID": entry_id,
            "配载单号": entry.get("配载单号", ""),
            "关联航班": entry.get("关联航班", ""),
            "机型": entry.get("机型", ""),
            # 重量与重心直接取配载单当前值，台账与列表、汇总同源。
            "计算重量": entry.get("计算重量", ""),
            "重心位置": entry.get("重心位置", ""),
            "重心合规": compliant,
            "判限说明": cg_reason,
            "配载人": loader,
            "复核人": reviewer,
            "复核意见": comment,
            "复核结论": LEDGER_DECISIONS[decision],
        }
        ledger_rows.append(record)

        # 同一张配载单重复送复核，以最后一次结论为准：回写配载单上的结论字段。
        entry["复核人员"] = reviewer
        entry["复核意见"] = comment
        entry["复核结论"] = record["复核结论"]
        entry["重心合规"] = compliant
        entry["判限说明"] = cg_reason
        entry["status"] = "已确认" if passed else "已退回"
        # 与既有状态机一致：已确认、已退回都不再是待处理。
        entry["pending"] = False
        entry["abnormal"] = not passed
        return record, f"配载单已{action}，复核台账已登记"

    # ---- 汇总（与列表、台账同一份数据） ------------------------------------

    def summary(self) -> dict[str, Any]:
        rows = store.rows(MODULE)

        def weight_of(row: dict[str, Any]) -> float:
            value = _to_float(row.get("计算重量"))
            return value or 0.0

        # 重量只认配载单登记的那一份：列表、台账、汇总都从这里取，不另立账。
        total_weight = sum(weight_of(row) for row in rows)
        confirmed_weight = sum(
            weight_of(row) for row in rows if row.get("status") == "已确认"
        )
        latest = self.latest_reviews()
        reviewed_weight = sum(weight_of(row) for row in latest)
        # 台账快照与配载单现值逐单比对，全部一致才算同一份数。
        weight_consistent = all(
            weight_of(record)
            == weight_of(store.find(MODULE, int(record.get("配载单ID", 0))) or {})
            for record in latest
        )
        return {
            "配载单总数": len(rows),
            "待复核数": sum(1 for row in rows if row.get("status") == "待复核"),
            "已确认数": sum(1 for row in rows if row.get("status") == "已确认"),
            "退回重算数": sum(1 for row in rows if row.get("status") == "已退回"),
            "计算重量合计": total_weight,
            "已确认重量合计": confirmed_weight,
            "台账重量合计": reviewed_weight,
            "台账与列表重量一致": weight_consistent,
            "复核台账条数": len(store.rows(LEDGER_MODULE)),
            "口径说明": "列表、台账与汇总重量均取自同一份配载单登记数据；重复复核按每单最后一次结论计",
        }
