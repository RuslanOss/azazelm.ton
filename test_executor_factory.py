# -*- coding: utf-8 -*-
"""Тесты фабрики исполнителей.

Главное требование: фабрика НИКОГДА не должна ронять движок из-за
отсутствия ключей. Без ключей она обязана отработать в dry_run и
честно сказать почему.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_executor_factory as F

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

def clear_env():
    for k in (F.ENV_KEY, F.ENV_SECRET, F.ENV_URL, F.ENV_EXCHANGE, F.ENV_DRY_RUN):
        os.environ.pop(k, None)

# ---------- без ключей ----------
clear_env()
check("биржа по умолчанию walt", F.exchange_name()=="walt", F.exchange_name())
check("ключей нет -> credentials_available False", F.credentials_available() is False)
c,err = F.make_client()
check("make_client без ключей -> ошибка, не исключение", c is None and err, err)
check("ошибка называет переменные", "WALT_API_KEY" in (err or ""), err)

ex, info = F.make_executor()
check("make_executor без ключей не падает", ex is not None, info)
check("без ключей -> dry_run", info["dry_run"] is True, info)
check("без ключей -> причина объяснена", "dry_run" in info["reason"], info)
check("исполнитель действительно dry_run", getattr(ex,"dry_run",None) is True, info)

ex, info = F.make_executor(dry_run=False)
check("явный запрет торговли без ключей -> исполнителя нет", ex is None, info)
check("и причина ясна", "WALT_API_KEY" in (info.get("error") or ""), info)

# ---------- с ключами ----------
os.environ[F.ENV_KEY]="testkey"
os.environ[F.ENV_SECRET]="testsecret"
check("ключи есть -> credentials_available True", F.credentials_available() is True)
ex, info = F.make_executor()
check("с ключами создаётся исполнитель", ex is not None, info)
check("с ключами -> не dry_run по умолчанию", info["dry_run"] is False, info)
check("исполнитель Walt", type(ex).__name__=="WaltExecutor", type(ex).__name__)
check("клиент внутри живой", getattr(ex,"client",None) is not None, ex)
check("причина называет Walt", "Walt" in info["reason"], info)

# dry_run через env
os.environ[F.ENV_DRY_RUN]="1"
ex, info = F.make_executor()
check("AZAZEL_DRY_RUN=1 -> dry_run", info["dry_run"] is True, info)
check("исполнитель в dry_run", getattr(ex,"dry_run",None) is True, info)
os.environ.pop(F.ENV_DRY_RUN)

# явный dry_run=True поверх ключей
ex, info = F.make_executor(dry_run=True)
check("явный dry_run=True -> dry_run", info["dry_run"] is True, info)

# ---------- переключение биржи ----------
os.environ[F.ENV_EXCHANGE]="lighter"
check("биржа переключается", F.exchange_name()=="lighter", F.exchange_name())
ex, info = F.make_executor()
check("для lighter исполнитель создаётся или честная ошибка",
      ex is not None or info.get("error"), info)

os.environ[F.ENV_EXCHANGE]="walt"
check("возврат к walt", F.exchange_name()=="walt", F.exchange_name())

# ---------- min_notional пробрасывается ----------
ex, info = F.make_executor(min_notional=25.0)
check("min_notional пробрасывается в исполнитель",
      getattr(ex,"min_notional",None)==25.0, getattr(ex,"min_notional",None))

# ---------- исполнения не происходит ----------
clear_env()
ex, info = F.make_executor()
called=[]
class Spy(object):
    def open_position(self,*a,**k):
        called.append((a,k)); return {"orderId":1}
ex.client = Spy()
plan={"symbol":"LIT","side":"long","entry":100.0,"stop_price":97.0,
      "take_price":106.0,"leverage":5,"units":2.5,"margin_usd":50,
      "notional_usd":250.0}
r = ex.open_with_protection(plan)
check("dry_run не шлёт ордер", len(called)==0, called)
check("dry_run возвращает ok", r["ok"], r)

clear_env()
print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
