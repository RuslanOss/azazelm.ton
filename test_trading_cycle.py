# -*- coding: utf-8 -*-
"""Тесты торгового цикла.

Критичные требования:
  * без ключа Walt цикл НЕ падает и НЕ торгует;
  * auto_confirm по умолчанию ВЫКЛ - планы готовятся, ордера не идут;
  * профиль из Airtable попадает в extra движка;
  * один сбойный шаг не роняет весь цикл;
  * цикл НЕ ходит в сеть, если клиент подставлен.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_test_guard  # izolyaciya ot boevoy Airtable/Telegram
import azazel_trading_cycle as TC

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

def synth_up(n=120, start=100.0, step=0.5, vol=1000.0):
    out=[]; p=start
    for i in range(n):
        o=p; c=p+step+(0.3 if i%7==0 else -0.1)
        out.append({"o":o,"h":max(o,c)+0.2,"l":min(o,c)-0.2,"c":c,
                    "v":vol*(1+(i%5)*0.1)})
        p=c
    return out

class FakeClient(object):
    """Мок клиента Walt. Никаких сетевых вызовов."""
    def __init__(self, fail=(), n=120):
        self.fail=fail; self.n=n; self.calls=[]
    def klines(self, sym, interval="15m", limit=200):
        self.calls.append(("klines",sym))
        if sym in self.fail: raise Exception("свечи недоступны")
        return synth_up(self.n)
    def funding_rate(self, sym, limit=10):
        self.calls.append(("funding",sym))
        return [{"fundingRate":"0.0001"}]
    def ticker_price(self, sym):
        self.calls.append(("ticker",sym))
        return {"price":"77900.0"}

# ---------- профиль -> extra ----------
e = TC.profile_to_extra({"Стоп альты %": 4, "Мин R:R": 3,
                          "Плечо альты": 3, "Автоподтверждение": True})
check("профиль -> stop_alts", e["stop_alts"]==4.0, e)
check("профиль -> rr", e["rr"]==3.0, e)
check("профиль -> lev_alts", e["lev_alts"]==3.0, e)
check("неизвестные поля игнорируются", "Хрень" not in e, e)
check("пустой профиль -> пустой extra", TC.profile_to_extra({})=={}, TC.profile_to_extra({}))
check("None-поля пропускаются", "stop_alts" not in TC.profile_to_extra({"Стоп альты %":None}), None)
check("пустые строки пропускаются", "rr" not in TC.profile_to_extra({"Мин R:R":""}), None)

# ---------- collect_market ----------
fc = FakeClient()
m = TC.collect_market(fc, ["BTC","ETH"])
check("свечи собраны для обоих символов", len(m["candles"])==2, list(m["candles"]))
check("тикер с суффиксом", "BTCUSDT" in m["candles"], list(m["candles"]))
check("фандинг собран", m["funding"].get("BTCUSDT") is not None, m["funding"])
check("BTC-контекст есть", m["btc_ctx"] and m["btc_ctx"]["price"]==77900.0, m["btc_ctx"])
check("сопротивление = максимум хайов", m["btc_ctx"]["resistance"]>=101.0, m["btc_ctx"])

fc2 = FakeClient(fail=("BTCUSDT",))
m2 = TC.collect_market(fc2, ["BTC","ETH"])
check("сбой по одному символу не роняет сбор",
      len(m2["candles"])==1 and m2["errors"], (list(m2["candles"]), m2["errors"]))

m3 = TC.collect_market(None, ["BTC"])
check("без клиента - понятная ошибка", m3["errors"] and not m3["candles"], m3)

# ---------- build_candidates ----------
m4 = TC.collect_market(FakeClient(), ["BTC"])
cands = TC.build_candidates(m4)
check("кандидат собран", len(cands)==1, cands)
check("символ без суффикса", cands[0]["symbol"]=="BTC", cands[0]["symbol"])
check("цена из последней свечи", cands[0]["price"]>0, cands[0]["price"])
check("btc_ctx прокинут в кандидата", cands[0]["btc_ctx"] is not None, cands[0])

# ---------- run_cycle: автоподтверждение выключено ----------
rep = TC.run_cycle(profile={}, state={"free_margin":500},
                    symbols=["BTC"], client=FakeClient())
check("цикл не падает", isinstance(rep,dict) and rep["stage"], rep)
check("auto_confirm по умолчанию выключен", rep.get("auto_confirm") is False, rep)
check("цикл не торгует при выключенном автоподтверждении", rep["traded"] is False, rep)
check("причина объяснена", bool(rep.get("reason")), rep)
check("рынок собран", (rep.get("market") or {}).get("candles",0)>=1, rep.get("market"))
check("решения получены", isinstance(rep.get("entries"),list), rep.get("entries"))

# ---------- автоподтверждение включено, но маржи нет ----------
rep = TC.run_cycle(profile={"Автоподтверждение": True},
                    state={"free_margin":0}, symbols=["BTC"], client=FakeClient())
check("без маржи не торгует", rep["traded"] is False, rep)
check("причина - нет маржи", "марж" in (rep.get("reason") or "").lower(), rep)

# ---------- автоподтверждение по профилю ----------
rep = TC.run_cycle(profile={"Автоподтверждение": True},
                    state={"free_margin":500}, symbols=["BTC"], client=FakeClient())
check("профиль автоподтверждения учтён", rep.get("auto_confirm") is True, rep)

# ---------- исполнение через подставной исполнитель ----------
sent=[]
class SpyExec(object):
    def open_with_protection(self, plan, api_key_index=255):
        sent.append(plan); return {"ok":True,"steps":[{"op":"open","ok":True}]}
rep = TC.run_cycle(profile={"Автоподтверждение": True},
                    state={"free_margin":500}, symbols=["BTC"],
                    executor=SpyExec(), client=FakeClient())
check("исполнения отработали без исключения", isinstance(rep["executed"],list), rep)
if sent:
    check("план исполнен и торг отмечен", rep["traded"] is True, rep)
    check("в плане есть символ и стоп", sent[0].get("symbol") and sent[0].get("stop_loss"), sent[0])
else:
    check("без входов цикл честно отработал",
          rep["traded"] is False and bool(rep.get("reason")), rep)

# ---------- клиент подставлен: сеть не трогается ----------
fc = FakeClient()
TC.run_cycle(profile={}, state={"free_margin":500}, symbols=["BTC"], client=fc)
check("использован подставленный клиент",
      any(c[0]=="klines" for c in fc.calls), fc.calls)

# ---------- сбойный клиент не роняет цикл ----------
rep = TC.run_cycle(profile={}, state={"free_margin":500}, symbols=["BTC"],
                    client=FakeClient(fail=("BTCUSDT","ETHUSDT")))
check("все символы упали - цикл не падает", isinstance(rep,dict), rep)
check("причина - рынок не собран", "рынок" in (rep.get("reason") or ""), rep)

# ---------- кривые аргументы ----------
rep = TC.run_cycle(profile=None, state=None, symbols=None, client=FakeClient())
check("пустые аргументы не роняют цикл", isinstance(rep,dict) and rep["stage"], rep)

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
