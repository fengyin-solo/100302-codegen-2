"""网元窗口排期：割接、巡检、告警处理在同一网元上互相让路的唯一裁决处。

谁先谁后只在这一处定义（priority_key）：影响面大的先排；影响面相同，先报的先排。
割接工单、巡检、告警处理要占用网元窗口都必须走 book()，各模块不许再写一套自己的
比较逻辑——否则几个人各拿一张离线排期表对着干的老问题又会回来。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "schedule"
KINDS = ["割接", "巡检", "告警处理"]
IMPACT_LEVELS = ["低", "中", "高"]
WINDOW_FORMAT = "%Y-%m-%d %H:%M"

_IMPACT_SCORE = {"低": 1, "中": 2, "高": 3}


def impact_score(level: Any) -> int:
    return _IMPACT_SCORE.get(str(level or "").strip(), 0)


def priority_key(booking: dict[str, Any]) -> tuple[int, str, int]:
    """唯一的排队口径：影响面大者优先；同级先报先得，再按编号兜底。"""
    return (
        -impact_score(booking.get("影响面")),
        str(booking.get("提交时间") or ""),
        int(booking.get("id") or 0),
    )


def parse_window(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or "").strip(), WINDOW_FORMAT)
    except ValueError:
        return None


def _now() -> str:
    return datetime.now().strftime(WINDOW_FORMAT)


class ScheduleService:
    """网元窗口的占用、让路与释放。"""

    def bookings(self, ne: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        if ne:
            rows = [row for row in rows if str(row.get("网元")) == str(ne)]
        return sorted(rows, key=priority_key)

    def booking_by_ref(self, ref: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("来源单号")) == str(ref) and row.get("状态") == "已排定":
                return row
        return None

    def book(
        self,
        *,
        kind: str,
        ne: str,
        start: str,
        end: str,
        impact: str,
        title: str,
        ref: str = "",
    ) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]]]:
        """占用一个网元窗口；与已有占用冲突时按 priority_key 裁决，输的一方让路。"""
        kind = str(kind or "").strip()
        ne = str(ne or "").strip()
        title = str(title or "").strip()
        impact = str(impact or "").strip()
        if kind not in KINDS:
            return None, f"占用类型「{kind}」不在 {'/'.join(KINDS)} 范围内", []
        if not ne:
            return None, "网元不能为空", []
        if impact not in IMPACT_LEVELS:
            return None, f"影响面须为 {'/'.join(IMPACT_LEVELS)}", []
        start_dt, end_dt = parse_window(start), parse_window(end)
        if start_dt is None or end_dt is None:
            return None, f"变更窗口格式应为 YYYY-MM-DD HH:MM", []
        if not start_dt < end_dt:
            return None, "窗口开始必须早于窗口结束", []

        rows = store.rows(MODULE)
        conflicts = [
            row
            for row in rows
            if str(row.get("网元")) == ne
            and row.get("状态") == "已排定"
            and start_dt < parse_window(row.get("窗口结束"))
            and parse_window(row.get("窗口开始")) < end_dt
        ]
        candidate: dict[str, Any] = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "网元": ne,
            "类型": kind,
            "事项": title or f"{ne}{kind}",
            "窗口开始": str(start).strip(),
            "窗口结束": str(end).strip(),
            "影响面": impact,
            "状态": "已排定",
            "来源单号": str(ref or ""),
            "提交时间": _now(),
            "让路说明": "",
            "pending": False,
            "abnormal": False,
        }
        blockers = [row for row in conflicts if priority_key(row) < priority_key(candidate)]
        if blockers:
            top = sorted(blockers, key=priority_key)[0]
            return (
                None,
                f"网元 {ne} 该窗口与{top['类型']}《{top['事项']}》冲突："
                f"按影响面排序（{top['影响面']}优先于{impact}，同级先报先得），本次需让路",
                [],
            )
        displaced: list[dict[str, Any]] = []
        for row in conflicts:
            row["状态"] = "需改期"
            row["让路说明"] = f"让路给{kind}《{candidate['事项']}》（影响面{impact}）"
            row["pending"] = True
            displaced.append(row)
        rows.append(candidate)
        message = f"网元 {ne} 窗口已排定"
        if displaced:
            message += f"，{len(displaced)} 条低优先级占用需改期"
        return candidate, message, displaced

    def release_by_ref(self, ref: str, reason: str) -> None:
        """释放某个来源单号占着的窗口（完结、回退、改报时调用），记录保留备查。"""
        for row in store.rows(MODULE):
            if str(row.get("来源单号")) == str(ref) and row.get("状态") == "已排定":
                row["状态"] = "已释放"
                row["让路说明"] = reason
                row["pending"] = False
