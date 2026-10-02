"""网元台账：割接收尾/回退结论的唯一写回处，最近变更的唯一读取处。

割接工单完结或回退时把结论经 append_change() 追加进变更记录；割接工单详情、
网元台账页等所有入口都经 recent_changes() 读同一份数据，避免两处各存一份对不上。
变更记录只增不改，当时的结论原样留底。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE_NE = "neledger"
MODULE_CHANGES = "nechanges"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class NeLedgerService:
    def list_nes(self, keyword: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE_NE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("网元编号", "")) or keyword in str(row.get("网元名称", ""))
            ]
        result = []
        for row in rows:
            changes = self.recent_changes(str(row.get("网元编号")))
            result.append({**row, "变更条数": len(changes), "最近变更时间": changes[0]["时间"] if changes else "—"})
        return result

    def get_ne(self, ne_id: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE_NE):
            if str(row.get("网元编号")) == str(ne_id):
                return row
        return None

    def recent_changes(self, ne_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """最近变更唯一读取口：所有页面、所有模块都从这里拿同一份。"""
        rows = [row for row in store.rows(MODULE_CHANGES) if str(row.get("网元")) == str(ne_id)]
        rows.sort(key=lambda row: (str(row.get("时间") or ""), int(row.get("id") or 0)), reverse=True)
        return rows[:limit]

    def append_change(self, ne_id: str, *, kind: str, conclusion: str, ref: str, window: str) -> dict[str, Any]:
        """最近变更唯一写入口：只允许追加，不提供修改。"""
        rows = store.rows(MODULE_CHANGES)
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "网元": str(ne_id),
            "类型": kind,
            "结论": str(conclusion),
            "来源工单": str(ref),
            "变更窗口": window,
            "时间": _now(),
            "pending": False,
            "abnormal": kind == "割接回退",
        }
        rows.append(record)
        ne = self.get_ne(ne_id)
        if ne is not None:
            ne["最近变更时间"] = record["时间"]
        return record
