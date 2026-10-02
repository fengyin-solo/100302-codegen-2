"""网元台账入口：读的是和割接服务同一张 element 表。

割接完结/回退在 CutoverService 里回写，这里只负责按台账视角查询，
不另存任何「最近变更」，因此两个入口永远取到同一份数据。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "element"


class ElementService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        element: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("网元编号", "")) or keyword in str(r.get("网元名称", ""))]
        if element:
            rows = [r for r in rows if element in str(r.get("网元编号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def latest_change(self, element: str) -> dict[str, Any] | None:
        """按网元编号取最近一次割接结论；割接口的台账回写就是这份。"""
        row = next((r for r in store.rows(MODULE) if str(r.get("网元编号", "")) == element), None)
        if row is None:
            return None
        return {
            "网元编号": row.get("网元编号"),
            "最近变更工单号": row.get("最近变更工单号"),
            "最近变更类型": row.get("最近变更类型"),
            "最近变更结果": row.get("最近变更结果"),
            "最近变更结论": row.get("最近变更结论"),
            "最近变更时间": row.get("最近变更时间"),
            "数据来源": "网元台账（与割接工单同源）",
        }
