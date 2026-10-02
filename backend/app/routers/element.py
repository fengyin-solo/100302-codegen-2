"""网元台账接口：维护网元视角的最近变更，数据与割接工单同源。

割接收尾或回退时由割接服务回写本表；这里读到的最近变更，
与割接口 `/api/cutover/elements/{网元}/latest-change` 是同一份。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import PageResult
from app.services.element import ElementService

router = APIRouter(prefix="/api/element", tags=["网元台账"])

service = ElementService()

COLUMNS = ["网元编号", "网元名称", "所属站点", "网元类型", "网元状态",
           "最近变更工单号", "最近变更类型", "最近变更结果", "最近变更结论", "最近变更时间"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按网元编号或名称检索"),
    element: str | None = Query(default=None, description="按网元编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """网元台账列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, element=element, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/meta")
def meta() -> dict[str, object]:
    return {"columns": COLUMNS}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单个网元台账；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"网元台账 {entry_id} 不存在")
    return entry


@router.get("/code/{element}/latest-change")
def latest_change(element: str) -> dict[str, object]:
    """台账入口按网元编号取最近一次变更结论。"""
    latest = service.latest_change(element)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"网元 {element} 暂无台账或变更记录")
    return latest
