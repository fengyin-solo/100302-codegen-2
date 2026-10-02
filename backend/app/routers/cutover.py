"""割接变更工单接口：登记、会签、执行、回退、完结与窗口改报。

注意这里故意不提供「修改工单」接口：变更窗口登记即锁定，要挪时间只能走
「重新报窗口」动作（原单作废留痕、新单重走流程），原单上不许偷偷改。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cutover import EXTRA_STATUSES, STATUS_FLOW, CutoverService

router = APIRouter(prefix="/api/cutover", tags=["割接变更"])

service = CutoverService()

STATUSES = STATUS_FLOW + EXTRA_STATUSES


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工单编号、网元、站点检索"),
    status: str | None = Query(default=None, description="立项、会签、待执行、执行中、已回退、已完结、已打回、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按关键字与状态过滤割接工单列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出割接工单清单：返回当前全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "cutover", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条工单详情：含会签存档、执行环节、流转记录与网元最近变更。"""
    detail = service.detail(entry_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"割接工单 {entry_id} 不存在或已归档")
    return detail


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记割接工单；同网元同窗口重复提交原样打回，排期冲突输给高优先级事项时不予登记。"""
    entry, message, ok = service.create_entry(payload.values)
    return ActionResult(ok=ok, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条工单执行提交会签、会签意见、开始执行、确认环节、执行回退、完结、重新报窗口。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
