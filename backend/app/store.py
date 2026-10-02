"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
割接变更域（工单、打回记录、网元台账、让行任务）的数据由 cutover_seed 单独维护。
"""
from __future__ import annotations

from typing import Any

from app.cutover_seed import build_cutover_seeds
from app.seed import SEED_ROWS

# 看板/概览只统计通用运维台账模块；割接域内部表不进看板卡片，避免重复计数。
OVERVIEW_TABLES = list(SEED_ROWS.keys())


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        for name, rows in build_cutover_seeds().items():
            self._tables[name] = [dict(row) for row in rows]

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_id(self, module: str) -> int:
        return max((int(row.get("id", 0)) for row in self.rows(module)), default=0) + 1

    def insert(self, module: str, row: dict[str, Any]) -> dict[str, Any]:
        row.setdefault("id", self.next_id(module))
        self.rows(module).append(row)
        return row

    def upsert(self, module: str, key_field: str, key_value: str, values: dict[str, Any]) -> dict[str, Any]:
        """按业务键存在则更新、不存在则插入。

        网元台账只有一张表：割接服务回写和台账入口读取都经过这里，
        保证「另一个入口读到的最近变更」与割接侧是同一份数据。
        """
        rows = self.rows(module)
        for row in rows:
            if str(row.get(key_field, "")) == key_value:
                row.update(values)
                return row
        values[key_field] = key_value
        return self.insert(module, values)

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in OVERVIEW_TABLES:
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
