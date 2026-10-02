"""割接变更工单接口。

状态流转全部落在服务层：窗口锁死、同窗判重、会签闸门、断点续作、
台账回写、会签留档都不允许在路由层自行判断。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.cutover import CutoverService
from app.services.element import ElementService

router = APIRouter(prefix="/api/cutover", tags=["割接变更"])

service = CutoverService()
element_service = ElementService()

COLUMNS = ["工单号", "所属站点", "网元编号", "变更类型", "窗口开始", "窗口结束",
           "提报人", "源工单号", "status"]
STATUSES = ["立项", "会签中", "会签未通过", "待执行", "执行中", "已回退", "已完结"]
# 各状态下界面上可点的动作，最终是否放行仍由服务层判定。
STATUS_ACTIONS = {
    "立项": ["提交会签"],
    "会签中": ["会签通过", "会签驳回"],
    "会签未通过": ["重新提请会签", "重新报窗"],
    "待执行": ["进入执行", "执行回退", "重新报窗"],
    "执行中": ["确认下一环节", "中断执行", "执行回退"],
    "已回退": ["重新报窗"],
    "已完结": [],
}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按工单号检索"),
    status: str | None = Query(default=None, description="立项/会签中/会签未通过/待执行/执行中/已回退/已完结"),
    element: str | None = Query(default=None, description="按网元编号过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按工单号、状态、网元过滤割接工单；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, element=element, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/meta")
def meta() -> dict[str, object]:
    """给前端提供状态序列与各状态可执行动作，避免前端再硬编码一份。"""
    return {"columns": COLUMNS, "statuses": STATUSES, "status_actions": STATUS_ACTIONS, "stats": service.stats()}


@router.get("/rejected")
def list_rejected(element: str | None = Query(default=None, description="按网元编号过滤打回记录")) -> dict[str, object]:
    """重复提交的工单不进主列表，在这里查打回留痕与中标工单号。"""
    return {"items": service.list_rejected(element)}


@router.get("/schedule")
def schedule(element: str | None = Query(default=None, description="按网元编号过滤排程")) -> dict[str, object]:
    """同一网元割接/巡检/告警处理的让行次序，影响面次序只此一处口径。"""
    return service.schedule(element)


@router.post("/schedule/tasks", response_model=ActionResult)
def add_schedule_task(payload: EntryPayload) -> ActionResult:
    """登记一条巡检或告警处理作业参与同网元排程；割接必须走工单立项。"""
    task, message = service.add_task(payload.values)
    if task is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=task)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单张割接工单的会签席位、执行环节、留档与流转日志。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"割接工单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """立项开单：窗口此处定死；同网元同窗重复提交原样打回。"""
    entry, missing, rejected = service.create_entry(payload.values)
    if rejected is not None:
        return ActionResult(ok=False, message=rejected["打回原因"], entry=rejected)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段或窗口不合法：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"割接工单已立项，窗口已锁定：{entry['工单号']}", entry=entry)  # type: ignore[index]


@router.post("/{entry_id}/submit-sign", response_model=ActionResult)
def submit_sign(entry_id: int) -> ActionResult:
    """立项工单提交三方会签。"""
    entry, message = service.submit_for_sign(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/countersign", response_model=ActionResult)
def countersign(entry_id: int, payload: EntryPayload) -> ActionResult:
    """某个会签席位签署通过/驳回；已签署的不可改，全部通过则放行并留档。"""
    entry, message = service.countersign(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/resubmit-sign", response_model=ActionResult)
def resubmit_sign(entry_id: int) -> ActionResult:
    """会签被驳回、按意见改齐后重新提请会签。"""
    entry, message = service.resubmit_sign(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/start", response_model=ActionResult)
def start_execution(entry_id: int) -> ActionResult:
    """待执行工单进入执行；会签没过的单会被服务层拦下。"""
    entry, message = service.start_execution(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/steps/confirm", response_model=ActionResult)
def confirm_step(entry_id: int, payload: EntryPayload) -> ActionResult:
    """确认当前第一个还空着的执行环节，已确认的环节不重做。"""
    entry, message = service.confirm_step(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/interrupt", response_model=ActionResult)
def interrupt(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行中断：回待执行，已确认环节保留，后续接着填空缺环节。"""
    reason = str(payload.values.get("reason") or payload.values.get("原因") or "").strip()
    entry, message = service.interrupt(entry_id, reason)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/finish", response_model=ActionResult)
def finish(entry_id: int, payload: EntryPayload) -> ActionResult:
    """五个环节确认齐后收尾完结，结论回写网元台账。"""
    conclusion = str(payload.values.get("conclusion") or payload.values.get("完结结论") or "").strip()
    entry, message = service.finish(entry_id, conclusion)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/rollback", response_model=ActionResult)
def rollback(entry_id: int, payload: EntryPayload) -> ActionResult:
    """按会签通过的回退方案回退，结论回写网元台账。"""
    conclusion = str(payload.values.get("conclusion") or payload.values.get("回退结论") or "").strip()
    entry, message = service.rollback(entry_id, conclusion)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/reschedule", response_model=ActionResult)
def reschedule(entry_id: int, payload: EntryPayload) -> ActionResult:
    """窗口锁死后挪时间的唯一方式：重新报窗新开一单，原单不许改。"""
    entry, missing, rejected = service.reschedule(entry_id, payload.values)
    if rejected is not None:
        return ActionResult(ok=False, message=rejected["打回原因"], entry=rejected)
    if missing:
        return ActionResult(ok=False, message="；".join(missing))
    return ActionResult(ok=True, message=f"已重新报窗，新单 {entry['工单号']}，原单保留不动", entry=entry)  # type: ignore[index]


@router.get("/elements/{element}/latest-change")
def element_latest_change(element: str) -> dict[str, object]:
    """割接侧视角读取某网元最近变更，与网元台账入口是同一份数据。"""
    latest = element_service.latest_change(element)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"网元 {element} 暂无台账或变更记录")
    return latest
