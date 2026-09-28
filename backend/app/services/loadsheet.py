"""载重平衡业务规则：配载登记、包线判核、复核台账与状态流转都收在这里。

口径约定：配载单列表、复核台账与汇总数字都只从内存仓库里的同一份配载单数据
派生，不在别处另存重量，避免出现“台账一个数、列表一个数”。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "loadsheet"
REVIEW_MODULE = "loadsheet_review"
REQUIRED_FIELDS = ["配载单号", "关联航班", "机型", "计算重量", "重心位置", "配载人员"]
OPTIONAL_FIELDS = ["油量数据"]
NUMERIC_FIELDS = ["计算重量", "重心位置"]
STATUS_ORDER = ["待计算", "待复核", "已确认", "已退回"]
ACTION_RULES = {"提交复核": "待复核", "确认配载": "已确认", "退回重算": "已退回"}
NEGATIVE_ACTIONS = ["退回重算"]

# 机型重心包线：重心位置统一以 %MAC 计，这里维护各机型包线的（后）上限。
# 重心位置大于该上限即判定为超出包线，不允许直接确认配载。
ENVELOPE_LIMITS: dict[str, float] = {
    "A320": 33.0,
    "A321": 35.0,
    "B737-800": 32.5,
    "B737-8": 33.5,
    "A330-300": 37.0,
    "B777-300ER": 38.0,
}

PASS = "通过"
REJECT = "退回"


def _to_number(value: Any) -> float | None:
    """把录入框里的重量/重心解析成数值；解析不出来时返回 None，由调用方报错。"""
    if value is None:
        return None
    text = str(value).strip().replace("kg", "").replace("KG", "").replace("公斤", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class LoadsheetService:
    # ---------- 读取口径：列表、明细、台账、汇总都从这里过 ----------
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
        return [self._decorate(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry is not None else None

    def list_reviews(self, *, keyword: str | None = None) -> list[dict[str, Any]]:
        """复核台账：一张配载单每送一次复核就留一条，轮次越大越新。"""
        rows = store.rows(REVIEW_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("配载单号", ""))]
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        """汇总口径：重量合计与各状态数量全部按当前配载单实时算，不另存一份。"""
        rows = [self._decorate(row) for row in store.rows(MODULE)]
        total_weight = 0.0
        for row in rows:
            weight = row.get("计算重量")
            if isinstance(weight, (int, float)):
                total_weight += float(weight)
        return {
            "配载单总数": len(rows),
            "待复核配载": sum(1 for row in rows if row["status"] == "待复核"),
            "已确认配载": sum(1 for row in rows if row["status"] == "已确认"),
            "退回重算数": sum(1 for row in rows if row["status"] == "已退回"),
            "计算重量合计": round(total_weight, 1),
            "机型包线": [{"机型": name, "包线上限": limit} for name, limit in ENVELOPE_LIMITS.items()],
        }

    # ---------- 登记 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        aircraft = str(values.get("机型") or "").strip()
        if aircraft not in ENVELOPE_LIMITS:
            return None, f"机型「{aircraft}」未配置重心包线上限，无法判定重心是否合规"
        parsed: dict[str, float] = {}
        for field in NUMERIC_FIELDS:
            number = _to_number(values.get(field))
            if number is None:
                return None, f"{field}需为数值，收到的是「{values.get(field)}」"
            parsed[field] = number
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field) or "").strip() for field in REQUIRED_FIELDS if field not in NUMERIC_FIELDS})
        entry.update(parsed)
        for field in OPTIONAL_FIELDS:
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._decorate(entry), ""

    # ---------- 动作流转 ----------
    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"配载单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于载重平衡可执行范围"
        values = values or {}
        if action == "提交复核":
            return self._submit_review(entry, values)
        if action == "确认配载":
            return self._confirm(entry)
        return self._return(entry, values)

    def _submit_review(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] == "已确认":
            return None, "配载单已确认，不能再送复核；如需调整请先退回重算"
        reviewer = str(values.get("复核人员") or "").strip()
        if not reviewer:
            return None, "送复核必须登记复核人员"
        opinion = str(values.get("复核意见") or "").strip()

        # 退回重算后允许把新算的重量/重心一并送来，台账与列表从此共用这组新值。
        for field in NUMERIC_FIELDS:
            raw = values.get(field)
            if raw is not None and str(raw).strip():
                number = _to_number(raw)
                if number is None:
                    return None, f"{field}需为数值，收到的是「{raw}」"
                entry[field] = number

        # 同人复核不予受理，并指明对不上的是“人员项”。
        if reviewer == str(entry.get("配载人员") or "").strip():
            return None, (
                f"不予受理：复核人员「{reviewer}」与配载人员是同一人，"
                "人员项对不上（复核与配载须由不同人员完成）"
            )

        aircraft = str(entry.get("机型") or "").strip()
        limit = ENVELOPE_LIMITS.get(aircraft)
        if limit is None:
            return None, f"机型「{aircraft}」未配置重心包线上限，无法判定重心是否合规"
        cg = float(entry["重心位置"])
        within_envelope = cg <= limit
        if not within_envelope and not opinion:
            return None, (
                f"重心位置 {cg:g}%MAC 超出机型 {aircraft} 包线上限 {limit:g}%MAC，"
                "须退回重算，请填写复核意见后再提交"
            )

        conclusion = PASS if within_envelope else REJECT
        record = self._append_review(entry, reviewer, opinion, conclusion, limit)
        if within_envelope:
            entry["status"] = "待复核"
            entry["pending"] = True
            entry["abnormal"] = False
            message = (
                f"第 {record['轮次']} 次复核通过：重心 {cg:g}%MAC 在 {aircraft} 包线上限 "
                f"{limit:g}%MAC 以内，可以确认配载"
            )
        else:
            entry["status"] = "已退回"
            entry["pending"] = True
            entry["abnormal"] = True
            message = (
                f"重心位置 {cg:g}%MAC 超出机型 {aircraft} 包线上限 {limit:g}%MAC，"
                "对不上的项是「重心位置」，不允许直接确认配载，已退回重算"
            )
        return self._decorate(entry), message

    def _confirm(self, entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] == "已确认":
            return self._decorate(entry), "配载单已确认"
        latest = self._latest_review(int(entry["id"]))
        if latest is None:
            return None, "该配载单还没有复核台账记录，须先送复核通过后才能确认配载"
        # 同一张配载单重复送复核的，以最后一次结论为准。
        if latest["复核结论"] != PASS:
            return None, (
                f"最近一次（第 {latest['轮次']} 次）复核结论为「退回」：{latest['复核意见'] or '无意见'}，"
                "不能确认配载，请重算后重新送复核"
            )
        limit = ENVELOPE_LIMITS.get(str(entry.get("机型") or ""))
        cg = _to_number(entry.get("重心位置"))
        if limit is None or cg is None:
            return None, "机型包线或重心位置缺失，无法确认配载"
        if cg > limit:
            return None, (
                f"当前重心位置 {cg:g}%MAC 已超出包线上限 {limit:g}%MAC，"
                "对不上的项是「重心位置」，不能确认配载"
            )
        entry["status"] = "已确认"
        entry["pending"] = False
        entry["abnormal"] = False
        return self._decorate(entry), "配载单已确认"

    def _return(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] in ("已确认", "已退回"):
            return None, f"配载单当前为「{entry['status']}」，无需再退回重算"
        reviewer = str(values.get("复核人员") or "").strip()
        opinion = str(values.get("复核意见") or "").strip()
        if reviewer:
            # 走入口手工退回同样把复核人与意见记进台账；同人照样不予受理。
            if reviewer == str(entry.get("配载人员") or "").strip():
                return None, (
                    f"不予受理：复核人员「{reviewer}」与配载人员是同一人，"
                    "人员项对不上（复核与配载须由不同人员完成）"
                )
            limit = ENVELOPE_LIMITS.get(str(entry.get("机型") or ""))
            self._append_review(entry, reviewer, opinion, REJECT, limit)
        entry["status"] = "已退回"
        entry["pending"] = True
        entry["abnormal"] = True
        suffix = "，复核人与意见已记入台账" if reviewer else ""
        return self._decorate(entry), f"配载单已退回重算{suffix}"

    # ---------- 台账与派生字段 ----------
    def _append_review(
        self,
        entry: dict[str, Any],
        reviewer: str,
        opinion: str,
        conclusion: str,
        limit: float | None,
    ) -> dict[str, Any]:
        ledger = store.rows(REVIEW_MODULE)
        entry_id = int(entry["id"])
        round_no = sum(1 for row in ledger if int(row.get("配载单", 0)) == entry_id) + 1
        record = {
            "id": max((int(row.get("id", 0)) for row in ledger), default=0) + 1,
            "配载单": entry_id,
            "配载单号": entry.get("配载单号"),
            "机型": entry.get("机型"),
            "计算重量": entry.get("计算重量"),
            "重心位置": entry.get("重心位置"),
            "包线上限": limit,
            "复核结论": conclusion,
            "复核人员": reviewer,
            "复核意见": opinion,
            "复核时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "轮次": round_no,
        }
        ledger.append(record)
        return record

    def _latest_review(self, entry_id: int) -> dict[str, Any] | None:
        matches = [
            row for row in store.rows(REVIEW_MODULE) if int(row.get("配载单", 0)) == entry_id
        ]
        return matches[-1] if matches else None

    def _decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """把配载单原始记录补成列表口径：包线、重心判定、最后一次复核结论都现场派生。"""
        result = dict(entry)
        aircraft = str(entry.get("机型") or "")
        limit = ENVELOPE_LIMITS.get(aircraft)
        cg = _to_number(entry.get("重心位置"))
        result["包线上限"] = limit
        if limit is None or cg is None:
            result["重心判定"] = "未配包线"
        else:
            result["重心判定"] = "合规" if cg <= limit else "超限"
        latest = self._latest_review(int(entry.get("id", 0)))
        if latest is not None:
            result["复核人员"] = latest["复核人员"]
            result["复核意见"] = latest["复核意见"]
            result["最新复核结论"] = latest["复核结论"]
            result["复核时间"] = latest["复核时间"]
        else:
            result.setdefault("复核人员", "")
            result["复核意见"] = ""
            result["最新复核结论"] = ""
            result["复核时间"] = ""
        result["配载状态"] = entry.get("status")
        return result
