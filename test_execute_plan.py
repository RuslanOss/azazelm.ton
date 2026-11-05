# -*- coding: utf-8 -*-
"""Тесты обёртки execute_plan в CE."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_test_guard  # izolyaciya ot boevoy Airtable/Telegram
import continuation_engine as ce
import azazel_executor_factory as F

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

for k in (F.ENV_KEY,F.ENV_SECRET,F.ENV_EXCHANGE,F.ENV_DRY_RUN):
    os.environ.pop(k,None)

plan = {"symbol":"LIT","side":"long","entry":100.0,"stop_loss":97.0,
        "take_profit":106.0,"leverage":5,"margin_usd":50}

# без ключей -> dry_run, ордер не уходит
res = ce.execute_plan(plan)
check("execute_plan без ключей не падает", isinstance(res,dict), res)
check("execute_plan без ключей -> ok (dry_run)", res["ok"], res)
check("ошибка объясняет отсутствие ключей",
      "WALT_API_KEY" in (res.get("executor_info",{}).get("error") or ""), res)

# план из open_position (имена полей CE)
op = {"symbol":"LIT","side":"long","price":100.0,"stop_loss":97.0,
      "take_profit":106.0,"leverage":5,"margin_usd":50,"units":2.5}
res = ce.execute_plan(op)
check("план из open_position принимается", res["ok"], res)

# make_executor в CE
ex, info = ce.make_executor()
check("ce.make_executor отдаёт исполнителя", ex is not None, info)
check("ce.make_executor -> dry_run без ключей", info["dry_run"] is True, info)

# executor передан явно - фабрика не вызывается
class Spy(object):
    def __init__(self): self.plans=[]
    def open_with_protection(self, plan, api_key_index=255):
        self.plans.append(plan); return {"ok":True,"steps":[]}
sp = Spy()
res = ce.execute_plan(plan, executor=sp)
check("явный исполнитель используется", len(sp.plans)==1, sp.plans)
check("план нормализован: stop_price есть", "stop_price" in sp.plans[0], sp.plans)
check("план нормализован: take_price есть", "take_price" in sp.plans[0], sp.plans)
check("план нормализован: entry есть", "entry" in sp.plans[0], sp.plans)

# исполнитель падает - execute_plan не должен бросать
class Boom(object):
    def open_with_protection(self, plan, api_key_index=255):
        raise RuntimeError("упало")
res = ce.execute_plan(plan, executor=Boom())
check("упавший исполнитель не роняет CE", not res["ok"], res)
check("причина падения в error", "упало" in (res.get("error") or ""), res)

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
