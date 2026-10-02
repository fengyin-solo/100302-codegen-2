"""网元窗口排期接口：巡检、告警处理在这里登记占用；割接占用随割接工单登记。

谁先谁后的裁决口径只在 services/schedule.py 一处，本接口只是透传。
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import ActionResult, EntryPayload
from app.services.schedule import ScheduleService

router = APIRouter(prefix="/api/schedule", tags=["窗口排期"])

service = ScheduleService()


@router.get("")
def list_bookings(
    ne: str | None = Query(default=None, description="按网元编号过滤"),
) -> dict:
    """网元窗口占用列表，按统一口径（影响面优先、同级先报先得）排序。"""
    items = service.bookings(ne=ne)
    return {"items": items, "total": len(items)}


@router.post("/book", response_model=ActionResult)
def book(payload: EntryPayload) -> ActionResult:
    """登记巡检或告警处理的窗口占用；与已有占用冲突时按统一口径裁决谁让路。"""
    values = payload.values
    kind = str(values.get("类型") or "").strip()
    if kind == "割接":
        return ActionResult(ok=False, message="割接占用请通过割接工单登记，窗口随工单锁定")
    booking, message, _displaced = service.book(
        kind=kind,
        ne=str(values.get("网元") or ""),
        start=str(values.get("窗口开始") or ""),
        end=str(values.get("窗口结束") or ""),
        impact=str(values.get("影响面") or ""),
        title=str(values.get("事项") or ""),
        ref=str(values.get("来源单号") or ""),
    )
    return ActionResult(ok=booking is not None, message=message, entry=booking)
