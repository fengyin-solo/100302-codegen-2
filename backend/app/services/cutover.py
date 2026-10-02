"""割接变更工单业务规则：状态机、窗口锁定、判重、断点续作、台账回写都收在这里。

关键约束（路由层不做业务判断）：
- 变更窗口在立项时定下即锁死，没有任何改窗口入口；要挪时间只能「重新报窗」新开一单；
- 同网元同一变更窗口（窗口重叠）重复报割接，只认提交最早的那一版，晚单原样打回；
- 会签三方全部通过才放行进待执行，任意一方驳回即判为会签未通过；
- 执行环节按序确认、已确认不可改；中断后从第一个空缺环节继续；
- 完结/回退结论回写网元台账，台账只有一份数据，割接口和台账入口读同一张表；
- 会签通过时把结论、回退方案、规则版本原样留档，之后规则升级不改旧档。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from app.services import scheduling
from app.services.scheduling import windows_overlap
from app.store import store

MODULE = "cutover"
REJECT_MODULE = "cutover_rejected"
ELEMENT_MODULE = "element"
TASK_MODULE = "element_task"

# 状态沿这一条主线往下走，不允许跳档。
STATUS_INIT = "立项"
STATUS_SIGNING = "会签中"
STATUS_SIGN_REJECTED = "会签未通过"
STATUS_READY = "待执行"
STATUS_RUNNING = "执行中"
STATUS_ROLLED = "已回退"
STATUS_DONE = "已完结"

STEPS = ["前置检查", "数据备份", "配置割接", "业务验证", "现场恢复"]
SIGN_SEATS = ["网络组", "动力组", "监控中心"]
RULE_VERSION = "割接会签规则 2026.10 版"

REQUIRED_FIELDS = ["所属站点", "网元编号", "变更类型", "窗口开始", "窗口结束", "变更内容", "提报人", "回退方案"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _normalize_window(value: Any) -> str:
    """把 2026-10-05T00:00 统一成 2026-10-05 00:00，保证窗口可按字符串比较。"""
    return str(value or "").strip().replace("T", " ")


class CutoverService:
    # ---------------- 列表 / 明细 ----------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        element: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [r for r in rows if keyword in str(r.get("工单号", ""))]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if element:
            rows = [r for r in rows if element in str(r.get("网元编号", ""))]
        rows = sorted(rows, key=lambda r: str(r.get("提报时间", "")), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def stats(self) -> list[dict[str, object]]:
        rows = store.rows(MODULE)
        return [
            {"label": "待我处理（会签/待执行）", "value": sum(1 for r in rows if r.get("status") in (STATUS_SIGNING, STATUS_READY))},
            {"label": "执行中", "value": sum(1 for r in rows if r.get("status") == STATUS_RUNNING)},
            {"label": "已回退", "value": sum(1 for r in rows if r.get("status") == STATUS_ROLLED)},
            {"label": "重复打回（累计）", "value": len(store.rows(REJECT_MODULE))},
        ]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------------- 立项 ----------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        """立项：窗口此处定死。返回 (工单, 缺字段, 打回记录)，三态互斥。"""
        missing = [f for f in REQUIRED_FIELDS if not str(values.get(f) or "").strip()]
        if missing:
            return None, missing, None

        start = _normalize_window(values["窗口开始"])
        end = _normalize_window(values["窗口结束"])
        if not start < end:
            return None, ["变更窗口开始时间必须早于结束时间"], None

        element = str(values["网元编号"]).strip()
        submitted = _now()
        duplicate = self._find_winner(element, start, end)
        if duplicate is not None:
            # 后来的原样打回：只留一份打回记录，不进主单列表。
            rejected = store.insert(REJECT_MODULE, {
                "打回工单号": self._next_reject_no(submitted),
                "网元编号": element,
                "变更类型": str(values["变更类型"]).strip(),
                "窗口开始": start,
                "窗口结束": end,
                "提报人": str(values["提报人"]).strip(),
                "提报时间": submitted,
                "中标工单号": str(duplicate.get("工单号")),
                "打回原因": f"同一网元 {element} 在同一变更窗口已有先报工单 {duplicate.get('工单号')}，"
                           f"重复提交原样打回，只认第一次报的版本",
            })
            return None, [], rejected

        entry = self._build_order(values, start, end, submitted)
        store.insert(MODULE, entry)
        self._ensure_element(element, str(values.get("所属站点", "")).strip())
        return entry, [], None

    def _build_order(self, values: dict[str, Any], start: str, end: str, submitted: str,
                     source_no: str | None = None) -> dict[str, Any]:
        order = {
            "status": STATUS_INIT,
            "pending": True,
            "abnormal": False,
            "工单号": self._next_order_no(submitted),
            "所属站点": str(values["所属站点"]).strip(),
            "网元编号": str(values["网元编号"]).strip(),
            "变更类型": str(values["变更类型"]).strip(),
            "窗口开始": start,
            "窗口结束": end,
            "变更内容": str(values["变更内容"]).strip(),
            "提报人": str(values["提报人"]).strip(),
            "提报时间": submitted,
            "回退方案": str(values["回退方案"]).strip(),
            "源工单号": source_no,
            "会签席位": [{"席位": s, "结论": None, "意见": "", "签署时间": None, "签署人": None} for s in SIGN_SEATS],
            "会签留档": None,
            "执行环节": [{"环节": s, "确认人": None, "确认时间": None, "执行记录": ""} for s in STEPS],
            "完结结论": "",
            "完结时间": "",
            "流转日志": [{"时间": submitted, "环节": "立项",
                        "说明": (f"{values['提报人']} 提报割接工单" +
                                (f"，由 {source_no} 重新报窗新开" if source_no else ""))}],
        }
        return order

    def _find_winner(self, element: str, start: str, end: str,
                     exclude_id: int | None = None) -> dict[str, Any] | None:
        """同网元 + 窗口重叠即同一窗口；中标者是提交最早的那一版。"""
        candidates = [
            r for r in store.rows(MODULE)
            if r.get("id") != exclude_id
            and str(r.get("网元编号", "")) == element
            and windows_overlap(start, end, str(r.get("窗口开始")), str(r.get("窗口结束")))
        ]
        return min(candidates, key=lambda r: (str(r.get("提报时间", "")), int(r.get("id", 0))), default=None)

    def _next_order_no(self, submitted: str) -> str:
        day = submitted[:10].replace("-", "")
        prefix = f"CG-{day}-"
        seq = sum(1 for r in store.rows(MODULE) if str(r.get("工单号", "")).startswith(prefix)) + 1
        return f"{prefix}{seq:03d}"

    def _next_reject_no(self, submitted: str) -> str:
        day = submitted[:10].replace("-", "")
        prefix = f"CG-{day}-"
        seq = sum(1 for r in store.rows(REJECT_MODULE) if str(r.get("打回工单号", "")).startswith(prefix)) + 1
        return f"{prefix}{seq:03d}"

    def _ensure_element(self, element: str, site: str) -> dict[str, Any]:
        """网元台账是唯一一份：新网元首次报割接时自动建档。"""
        return store.upsert(ELEMENT_MODULE, "网元编号", element, {
            "id": store.next_id(ELEMENT_MODULE),
            "网元名称": "",
            "所属站点": site,
            "网元类型": "",
            "网元状态": "在役",
        })

    # ---------------- 会签 ----------------
    def submit_for_sign(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_INIT:
            return None, "只有立项中的工单可以提交会签"
        entry["status"] = STATUS_SIGNING
        self._log(entry, "会签", f"{entry['提报人']} 提交三方会签")
        return entry, "已提交会签，待网络组、动力组、监控中心签署"

    def countersign(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        seat = str(values.get("seat") or values.get("席位") or "").strip()
        result = str(values.get("result") or values.get("结论") or "").strip()
        signer = str(values.get("signer") or values.get("签署人") or "").strip()
        opinion = str(values.get("opinion") or values.get("意见") or "").strip()

        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_SIGNING:
            return None, "只有会签中的工单可以签署"
        target = next((s for s in entry["会签席位"] if s["席位"] == seat), None)
        if target is None:
            return None, f"会签席位「{seat}」不存在，应为 {'、'.join(SIGN_SEATS)} 之一"
        if target["结论"] is not None:
            return None, f"{seat} 已签署，会签结论不可更改"
        if result not in ("通过", "驳回"):
            return None, "会签结论只能是「通过」或「驳回」"
        if not signer:
            return None, "需要填写签署人"

        target.update({"结论": result, "意见": opinion, "签署时间": _now(), "签署人": signer})
        self._log(entry, "会签", f"{seat}（{signer}）结论：{result}")

        if result == "驳回":
            entry["status"] = STATUS_SIGN_REJECTED
            entry["abnormal"] = True
            return entry, f"{seat} 驳回，会签未通过，本单不得进入执行"

        if all(s["结论"] == "通过" for s in entry["会签席位"]):
            entry["status"] = STATUS_READY
            # 会签结论原样留档：连回退方案原文和当时规则版本一起冻结。
            entry["会签留档"] = {
                "规则版本": RULE_VERSION,
                "回退方案原文": copy.deepcopy(entry["回退方案"]),
                "会签结论": copy.deepcopy(entry["会签席位"]),
                "留档时间": _now(),
            }
            self._log(entry, "会签", "三方会签全部通过，结论已按当前规则留档，等待执行窗口")
            return entry, "三方会签全部通过，已进入待执行"
        return entry, f"{seat} 已签署通过，等待其余席位会签"

    def resubmit_sign(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """会签被驳回后按要求改齐，可重新提请会签；上一轮结论原样保留在日志里。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_SIGN_REJECTED:
            return None, "只有会签未通过的工单可以重新提请会签"
        entry["会签席位"] = [{"席位": s, "结论": None, "意见": "", "签署时间": None, "签署人": None} for s in SIGN_SEATS]
        entry["status"] = STATUS_SIGNING
        entry["abnormal"] = False
        self._log(entry, "会签", "按驳回意见改齐后重新提请会签，上一轮结论已留在流转日志中")
        return entry, "已重新提请会签"

    # ---------------- 执行：断点续作 ----------------
    def start_execution(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        # 会签没过的进不了执行这一档；待执行既含首次放行，也含中断后重新进来。
        if entry["status"] != STATUS_READY:
            return None, "只有会签通过、处于待执行的工单能进入执行"
        entry["status"] = STATUS_RUNNING
        self._log(entry, "执行", "进入执行窗口，从第一个尚未确认的环节开始")
        return entry, "已进入执行"

    def confirm_step(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        record = str(values.get("record") or values.get("执行记录") or "").strip()
        confirmer = str(values.get("confirmer") or values.get("确认人") or "").strip()

        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_RUNNING:
            return None, "只有执行中的工单可以确认执行环节"
        step = next((s for s in entry["执行环节"] if s["确认人"] is None), None)
        if step is None:
            return None, "五个执行环节均已确认，请完结工单"
        if not record or not confirmer:
            return None, f"请填写「{step['环节']}」的执行记录与确认人"

        step["确认人"] = confirmer
        step["确认时间"] = _now()
        step["执行记录"] = record
        self._log(entry, "执行", f"环节「{step['环节']}」已由 {confirmer} 确认")
        remaining = sum(1 for s in entry["执行环节"] if s["确认人"] is None)
        if remaining:
            return entry, f"「{step['环节']}」已确认，还剩 {remaining} 个环节，已确认环节不再重做"
        return entry, "五个执行环节全部确认，可以完结工单"

    def interrupt(self, entry_id: int, reason: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_RUNNING:
            return None, "只有执行中的工单可以中断"
        entry["status"] = STATUS_READY
        self._log(entry, "中断", (reason or "执行中断") + "，已确认环节保留，重新进来从空缺环节继续")
        return entry, "已中断：工单回到待执行，已确认环节不重做"

    def finish(self, entry_id: int, conclusion: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_RUNNING:
            return None, "只有执行中的工单可以完结"
        if any(s["确认人"] is None for s in entry["执行环节"]):
            return None, "还有执行环节未确认，不能完结"
        if not str(conclusion or "").strip():
            return None, "需要填写收尾结论"
        at = _now()
        entry["status"] = STATUS_DONE
        entry["pending"] = False
        entry["abnormal"] = False
        entry["完结结论"] = str(conclusion).strip()
        entry["完结时间"] = at
        self._write_ledger(entry, STATUS_DONE, at)
        self._log(entry, "完结", "五个环节全部确认，收尾结论已回写网元台账")
        return entry, "割接已完结，结论已回写网元台账"

    def rollback(self, entry_id: int, conclusion: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        if entry["status"] not in (STATUS_RUNNING, STATUS_READY):
            return None, "只有会签通过、处于执行中或待执行的工单可以按预案回退"
        if not str(conclusion or "").strip():
            return None, "需要填写回退结论"
        at = _now()
        entry["status"] = STATUS_ROLLED
        entry["pending"] = False
        entry["abnormal"] = True
        entry["完结结论"] = str(conclusion).strip()
        entry["完结时间"] = at
        self._write_ledger(entry, STATUS_ROLLED, at)
        self._log(entry, "回退", "按会签通过的回退方案回退，结论已回写网元台账")
        return entry, "已按预案回退，结论已回写网元台账"

    # ---------------- 挪窗口：重新报窗 ----------------
    def reschedule(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
        """窗口锁死后唯一的挪时间方式：以原单为据新开一单，原单原样不动。"""
        source = store.find(MODULE, entry_id)
        if source is None:
            return None, [f"割接工单 {entry_id} 不存在或已归档"], None
        start = _normalize_window(values.get("窗口开始"))
        end = _normalize_window(values.get("窗口结束"))
        if not start or not end:
            return None, ["需要填写新窗口的开始与结束时间"], None
        if not start < end:
            return None, ["变更窗口开始时间必须早于结束时间"], None

        element = str(source["网元编号"])
        submitted = _now()
        duplicate = self._find_winner(element, start, end)
        if duplicate is not None:
            rejected = store.insert(REJECT_MODULE, {
                "打回工单号": self._next_reject_no(submitted),
                "网元编号": element,
                "变更类型": str(source["变更类型"]),
                "窗口开始": start,
                "窗口结束": end,
                "提报人": str(values.get("提报人") or source["提报人"]).strip(),
                "提报时间": submitted,
                "中标工单号": str(duplicate.get("工单号")),
                "打回原因": f"重新报窗的窗口与先报工单 {duplicate.get('工单号')} 冲突，原样打回",
            })
            return None, [], rejected

        new_values = dict(source)
        new_values["变更内容"] = str(values.get("变更内容") or source["变更内容"])
        new_values["提报人"] = str(values.get("提报人") or source["提报人"])
        new_values["窗口开始"] = start
        new_values["窗口结束"] = end
        entry = self._build_order(new_values, start, end, submitted, source_no=str(source["工单号"]))
        store.insert(MODULE, entry)
        self._log(source, "重新报窗", f"窗口锁定不得改，已另开新单 {entry['工单号']}（{start} ~ {end}），原单保留")
        return entry, [], None

    # ---------------- 台账回写 ----------------
    def _write_ledger(self, entry: dict[str, Any], result: str, at: str) -> None:
        existing = next((r for r in store.rows(ELEMENT_MODULE) if r.get("网元编号") == entry["网元编号"]), {})
        store.upsert(ELEMENT_MODULE, "网元编号", str(entry["网元编号"]), {
            "网元名称": existing.get("网元名称", ""),
            "网元类型": existing.get("网元类型", ""),
            "所属站点": entry["所属站点"],
            "网元状态": "在役",
            "最近变更工单号": entry["工单号"],
            "最近变更类型": entry["变更类型"],
            "最近变更结论": entry["完结结论"],
            "最近变更结果": result,
            "最近变更时间": at,
        })

    # ---------------- 让行排程 ----------------
    def add_task(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        task_type = str(values.get("作业类型") or "").strip()
        if task_type not in ("巡检", "告警处理"):
            return None, "排程登记只受理巡检、告警处理；割接必须走割接工单立项"
        missing = [f for f in ("网元编号", "作业编号", "作业标题", "窗口开始", "窗口结束") if not str(values.get(f) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        start, end = _normalize_window(values["窗口开始"]), _normalize_window(values["窗口结束"])
        if not start < end:
            return None, "作业窗口开始时间必须早于结束时间"
        task = store.insert(TASK_MODULE, {
            "网元编号": str(values["网元编号"]).strip(),
            "作业类型": task_type,
            "作业编号": str(values["作业编号"]).strip(),
            "作业标题": str(values["作业标题"]).strip(),
            "窗口开始": start,
            "窗口结束": end,
            "提报人": str(values.get("提报人") or "").strip(),
            "提交时间": _now(),
        })
        return task, "作业已纳入同网元让行排程"

    def schedule(self, element: str | None = None) -> dict[str, Any]:
        """按网元汇总同窗口的割接/巡检/告警处理，次序只取 scheduling 一处的规则。"""
        merged: list[dict[str, Any]] = [dict(t) for t in store.rows(TASK_MODULE)]
        for order in store.rows(MODULE):
            # 只有会签已放行（待执行/执行中）的割接才真正占用窗口：
            # 立项、会签中、会签未通过的单随时可能改期或被驳回，不算占窗；
            # 已完结/已回退属于历史，也不再占窗口。
            if order.get("status") not in (STATUS_READY, STATUS_RUNNING):
                continue
            merged.append({
                "网元编号": order["网元编号"],
                "作业类型": "割接",
                "作业编号": order["工单号"],
                "作业标题": order["变更内容"],
                "窗口开始": order["窗口开始"],
                "窗口结束": order["窗口结束"],
                "提报人": order["提报人"],
                "提交时间": order["提报时间"],
                "来源": "割接工单",
            })
        if element:
            merged = [t for t in merged if t["网元编号"] == element]

        elements = sorted({t["网元编号"] for t in merged})
        groups: list[dict[str, Any]] = []
        for ne in elements:
            tasks = [dict(t) for t in merged if t["网元编号"] == ne]
            self._mark_conflicts(tasks)
            groups.append({"网元编号": ne, "任务": scheduling.sort_tasks(tasks),
                           "冲突数": sum(1 for t in tasks if t["窗口冲突"])})
        return {"让行规则": scheduling.priority_rule(), "分组": groups}

    def _mark_conflicts(self, tasks: list[dict[str, Any]]) -> None:
        for task in tasks:
            task["窗口冲突"] = any(
                other is not task
                and windows_overlap(task["窗口开始"], task["窗口结束"],
                                    other["窗口开始"], other["窗口结束"])
                for other in tasks
            )
            task["让路给"] = [
                other["作业编号"]
                for other in tasks
                if other is not task
                and windows_overlap(task["窗口开始"], task["窗口结束"],
                                    other["窗口开始"], other["窗口结束"])
                and scheduling.impact_of(other["作业类型"]) > scheduling.impact_of(task["作业类型"])
            ]

    # ---------------- 打回记录 ----------------
    def list_rejected(self, element: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(REJECT_MODULE)
        if element:
            rows = [r for r in rows if r.get("网元编号") == element]
        return sorted(rows, key=lambda r: str(r.get("提报时间", "")), reverse=True)

    def _log(self, entry: dict[str, Any], stage: str, message: str) -> None:
        entry.setdefault("流转日志", []).append({"时间": _now(), "环节": stage, "说明": message})
