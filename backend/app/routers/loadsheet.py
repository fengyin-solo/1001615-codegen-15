"""载重平衡接口：维护配载单与复核台账，覆盖提交复核、确认配载、退回重算等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.loadsheet import LoadsheetService

router = APIRouter(prefix="/api/loadsheet", tags=["载重平衡"])

service = LoadsheetService()

LIST_FIELDS = [
    "配载单号", "关联航班", "机型", "计算重量", "重心位置", "包线上限", "重心判定",
    "油量数据", "配载人员", "复核人员", "复核意见", "最新复核结论", "复核时间", "配载状态",
]
REVIEW_FIELDS = [
    "配载单号", "机型", "计算重量", "重心位置", "包线上限", "复核结论",
    "复核人员", "复核意见", "复核时间", "轮次",
]
STATUSES = ["待计算", "待复核", "已确认", "已退回"]


@router.get("/summary")
def summary() -> dict[str, Any]:
    """载重平衡汇总口径：与列表、台账同源，重量合计实时计算。"""
    return service.summary()


@router.get("/reviews")
def list_reviews(
    keyword: str | None = Query(default=None, description="按配载单号检索台账"),
) -> dict[str, Any]:
    """复核台账：每次送复核都留痕，重复送复核以轮次最大的一条为最后结论。"""
    items = service.list_reviews(keyword=keyword)
    return {"module": "loadsheet_review", "total": len(items), "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按配载单号检索"),
    status: str | None = Query(default=None, description="待计算、待复核、已确认、已退回"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按配载单号与状态过滤载重平衡列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出载重平衡清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "loadsheet", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条配载单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"配载单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条配载单，重量与重心位置一并录入；缺字段或数值不合法时说明原因。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="配载单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条配载单执行提交复核、确认配载、退回重算；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.pop("action", "") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
