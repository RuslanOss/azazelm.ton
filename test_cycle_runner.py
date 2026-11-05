# -*- coding: utf-8 -*-
"""Тесты раннера автономного цикла.

Критичные требования:
  * пользователь без ключа Walt НЕ запускается;
  * пользователь без настроек НЕ запускается;
  * автоподтверждение выключено - ордера не уходят;
  * дневные счётчики сбрасываются при смене дня;
  * позиции Walt переводятся в формат движка;
  * ошибка одного пользователя не роняет прогон остальных.
"""
import sys, os, json, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_test_guard  # izolyaciya ot boevoy Airtable/Telegram
import azazel_cycle_runner as R

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

D = tempfile.mkdtemp()
def mkuser(uid, **kw):
    p = os.path.join(D, str(uid)+".json")
    with open(p,"w",encoding="utf-8") as f: json.dump(kw,f)
    return p

# ---------- список пользователей ----------
mkuser(1, walt_key="k", walt_secret="s")
mkuser(2, walt_key="k", walt_secret="s")
os.makedirs(os.path.join(D,"sub"), exist_ok=True)
with open(os.path.join(D,"notanumber.json"),"w") as f: f.write("{}")
users = R.list_users(D)
check("найдены только числовые uid", users==[1,2], users)

# ---------- допуск пользователя ----------
ok,why = R.eligible({}, {"walt_key":"k","walt_secret":"s"})
check("с ключом и без прогресса - не готов", not ok, why)
ok,why = R.eligible({"Прогресс настройки":100}, {"walt_key":"k","walt_secret":"s"})
check("с прогрессом 100 - готов", ok, why)
ok,why = R.eligible({"Прогресс настройки":50}, {"walt_key":"k","walt_secret":"s"})
check("прогресс 50 - не готов", not ok, why)
ok,why = R.eligible({"Прогресс настройки":100}, {})
check("без ключа - не готов", not ok, why)
check("причина называет ключ", "ключ" in why.lower(), why)
ok,why = R.eligible({"Прогресс настройки":100}, {"foo":"bar"})
check("профиль есть, ключа нет - не готов", not ok, why)
check("причина уточняет ключ", "ключ" in why.lower(), why)
ok,why = R.eligible({}, None)
check("профиля нет - нет профиля", not ok and "профил" in why.lower(), why)
ok,why = R.eligible({"Прогресс настройки":100,"Подписка":"активна"},
                     {"walt_key":"k","walt_secret":"s"})
check("с активной подпиской - готов", ok, why)
ok,why = R.eligible({"Прогресс настройки":100,"Подписка":"нет"},
                     {"walt_key":"k","walt_secret":"s"})
check("без подписки - не готов", not ok, why)

# ---------- состояние ----------
st = {"positions":[{"symbol":"LITUSDT"}], "trades_today":3, "pnl_today":-5.0}
R.save_state(D, 1, st)
loaded = R.load_state(D, 1)
check("состояние сохранилось", loaded["trades_today"]==3, loaded)
check("позиции сохранились", loaded["positions"]==st["positions"], loaded)
check("счётчики сохранены", loaded["pnl_today"]==-5.0, loaded)

# ключ не теряется при записи состояния
j = R.read_user_json(D,1)
check("ключ Walt не затёрт", j.get("walt_key")=="k", j)

# ---------- дневной сброс ----------
s2 = {"day":"2000-01-01","trades_today":5,"stops_today":2,"pnl_today":-10.0}
changed = R.roll_day(s2)
check("смена дня сбрасывает счётчики", changed and s2["trades_today"]==0, s2)
check("сбросил стопы", s2["stops_today"]==0, s2)
check("сбросил pnl", s2["pnl_today"]==0.0, s2)
s3 = {"day":R.today_str(),"trades_today":5}
check("в тот же день не сбрасывает", R.roll_day(s3) is False and s3["trades_today"]==5, s3)

# ---------- перевод позиций ----------
ps = [{"symbol":"LITUSDT","side":"long","positionAmt":"2.5","entryPrice":"100.0",
       "unRealizedProfit":"1.5"},
      {"symbol":"BTCUSDT","positionAmt":"-1.0","entryPrice":"77000"}]
out = R.positions_to_state(ps)
check("позиций две", len(out)==2, out)
check("лонг распознан", out[0]["side"]=="long", out[0])
check("шорт по знаку amount", out[1]["side"]=="short", out[1])
check("размер по модулю", out[0]["size"]==2.5, out[0])
check("цена входа", out[0]["entry"]==100.0, out[0])
check("неизвестный pnl -> 0", out[1]["unrealized_pnl"]==0.0, out[1])

# ---------- fetch_account_state ----------
class FakeAcc(object):
    def account(self): return {"availableBalance":"250.5"}
    def positions(self): return [{"symbol":"LITUSDT","side":"long","positionAmt":"1"}]
a = R.fetch_account_state(FakeAcc())
check("маржа прочитана", a["free_margin"]==250.5, a)
check("позиции прочитаны", len(a["positions"])==1, a)
a2 = R.fetch_account_state(None)
check("без клиента - ошибка, не исключение", a2["error"], a2)
class Broken(object):
    def account(self): raise Exception("сеть")
    def positions(self): raise Exception("сеть")
a3 = R.fetch_account_state(Broken())
check("битый клиент не роняет", a3["error"] and a3["free_margin"]==0.0, a3)

# ---------- run_user: пропуски ----------
rep = R.run_user(99, {}, {}, data_dir=D)
check("без профиля - пропущен", rep["skipped"] is True, rep)
check("причина названа", bool(rep["reason"]), rep)

# пользователь без ключа в профиле
mkuser(5, foo="bar")
rep = R.run_user(5, {"Прогресс настройки":100}, R.read_user_json(D,5), data_dir=D)
check("без ключа - пропущен", rep["skipped"] is True, rep)
check("не торгует", rep.get("traded") is False, rep)

# ---------- run_all не падает ----------
def gp(uid): return {"Прогресс настройки":100}
class NoNet(object):
    def account(self): return {"availableBalance":"100.0"}
    def positions(self): return []
res = R.run_all(D, gp, log=None, client=NoNet())
check("run_all отработал", isinstance(res,dict) and "ran" in res, res)
check("пропущенные посчитаны", res["skipped"]>=1, res)
check("отчётов по пользователям", isinstance(res["reports"],list), res)

# ---------- сбой в get_profile не роняет прогон ----------
def bad_gp(uid): raise Exception("airtable упал")
res2 = R.run_all(D, bad_gp, client=NoNet())
check("сбой профиля не роняет прогон", isinstance(res2,dict), res2)
check("пользователи всё равно обработаны", res2["ran"]+res2["skipped"]>=1, res2)

shutil.rmtree(D, ignore_errors=True)
print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
