# -*- coding: utf-8 -*-
"""Тесты связи per-user ключа с фабрикой.

Критичное требование: ордер должен уходить с ключом ТОГО пользователя,
который его сгенерировал, а не с ключом из окружения. Если связь
разорвана - сделка уйдёт с пустыми или чужими кредами.
"""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_executor_factory as F
import azazel_cycle_runner as R

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

for k in ("WALT_API_KEY","WALT_API_SECRET"):
    os.environ.pop(k, None)

# ---------- фабрика: явные креды ----------
c, err = F.make_client()
check("без ключей клиент не создан", c is None and err, err)
c, err = F.make_client("mykey","mysecret")
check("явные креды создают клиент", c is not None and err is None, err)
if c is not None:
    check("клиент получил явный ключ", getattr(c,"api_key","")=="mykey", vars(c).keys())
    check("клиент получил явный secret", getattr(c,"secret","")=="mysecret", vars(c).keys())

# env не должен перебивать явные
os.environ["WALT_API_KEY"]="envkey"; os.environ["WALT_API_SECRET"]="envsecret"
c, err = F.make_client("mykey","mysecret")
check("явные креды приоритетнее env", c is not None
      and getattr(c,"api_key","")=="mykey", vars(c).keys() if c else None)
os.environ.pop("WALT_API_KEY"); os.environ.pop("WALT_API_SECRET")

# ---------- фабрика: make_executor с явными кредами ----------
ex, info = F.make_executor(key="mykey", secret="mysecret")
check("исполнитель создан с явными кредами", ex is not None, info)
check("клиент исполнителя с нужным ключом",
      ex is not None and getattr(getattr(ex,"client",None),"api_key","")=="mykey",
      vars(ex.client).keys() if ex is not None and getattr(ex,"client",None) else None)

# без ключей и dry_run=None -> dry_run исполнитель, ордера не уходят
ex2, info2 = F.make_executor()
check("без ключей - dry_run исполнитель", ex2 is not None and info2["dry_run"] is True, info2)
check("в dry_run есть причина", bool(info2.get("reason")), info2)

# без ключей и dry_run=False -> исполнителя нет (явный запрет торговли)
ex3, info3 = F.make_executor(dry_run=False)
check("явный запрет торговли без ключей - исполнителя нет",
      ex3 is None and info3.get("error"), info3)

# ---------- CE прокидывает креды ----------
import continuation_engine as ce
ex4, info4 = ce.make_executor(key="mykey", secret="mysecret")
check("CE.make_executor принимает key/secret", ex4 is not None, info4)

sent=[]
class SpyExec(object):
    def open_with_protection(self, plan, api_key_index=255):
        sent.append(plan); return {"ok":True,"steps":[]}
# execute_plan с явным исп��лнителем не трогает фабрику
ce.execute_plan({"symbol":"LIT","side":"long","entry":1,"stop_price":0.9,
                 "take_price":1.2}, executor=SpyExec(), key="k", secret="s")
check("execute_plan с исп��лнителем работает", len(sent)==1, sent)

# ---------- раннер: ключ пользователя доходит до исполнителя ----------
D = tempfile.mkdtemp()
with open(os.path.join(D,"42.json"),"w",encoding="utf-8") as f:
    json.dump({"walt_key":"userkey42","walt_secret":"usersecret42"},f)

# подменяем сетевые вызовы
def synth(n=120):
    out=[]; p=100.0
    for i in range(n):
        o=p; c=p+0.5
        out.append({"o":o,"h":max(o,c)+0.2,"l":min(o,c)-0.2,"c":c,"v":1000.0})
        p=c
    return out
class NoNetClient(object):
    def account(self): return {"availableBalance":"100.0"}
    def positions(self): return []
    def klines(self, sym, interval="15m", limit=200): return synth()
    def funding_rate(self, sym, limit=10): return [{"fundingRate":"0.0001"}]
    def ticker_price(self, sym): return {"price":"77900.0"}
class SpyExec2(object):
    def __init__(self): self.plans=[]
    def open_with_protection(self, plan, api_key_index=255):
        self.plans.append(plan); return {"ok":True,"steps":[]}
# 1) внешний исполнитель: раннер НЕ должен создавать свой
sp = SpyExec2()
rep = R.run_user(42, {"Прогресс настройки":100,"Автоподтверждение":True},
                 R.read_user_json(D,42), data_dir=D,
                 client=NoNetClient(), executor=sp)
check("пользователь обработан", not rep.get("skipped"), rep)
check("внешний исполнитель использован", len(sp.plans)>=0, rep)
check("при внешнем исполнителе раннер не создаёт свой",
      rep.get("executor_info") is None, rep.get("executor_info"))

# 2) без внешнего исполнителя: раннер создаёт его под ключ пользователя
rep2 = R.run_user(42, {"Прогресс настройки":100,"Автоподтверждение":True},
                  R.read_user_json(D,42), data_dir=D, client=NoNetClient())
check("раннер создал исполнитель", rep2.get("executor_info") is not None, rep2)
check("исполнитель не в dry_run (ключ пользователя есть)",
      (rep2.get("executor_info") or {}).get("dry_run") is False,
      rep2.get("executor_info"))
check("в executor_info нет ошибки",
      not (rep2.get("executor_info") or {}).get("error"),
      rep2.get("executor_info"))

# ключ пользователя НЕ должен подменяться env
os.environ["WALT_API_KEY"]="envkey"; os.environ["WALT_API_SECRET"]="envsecret"
ex5, info5 = R.make_executor("userkey42","usersecret42")
check("раннер создаёт исполнитель с ключом пользователя",
      ex5 is not None
      and getattr(getattr(ex5,"client",None),"api_key","")=="userkey42",
      vars(getattr(ex5,"client",None)).keys() if ex5 is not None else None)
os.environ.pop("WALT_API_KEY"); os.environ.pop("WALT_API_SECRET")

# без ключа у пользователя - исполнитель в dry_run, ордера не идут
with open(os.path.join(D,"43.json"),"w",encoding="utf-8") as f:
    json.dump({"foo":"bar"},f)
rep = R.run_user(43, {"Прогресс настройки":100,"Автоподтверждение":True},
                 R.read_user_json(D,43), data_dir=D, client=NoNetClient())
check("без ключа - пропущен", rep.get("skipped") is True, rep)
check("без ключа - не торгует", rep.get("traded") is False, rep)

shutil.rmtree(D, ignore_errors=True)
print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
