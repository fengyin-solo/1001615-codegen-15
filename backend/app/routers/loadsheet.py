"""载重平衡接口：维护配载单、机型包线判限、复核台账与汇总口径。

确认配载、退回重算两个入口与原来一致，仍走 /actions；
执行这两个动作时须一并提交复核人与复核意见，结论写入复核台账。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.loadsheet import LoadsheetService

router = APIRouter(prefix="/api/loadsheet", tags=["载重平衡"])

service = LoadsheetService()

LIST_FIELDS = [
    "配载单号", "关联航班", "机型", "计算重量", "重心位置",
    "重心合规", "油量数据", "配载人员", "复核人员", "复核意见", "复核结论", "配载状态",
]
STATUSES = ["待计算", "待复核", "已确认", "已退回"]
# 需要落复核台账的两个动作（入口照旧，只是多录复核人与意见）。
REVIEW_ACTIONS = {"确认配载": "确认", "退回重算": "退回"}


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


@router.get("/envelope")
def list_envelope() -> dict[str, Any]:
    """机型重心包线上限：复核判限与前端提示共用这一份配置。"""
    return {"items": service.list_envelope()}


@router.get("/summary")
def summary() -> dict[str, Any]:
    """载重平衡汇总：配载单数量、退回重算数与重量合计，和列表、台账同一口径。"""
    return service.summary()


@router.get("/reviews", response_model=PageResult[dict])
def list_reviews(
    loadsheet_id: int | None = Query(default=None, description="按配载单ID过滤"),
    keyword: str | None = Query(default=None, description="按配载单号检索"),
    only_latest: bool = Query(default=False, description="为 true 时每张配载单只取最后一次结论"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """复核台账：默认保留每次送复核记录；only_latest 时按最后一次结论去重。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_reviews(
        loadsheet_id=loadsheet_id,
        keyword=keyword,
        only_latest=only_latest,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出载重平衡清单：返回全量配载单、复核台账与汇总，三者同一口径。"""
    items, total = service.list_entries(page=1, size=10000)
    reviews, review_total = service.list_reviews(page=1, size=10000)
    return {
        "module": "loadsheet",
        "total": total,
        "items": items,
        "review_total": review_total,
        "reviews": reviews,
        "summary": service.summary(),
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条配载单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"配载单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条配载单，计算重量与重心位置一并录入；缺字段时说明原因。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="配载单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对配载单执行动作。

    提交复核照旧直接流转；确认配载、退回重算须带复核人与复核意见，
    会按机型包线判限并登记复核台账，同人复核或超限确认都会被拦下。
    """
    values = payload.values
    action = str(values.get("action") or "").strip()
    if action in REVIEW_ACTIONS:
        record, message = service.submit_review(
            entry_id,
            decision=REVIEW_ACTIONS[action],
            reviewer=str(values.get("复核人") or values.get("复核人员") or ""),
            comment=str(values.get("复核意见") or payload.remark or ""),
        )
        if record is None:
            return ActionResult(ok=False, message=message)
        return ActionResult(ok=True, message=message, entry=record)

    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
