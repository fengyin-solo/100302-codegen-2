"""同一网元上多类作业的让行排序规则。

割接、巡检、告警处理挤在同一窗口时谁先谁后，只允许写在这一个文件里：
服务层算排程、前端展示次序都从这里取，避免两处各维护一份口径。
影响面数字越大，影响面越大，越要先排。
"""
from __future__ import annotations

from typing import Any

# 唯一的优先级出处：数字越大影响面越大，同窗口先排。
TASK_IMPACT: dict[str, int] = {
    "告警处理": 3,
    "割接": 2,
    "巡检": 1,
}

IMPACT_LABEL: dict[int, str] = {
    3: "高·影响面大",
    2: "中·业务变更",
    1: "低·例行作业",
}


def impact_of(task_type: str) -> int:
    """未知作业类型按最低影响面处理，不允许在调用方各自兜底。"""
    return TASK_IMPACT.get(task_type, 0)


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按影响面降序排；影响面相同时按最早提交时间排，先报的先做。

    排序结果直接写回每条记录（影响面、排序位次），调用方拿到即可展示。
    """
    ordered = sorted(
        tasks,
        key=lambda task: (-impact_of(str(task.get("作业类型", ""))),
                          str(task.get("提交时间", "")),
                          int(task.get("id", 0))),
    )
    for index, task in enumerate(ordered, start=1):
        task["影响面"] = impact_of(str(task.get("作业类型", "")))
        task["影响面说明"] = IMPACT_LABEL.get(task["影响面"], "未定级")
        task["排序位次"] = index
    return ordered


def windows_overlap(start_a: str, end_a: str, start_b: str, end_b: str) -> bool:
    """两个窗口是否重叠（端点相接不算同一窗口）。时间统一成可比较的字符串。"""
    return start_a < end_b and start_b < end_a


def priority_rule() -> dict[str, object]:
    """对外暴露当前生效的让行规则，便于页面标注「按哪版规则排的」。"""
    return {
        "规则说明": "同一窗口内按影响面大者先排，同影响面按最早提交时间排",
        "影响面次序": [
            {"作业类型": name, "影响面": level, "说明": IMPACT_LABEL[level]}
            for name, level in sorted(TASK_IMPACT.items(), key=lambda item: -item[1])
        ],
    }
