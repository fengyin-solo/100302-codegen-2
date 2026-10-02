"""网元台账接口：网元清单与最近变更。

最近变更与割接工单详情里读到的经的是同一个服务函数、同一份数据；
割接收尾/回退结论也只经这一个台账写回，不存在第二本账。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.neledger import NeLedgerService

router = APIRouter(prefix="/api/neledger", tags=["网元台账"])

service = NeLedgerService()


@router.get("")
def list_nes(
    keyword: str | None = Query(default=None, description="按网元编号、网元名称检索"),
) -> dict:
    """网元清单，每条带变更条数与最近变更时间。"""
    items = service.list_nes(keyword=keyword)
    return {"items": items, "total": len(items)}


@router.get("/{ne_id}")
def get_ne(ne_id: str) -> dict:
    """单个网元台账：基础信息加最近变更（与割接工单详情读到的是同一份）。"""
    ne = service.get_ne(ne_id)
    if ne is None:
        raise HTTPException(status_code=404, detail=f"网元 {ne_id} 不存在或已退网")
    return {**ne, "最近变更": service.recent_changes(ne_id)}
