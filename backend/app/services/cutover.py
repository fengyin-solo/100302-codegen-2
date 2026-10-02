"""割接变更工单业务规则：窗口锁定、查重打回、会签留档、断点续填、结论回写。

关键约定：
- 变更窗口在登记时定死，之后没有任何接口能改；要挪时间只能「重新报窗口」，
  原单作废留痕、新单重新走流程，原单上不许偷偷改。
- 同一网元同一变更窗口只认第一次报的那一版，重复提交原样打回。
- 会签结论按当时的规则原样归档（含规则版本与规则原文），以后规则怎么改都不动历史存档。
- 执行环节只能顺着第一个还空着的环节往下填，已确认过的环节不重做。
- 收尾/回退结论通过网元台账服务回写，别的入口读到的最近变更都是同一份。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.neledger import NeLedgerService
from app.services.schedule import IMPACT_LEVELS, ScheduleService, parse_window
from app.store import store

MODULE = "cutover"

# 状态机主线：立项 → 会签 → 待执行 → 执行中 → 已完结 / 已回退
STATUS_FLOW = ["立项", "会签", "待执行", "执行中", "已回退", "已完结"]
# 已打回：同网元同窗口重复提交；已作废：窗口改报后原单留痕
EXTRA_STATUSES = ["已打回", "已作废"]
TERMINAL_STATUSES = ["已完结", "已回退", "已打回", "已作废"]
# 查重口径：这些状态都算「已经报过」；已打回/已作废的单不占窗口
BLOCKING_STATUSES = ["立项", "会签", "待执行", "执行中", "已完结", "已回退"]

EXECUTE_STEPS = ["操作前检查", "实施割接", "业务验证", "收尾确认"]

REQUIRED_FIELDS = ["站点", "网元", "变更内容", "影响面", "窗口开始", "窗口结束", "回退方案"]

# 当前会签规则：全体会签角色都通过才算过。规则以后怎么改都行，
# 已归档的会签结论里存的是当时的规则版本与原文，不回溯。
APPROVAL_ROLES = ["网络部", "运维部", "客服部"]
APPROVAL_RULE_VERSION = "v1"
APPROVAL_RULE_TEXT = "全体会签角色（网络部/运维部/客服部）均通过方可进入执行"

# 允许重新报窗口的状态：还没进执行的单子才能挪时间
REBOOKABLE_STATUSES = ["立项", "会签", "待执行"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


class CutoverService:
    def __init__(self) -> None:
        self.schedule = ScheduleService()
        self.ledger = NeLedgerService()

    # ---------- 查询 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("工单编号", ""))
                or keyword in str(row.get("网元", ""))
                or keyword in str(row.get("站点", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def detail(self, entry_id: int) -> dict[str, Any] | None:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None
        return {
            **entry,
            "当前环节": self.current_step(entry),
            "可执行动作": self.available_actions(entry),
            "会签角色": APPROVAL_ROLES,
            "会签规则": APPROVAL_RULE_TEXT,
            # 与网元台账页读的是同一个函数、同一份数据
            "网元最近变更": self.ledger.recent_changes(str(entry.get("网元"))),
        }

    def current_step(self, entry: dict[str, Any]) -> str:
        steps = entry.get("执行环节") or []
        for step in steps:
            if not step.get("确认时间"):
                return str(step["环节"])
        return "全部已确认" if steps else "—"

    def available_actions(self, entry: dict[str, Any]) -> list[str]:
        status = entry.get("status")
        if status == "立项":
            return ["提交会签", "重新报窗口"]
        if status == "会签":
            return ["会签意见", "重新报窗口"]
        if status == "待执行":
            return ["开始执行", "重新报窗口"]
        if status == "执行中":
            return ["确认环节", "执行回退", "完结"]
        return []

    # ---------- 登记 ----------

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        record_duplicate: bool = True,
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """登记割接工单。重复提交原样打回；排期冲突输给高优先级事项时不予登记。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False
        impact = str(values.get("影响面")).strip()
        if impact not in IMPACT_LEVELS:
            return None, f"影响面须为 {'/'.join(IMPACT_LEVELS)}", False
        start = str(values.get("窗口开始")).strip()
        end = str(values.get("窗口结束")).strip()
        start_dt, end_dt = parse_window(start), parse_window(end)
        if start_dt is None or end_dt is None:
            return None, "变更窗口格式应为 YYYY-MM-DD HH:MM", False
        if not start_dt < end_dt:
            return None, "窗口开始必须早于窗口结束", False
        ne = str(values.get("网元")).strip()

        first = self._find_duplicate(ne, start, end)
        if first is not None:
            reason = f"与工单 {first['工单编号']} 同网元同变更窗口重复提交，只认第一次报的那一版"
            if not record_duplicate:
                return None, reason, False
            rejected = self._new_entry(values, ne=ne, start=start, end=end, impact=impact)
            rejected["status"] = "已打回"
            rejected["打回原因"] = reason
            rejected["pending"] = False
            rejected["abnormal"] = True
            store.rows(MODULE).append(rejected)
            return rejected, reason, False

        code = self._next_code()
        booking, message, displaced = self.schedule.book(
            kind="割接",
            ne=ne,
            start=start,
            end=end,
            impact=impact,
            title=str(values.get("变更内容")).strip()[:30],
            ref=code,
        )
        if booking is None:
            return None, message, False

        entry = self._new_entry(values, ne=ne, start=start, end=end, impact=impact)
        entry["工单编号"] = code
        entry["status"] = "立项"
        entry["窗口锁定"] = True  # 窗口自此锁死，本单没有任何接口能改
        store.rows(MODULE).append(entry)
        self._log(entry, "登记", values, f"变更窗口锁定 {start} ~ {end}")
        note = f"割接工单 {code} 已登记，变更窗口 {start} ~ {end} 已锁定"
        if displaced:
            note += f"；网元上 {len(displaced)} 条低优先级占用需改期"
        return entry, note, True

    def _find_duplicate(self, ne: str, start: str, end: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if (
                str(row.get("网元")) == ne
                and str(row.get("窗口开始")) == start
                and str(row.get("窗口结束")) == end
                and row.get("status") in BLOCKING_STATUSES
            ):
                return row
        return None

    def _new_entry(self, values: dict[str, Any], *, ne: str, start: str, end: str, impact: str) -> dict[str, Any]:
        rows = store.rows(MODULE)
        return {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "工单编号": "",  # 打回单没有编号，登记成功才发号
            "站点": str(values.get("站点")).strip(),
            "网元": ne,
            "变更内容": str(values.get("变更内容")).strip(),
            "影响面": impact,
            "窗口开始": start,
            "窗口结束": end,
            "窗口锁定": False,
            "回退方案": str(values.get("回退方案")).strip(),
            "重报自": str(values.get("重报自") or ""),
            "status": "立项",
            "当前会签": None,
            "会签存档": [],
            "执行环节": [{"环节": name, "确认人": "", "确认时间": "", "结论": "", "备注": ""} for name in EXECUTE_STEPS],
            "结论": "",
            "完结时间": "",
            "打回原因": "",
            "作废说明": "",
            "流转记录": [],
            "pending": True,
            "abnormal": False,
        }

    def _next_code(self) -> str:
        rows = store.rows(MODULE)
        seq = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        return f"CUT-{datetime.now():%Y}-{seq:04d}"

    # ---------- 动作 ----------

    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"割接工单 {entry_id} 不存在或已归档"
        handler = {
            "提交会签": self._submit_approval,
            "会签意见": self._submit_opinion,
            "开始执行": self._start_execute,
            "确认环节": self._confirm_step,
            "执行回退": self._rollback,
            "完结": self._finish,
            "重新报窗口": self._rebook_window,
        }.get(action)
        if handler is None:
            return None, f"动作「{action}」不属于割接工单可执行范围"
        return handler(entry, values)

    def _submit_approval(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "立项":
            return None, f"当前状态为「{entry.get('status')}」，只有立项中的工单才能提交会签"
        entry["status"] = "会签"
        entry["当前会签"] = {"轮次": len(entry.get("会签存档") or []) + 1, "意见": []}
        self._log(entry, "提交会签", values, f"进入第 {entry['当前会签']['轮次']} 轮会签")
        return entry, f"工单 {entry['工单编号']} 已提交会签，待 {'、'.join(APPROVAL_ROLES)} 会签"

    def _submit_opinion(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "会签":
            return None, f"当前状态为「{entry.get('status')}」，不在会签环节"
        role = str(values.get("会签角色") or "").strip()
        verdict = str(values.get("结论") or "").strip()
        opinion = str(values.get("意见") or "").strip()
        if role not in APPROVAL_ROLES:
            return None, f"会签角色须为 {'/'.join(APPROVAL_ROLES)}"
        if verdict not in ["通过", "驳回"]:
            return None, "会签结论须为 通过 或 驳回"
        if verdict == "驳回" and not opinion:
            return None, "驳回必须填写意见，说明哪里过不去"
        round_state = entry.get("当前会签") or {}
        opinions: list[dict[str, Any]] = round_state.setdefault("意见", [])
        if any(item.get("角色") == role for item in opinions):
            return None, f"{role} 本轮已提交过会签意见，不能重复提交"
        opinions.append({
            "角色": role,
            "结论": verdict,
            "意见": opinion,
            "会签人": str(values.get("操作人") or "值班管理员"),
            "时间": _now(),
        })

        if verdict == "驳回":
            self._archive_round(entry, "未通过")
            entry["status"] = "立项"
            entry["当前会签"] = None
            self._log(entry, "会签未通过", values, f"{role} 驳回：{opinion}")
            return entry, f"{role} 驳回，会签未通过，工单退回立项；本轮会签结论已原样留档"

        passed = {item["角色"] for item in opinions if item["结论"] == "通过"}
        remaining = [item for item in APPROVAL_ROLES if item not in passed]
        if remaining:
            self._log(entry, "会签意见", values, f"{role} 通过，还差 {'、'.join(remaining)}")
            return entry, f"{role} 已通过，还差 {'、'.join(remaining)} 会签"

        self._archive_round(entry, "通过")
        entry["status"] = "待执行"
        entry["当前会签"] = None
        self._log(entry, "会签通过", values, "全体会签角色通过，进入待执行")
        return entry, "全体会签通过，工单进入待执行；会签结论已原样留档"

    def _archive_round(self, entry: dict[str, Any], conclusion: str) -> None:
        """会签结论原样归档：规则版本、规则原文、每条意见都按当时的样子留底，只增不改。"""
        round_state = entry.get("当前会签") or {}
        snapshot = {
            "轮次": round_state.get("轮次", len(entry.get("会签存档") or []) + 1),
            "结论": conclusion,
            "规则版本": APPROVAL_RULE_VERSION,
            "规则原文": APPROVAL_RULE_TEXT,
            "意见": [dict(item) for item in round_state.get("意见") or []],
            "归档时间": _now(),
        }
        entry.setdefault("会签存档", []).append(snapshot)

    def _start_execute(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "待执行":
            return None, f"当前状态为「{entry.get('status')}」，会签没过的进不了执行这一档"
        archives = entry.get("会签存档") or []
        if not archives or archives[-1].get("结论") != "通过":
            return None, "没有留档的会签通过结论，进不了执行这一档"
        if self.schedule.booking_by_ref(str(entry.get("工单编号"))) is None:
            return None, "该单窗口已不在排定状态（可能被更高优先级事项挤占），请重新报窗口"
        entry["status"] = "执行中"
        self._log(entry, "开始执行", values, "进入执行中，从第一个环节往下填")
        return entry, f"工单 {entry['工单编号']} 开始执行，当前环节：{self.current_step(entry)}"

    def _confirm_step(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "执行中":
            return None, f"当前状态为「{entry.get('status')}」，只有执行中的工单才能确认环节"
        steps: list[dict[str, Any]] = entry.get("执行环节") or []
        target = str(values.get("环节") or "").strip()
        first_empty = next((index for index, step in enumerate(steps) if not step.get("确认时间")), None)
        if first_empty is None:
            return None, "所有环节都已确认，可直接办理完结"
        if any(step.get("环节") == target and step.get("确认时间") for step in steps):
            return None, f"环节「{target}」已确认过，已确认过的环节不重做"
        if target != steps[first_empty]["环节"]:
            return None, f"只能接着还空着的环节往下填，当前应填「{steps[first_empty]['环节']}」"
        step = steps[first_empty]
        step["确认人"] = str(values.get("操作人") or "值班管理员")
        step["确认时间"] = _now()
        step["结论"] = str(values.get("结论") or "正常").strip() or "正常"
        step["备注"] = str(values.get("备注") or "").strip()
        self._log(entry, "确认环节", values, f"环节「{target}」确认：{step['结论']}")
        if first_empty + 1 < len(steps):
            return entry, f"环节「{target}」已确认，下一环节：{steps[first_empty + 1]['环节']}"
        return entry, f"环节「{target}」已确认，所有环节已齐，可办理完结"

    def _rollback(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "执行中":
            return None, f"当前状态为「{entry.get('status')}」，只有执行中的工单才能回退"
        conclusion = str(values.get("回退结论") or "").strip()
        if not conclusion:
            return None, "回退必须填写回退结论"
        entry["status"] = "已回退"
        entry["结论"] = conclusion
        entry["完结时间"] = _now()
        entry["pending"] = False
        entry["abnormal"] = True
        self.schedule.release_by_ref(str(entry["工单编号"]), "割接已回退")
        self.ledger.append_change(
            str(entry["网元"]),
            kind="割接回退",
            conclusion=conclusion,
            ref=str(entry["工单编号"]),
            window=f"{entry['窗口开始']} ~ {entry['窗口结束']}",
        )
        self._log(entry, "执行回退", values, conclusion)
        return entry, f"工单 {entry['工单编号']} 已回退，回退结论已回写网元 {entry['网元']} 台账"

    def _finish(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") != "执行中":
            return None, f"当前状态为「{entry.get('status')}」，只有执行中的工单才能完结"
        steps: list[dict[str, Any]] = entry.get("执行环节") or []
        unfinished = [step["环节"] for step in steps if not step.get("确认时间")]
        if unfinished:
            return None, f"还有环节空着（{'、'.join(unfinished)}），不能完结"
        conclusion = str(values.get("收尾结论") or "").strip()
        if not conclusion:
            return None, "完结必须填写收尾结论"
        entry["status"] = "已完结"
        entry["结论"] = conclusion
        entry["完结时间"] = _now()
        entry["pending"] = False
        self.schedule.release_by_ref(str(entry["工单编号"]), "工单已完结")
        self.ledger.append_change(
            str(entry["网元"]),
            kind="割接完结",
            conclusion=conclusion,
            ref=str(entry["工单编号"]),
            window=f"{entry['窗口开始']} ~ {entry['窗口结束']}",
        )
        self._log(entry, "完结", values, conclusion)
        return entry, f"工单 {entry['工单编号']} 已完结，收尾结论已回写网元 {entry['网元']} 台账"

    def _rebook_window(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry.get("status") not in REBOOKABLE_STATUSES:
            return None, f"当前状态为「{entry.get('status')}」，只有 {'/'.join(REBOOKABLE_STATUSES)} 的工单才能重新报窗口"
        new_start = str(values.get("窗口开始") or "").strip()
        new_end = str(values.get("窗口结束") or "").strip()
        if not new_start or not new_end:
            return None, "重新报窗口必须给出新的窗口开始与窗口结束"
        new_values = {
            "站点": entry["站点"],
            "网元": entry["网元"],
            "变更内容": entry["变更内容"],
            "影响面": entry["影响面"],
            "窗口开始": new_start,
            "窗口结束": new_end,
            "回退方案": entry["回退方案"],
            "重报自": entry["工单编号"],
            "操作人": values.get("操作人"),
        }
        # 新窗口照样过查重与排期裁决；任何一步不过，原单一动不动
        new_entry, message, ok = self.create_entry(new_values, record_duplicate=False)
        if not ok or new_entry is None:
            return None, f"改报未成功：{message}（原单未改动）"
        old_code = str(entry["工单编号"])
        entry["status"] = "已作废"
        entry["作废说明"] = f"变更窗口改报，见新单 {new_entry['工单编号']}；原窗口 {entry['窗口开始']} ~ {entry['窗口结束']} 未改动"
        entry["pending"] = False
        self.schedule.release_by_ref(old_code, "窗口改报")
        self._log(entry, "重新报窗口", values, f"改报新单 {new_entry['工单编号']}，原单作废留痕")
        return new_entry, f"已重新报窗口：新单 {new_entry['工单编号']} 登记成功，原单 {old_code} 已作废留痕"

    # ---------- 痕迹 ----------

    def _log(self, entry: dict[str, Any], action: str, values: dict[str, Any], note: str) -> None:
        entry.setdefault("流转记录", []).append({
            "时间": _now(),
            "动作": action,
            "操作人": str(values.get("操作人") or "值班管理员"),
            "说明": note,
        })
