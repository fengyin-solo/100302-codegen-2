"""割接工单核心不变量验证：用真实 ASGI 应用打接口，不直接调内部函数。"""
from fastapi.testclient import TestClient

from app.main import app

c = TestClient(app)
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"{'✓' if cond else '✗'} {name}" + (f"  -> {detail}" if detail and not cond else ""))


def post(path, values=None):
    return c.post(path, json={"values": values or {}})


# 0. 种子数据
orders = c.get("/api/cutover?size=100").json()
check("种子工单 8 张", orders["total"] == 8, str(orders["total"]))

# 1. 立项必填校验
r = post("/api/cutover", {"所属站点": "X"})
check("立项缺字段被拒", r.status_code == 200 and r.json()["ok"] is False, r.text)

# 2. 窗口非法
r = post("/api/cutover", {
    "所属站点": "鼓楼枢纽", "网元编号": "NE-099", "变更类型": "测试",
    "窗口开始": "2026-11-01 05:00", "窗口结束": "2026-11-01 04:00",
    "变更内容": "c", "提报人": "q", "回退方案": "rb"})
check("窗口开始晚于结束被拒", r.json()["ok"] is False, r.json()["message"])

# 3. 同窗重复：NE-002 在 09-28 00:00-04:00 已有 CG-20260923-002
r = post("/api/cutover", {
    "所属站点": "鼓楼枢纽", "网元编号": "NE-002", "变更类型": "传输链路割接",
    "窗口开始": "2026-09-28 02:00", "窗口结束": "2026-09-28 05:00",
    "变更内容": "重复尝试", "提报人": "外协", "回退方案": "x"})
body = r.json()
check("同窗重复原样打回", body["ok"] is False, body["message"])
check("打回原因指明中标工单", body["entry"] and body["entry"]["中标工单号"] == "CG-20260923-002",
      str(body.get("entry")))
before = c.get("/api/cutover?size=100").json()["total"]
check("打回单不进主列表", before == 8, str(before))
rejected = c.get("/api/cutover/rejected").json()["items"]
check("打回记录留痕", any(x["中标工单号"] == "CG-20260923-002" for x in rejected))

# 4. 正常立项一张新网元（不与任何窗口冲突）
r = post("/api/cutover", {
    "所属站点": "江宁机房", "网元编号": "NE-777", "变更类型": "核心网板卡升级",
    "窗口开始": "2026-12-01 00:00", "窗口结束": "2026-12-01 03:00",
    "变更内容": "新板升级", "提报人": "测试员", "回退方案": "回退固件"})
o = r.json()["entry"]
oid = o["id"]
check("正常立项成功且窗口锁定提示", r.json()["ok"] and o["status"] == "立项", r.json()["message"])
check("新网元自动建台账", c.get("/api/element?keyword=NE-777").json()["total"] == 1)

# 5. 会签闸门：立项不能直接进执行
r = post(f"/api/cutover/{oid}/start")
check("立项单进不了执行", r.json()["ok"] is False)

# 提交会签；网络组先签
r = post(f"/api/cutover/{oid}/submit-sign")
check("提交会签", r.json()["ok"] and r.json()["entry"]["status"] == "会签中")
r = post(f"/api/cutover/{oid}/countersign", {"seat": "网络组", "result": "通过", "signer": "甲"})
check("仅一席通过仍是会签中", r.json()["entry"]["status"] == "会签中")
r = post(f"/api/cutover/{oid}/start")
check("会签未齐进不了执行", r.json()["ok"] is False)
# 重复签署不可改
r = post(f"/api/cutover/{oid}/countersign", {"seat": "网络组", "result": "驳回", "signer": "甲"})
check("已签署结论不可改", r.json()["ok"] is False, r.json()["message"])
post(f"/api/cutover/{oid}/countersign", {"seat": "动力组", "result": "通过", "signer": "乙"})
r = post(f"/api/cutover/{oid}/countersign", {"seat": "监控中心", "result": "通过", "signer": "丙"})
check("三方通过放行进待执行", r.json()["entry"]["status"] == "待执行")
frozen = r.json()["entry"]["会签留档"]
check("会签留档含规则版本/回退原文", frozen and frozen["规则版本"] and frozen["回退方案原文"] == "回退固件",
      str(frozen))

# 6. 断点续作：五个环节依次确认，已确认不可跳
r = post(f"/api/cutover/{oid}/start")
check("待执行进入执行中", r.json()["entry"]["status"] == "执行中")
r = post(f"/api/cutover/{oid}/steps/confirm", {"confirmer": "测试员"})
check("缺执行记录被拒", r.json()["ok"] is False)
# 确认前两个环节
post(f"/api/cutover/{oid}/steps/confirm", {"confirmer": "甲", "record": "前置检查OK"})
post(f"/api/cutover/{oid}/steps/confirm", {"confirmer": "甲", "record": "备份OK"})
# 完结前必须环节齐
r = post(f"/api/cutover/{oid}/finish", {"conclusion": "收工"})
check("环节未齐不能完结", r.json()["ok"] is False)
# 中断 -> 回待执行，已确认环节保留
r = post(f"/api/cutover/{oid}/interrupt", {"reason": "临时保障插队"})
detail = r.json()["entry"]
check("中断回待执行", detail["status"] == "待执行")
confirmed = [s for s in detail["执行环节"] if s["确认人"]]
check("中断后已确认两环节保留", len(confirmed) == 2, str([s["环节"] for s in confirmed]))
# 再进入执行，确认环节应从「配置割接」继续
post(f"/api/cutover/{oid}/start")
d = c.get(f"/api/cutover/{oid}").json()
first_empty = next(s["环节"] for s in d["执行环节"] if s["确认人"] is None)
check("重进从第一个空缺环节（配置割接）继续", first_empty == "配置割接", first_empty)
for rec in ("配置割接OK", "业务验证OK", "现场恢复OK"):
    post(f"/api/cutover/{oid}/steps/confirm", {"confirmer": "甲", "record": rec})
r = post(f"/api/cutover/{oid}/finish", {"conclusion": "割接成功，无告警"})
check("五环节齐后完结", r.json()["ok"] and r.json()["entry"]["status"] == "已完结")

# 7. 台账回写，双入口同源
led = c.get("/api/element?keyword=NE-777").json()["items"][0]
check("台账回写最近变更", led["最近变更工单号"] == o["工单号"] and led["最近变更结果"] == "已完结",
      str(led.get("最近变更工单号")))
a = c.get(f"/api/cutover/elements/NE-777/latest-change").json()
b = c.get("/api/element/code/NE-777/latest-change").json()
check("割接口与台账入口读到同一份", a["最近变更工单号"] == b["最近变更工单号"] == o["工单号"]
      and a["最近变更结论"] == "割接成功，无告警")

# 8. 会签驳回流：立项->会签->驳回->不得执行，可重新提请
r = post("/api/cutover", {
    "所属站点": "X机房", "网元编号": "NE-888", "变更类型": "路由策略调整",
    "窗口开始": "2026-12-02 00:00", "窗口结束": "2026-12-02 02:00",
    "变更内容": "调路由", "提报人": "q", "回退方案": "rb"})
oid2 = r.json()["entry"]["id"]
post(f"/api/cutover/{oid2}/submit-sign")
post(f"/api/cutover/{oid2}/countersign", {"seat": "网络组", "result": "通过", "signer": "x"})
post(f"/api/cutover/{oid2}/countersign", {"seat": "动力组", "result": "通过", "signer": "y"})
r = post(f"/api/cutover/{oid2}/countersign", {"seat": "监控中心", "result": "驳回", "signer": "z", "opinion": "窗口冲突"})
check("驳回判为会签未通过", r.json()["entry"]["status"] == "会签未通过")
check("驳回单进不了执行", post(f"/api/cutover/{oid2}/start").json()["ok"] is False)
r = post(f"/api/cutover/{oid2}/resubmit-sign")
check("可重新提请会签", r.json()["ok"] and r.json()["entry"]["status"] == "会签中")

# 9. 窗口锁死，只能重新报窗新开
src = c.get(f"/api/cutover/{oid2}").json()
r = post(f"/api/cutover/{oid2}/reschedule", {"窗口开始": "2026-12-20 01:00", "窗口结束": "2026-12-20 03:00"})
new = r.json()["entry"]
check("重新报窗新开一单", r.json()["ok"] and new["源工单号"] == src["工单号"] and new["id"] != oid2,
      r.json()["message"])
src_after = c.get(f"/api/cutover/{oid2}").json()
check("原单窗口原样不动", src_after["窗口开始"] == src["窗口开始"]
      and src_after["status"] == "会签中", str((src_after["窗口开始"], src_after["status"])))

# 10. 回退：在执行中回退，台账写已回退
r = post("/api/cutover", {
    "所属站点": "Y机房", "网元编号": "NE-999", "变更类型": "传输链路割接",
    "窗口开始": "2026-12-05 00:00", "窗口结束": "2026-12-05 03:00",
    "变更内容": "链路切换", "提报人": "q", "回退方案": "切回旧链路"})
oid3 = r.json()["entry"]["id"]
post(f"/api/cutover/{oid3}/submit-sign")
for s, who in [("网络组", "a"), ("动力组", "b"), ("监控中心", "c")]:
    post(f"/api/cutover/{oid3}/countersign", {"seat": s, "result": "通过", "signer": who})
post(f"/api/cutover/{oid3}/start")
r = post(f"/api/cutover/{oid3}/rollback", {"conclusion": "误码高，已切回"})
check("执行中可回退", r.json()["ok"] and r.json()["entry"]["status"] == "已回退")
led3 = c.get("/api/element?keyword=NE-999").json()["items"][0]
check("回退结论回写台账", led3["最近变更结果"] == "已回退" and "已切回" in led3["最近变更结论"])

# 11. 让行排程：唯一出处，告警处理>割接>巡检
sch = c.get("/api/cutover/schedule?element=NE-002").json()
grp = next(g for g in sch["分组"] if g["网元编号"] == "NE-002")
types_in_order = [(t["作业类型"], t["排序位次"]) for t in grp["任务"]]
check("NE-002 排到告警/割接/巡检三件", len(grp["任务"]) == 3, str(types_in_order))
order = [t["作业类型"] for t in grp["任务"]]
check("影响面次序 告警处理>割接>巡检", order == ["告警处理", "割接", "巡检"], str(order))
rule = sch["让行规则"]["影响面次序"]
check("规则只暴露一处且次序正确", [x["作业类型"] for x in rule] == ["告警处理", "割接", "巡检"])
patrol = next(t for t in grp["任务"] if t["作业类型"] == "巡检")
check("巡检标注让行给告警/割接", set(patrol["让路给"]) == {"ALM-0928", "CG-20260923-002"},
      str(patrol["让路给"]))

# 12. 立项/会签中/会签未通过/已完结/已回退的割接都不占窗口（只有待执行、执行中占）
ne1 = c.get("/api/cutover/schedule?element=NE-001").json()
g1 = next(g for g in ne1["分组"] if g["网元编号"] == "NE-001")
active = [t for t in g1["任务"] if t["作业类型"] == "割接"]
check("NE-001 无已放行割接占窗（005会签驳回/008立项均不计）", active == [], str([t["作业编号"] for t in active]))

# 13. 排程登记只受理巡检/告警，割接必须走工单
r = post("/api/cutover/schedule/tasks", {
    "网元编号": "NE-001", "作业类型": "割接", "作业编号": "X", "作业标题": "t",
    "窗口开始": "2026-12-09 00:00", "窗口结束": "2026-12-09 01:00"})
check("排程登记拒绝割接类型", r.json()["ok"] is False)

# 14. 种子 NE-003(执行中, 已确认2环节) 断点续作接口可用
d4 = c.get("/api/cutover/4").json()
empty = next(s["环节"] for s in d4["执行环节"] if s["确认人"] is None)
check("种子执行中单首个空缺环节=配置割接", empty == "配置割接", empty)

# 15. 看板不含割接内部表
ov = c.get("/api/overview").json()
names = {m["name"] for m in ov["modules"]}
check("概览只统计 20 个运维台账模块", len(names) == 20 and "cutover" not in names and "element" not in names,
      str(len(names)))

print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
if FAIL:
    print("失败项：", FAIL)
    raise SystemExit(1)
print("全部不变量验证通过")
