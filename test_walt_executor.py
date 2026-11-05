# -*- coding: utf-8 -*-
"""Тесты исполнителя Walt.

Главное, что тут проверяется: защита (стоп и тейк) должна уходить В СОМ
ордере с позицией. Если стоп падает отдельным запросом, между ордером
и стопом есть окно, в котором позиция живёт без защиты - именно в таком
окне в каскаде 23.10 сработали четыре позиции разом.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_test_guard  # izolyaciya ot boevoy Airtable/Telegram
from azazel_walt_executor import WaltExecutor, walt_symbol

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))


class FakeClient(object):
    """Мок клиента Walt: записывает вызовы, умеет падать."""
    def __init__(self, fail_on=None, price=100.0):
        self.calls=[]; self.fail_on=fail_on; self.price=price
    def set_leverage(self, symbol, leverage):
        self.calls.append(("set_leverage", symbol, leverage))
        if self.fail_on=="set_leverage": raise Exception("леверидж не встал")
        return {"ok":True}
    def open_position(self, symbol, side, margin_usd=None, leverage=None,
                      stop_loss=None, take_profit=None, quantity=None,
                      reduce_only=False, position_side=None):
        self.calls.append(("open_position", symbol, side, margin_usd, leverage,
                           stop_loss, take_profit, quantity))
        if self.fail_on=="open": raise Exception("ордер отклонён биржей")
        return {"orderId": 12345, "avgPrice":"100.5", "executedQty":"2.5"}
    def close_position(self, symbol, quantity=None, position_side=None):
        self.calls.append(("close_position", symbol, quantity))
        if self.fail_on=="close": raise Exception("закрытие не прошло")
        return {"orderId": 777}
    def set_algo_tpsl(self, symbol, stop_loss=None, take_profit=None,
                      side=None, quantity=None):
        self.calls.append(("set_algo_tpsl", symbol, stop_loss, take_profit))
        return {"ok":True}
    def positions(self):
        return [{"symbol":"LITUSDT","side":"long","size":2.5}]
    def cancel_order(self, symbol, order_id):
        self.calls.append(("cancel_order", symbol, order_id))
        return {"ok":True}

PLAN_LONG = {"symbol":"LIT","side":"long","entry":100.0,"stop_price":97.0,
             "take_price":106.0,"leverage":5,"units":2.5,"margin_usd":50,
             "notional_usd":250.0}
PLAN_SHORT = {"symbol":"LIT","side":"short","entry":100.0,"stop_price":103.0,
              "take_price":94.0,"leverage":5,"units":2.5,"margin_usd":50,
              "notional_usd":250.0}

# ---------- тикеры ----------
check("LIT -> LITUSDT", walt_symbol("LIT")=="LITUSDT", walt_symbol("LIT"))
check("BTC -> BTCUSDT", walt_symbol("btc")=="BTCUSDT", walt_symbol("btc"))
check("уже с суффиксом не меняется", walt_symbol("BTCUSDT")=="BTCUSDT", walt_symbol("BTCUSDT"))
check("USDT-суффикс не дублируется", walt_symbol("LITUSDT")=="LITUSDT")

# ---------- открытие ----------
c=FakeClient(); ex=WaltExecutor(c)
r=ex.open_with_protection(PLAN_LONG)
check("открытие успешно", r["ok"], r)
check("order_id возвращён", r.get("order_id")==12345, r)
ops=[x[0] for x in c.calls]
check("сначала плечо, потом ордер", ops==["set_leverage","open_position"], ops)
op=[x for x in c.calls if x[0]=="open_position"][0]
check("символ переведён в тикер Walt", op[1]=="LITUSDT", op)
check("стоп уходит В СОМ ордере", op[5]==97.0, op)
check("тейк уходит В СОМ ордере", op[6]==106.0, op)
check("плечо передано", op[4]==5, op)
check("quantity передан", op[7]==2.5, op)
check("НЕТ отдельного вызова algoOrder", "set_algo_tpsl" not in ops, ops)
check("НЕТ отдельного вызова set_algo_tpsl", not any(x[0]=="set_algo_tpsl" for x in c.calls))

# шорт
c=FakeClient(); ex=WaltExecutor(c)
r=ex.open_with_protection(PLAN_SHORT)
check("шорт открывается", r["ok"], r)
op=[x for x in c.calls if x[0]=="open_position"][0]
check("шорт: стоп выше входа", op[5]==103.0, op)
check("шорт: тейк ниже входа", op[6]==94.0, op)

# ---------- валидация плана ----------
c=FakeClient(); ex=WaltExecutor(c)
bad=dict(PLAN_LONG); bad["stop_price"]=101.0   # стоп выше входа у лонга
r=ex.open_with_protection(bad)
check("лонг со стопом выше входа отклонён", not r["ok"], r)
check("ордер не отправлен", len(c.calls)==0, c.calls)

bad=dict(PLAN_LONG); bad["take_price"]=99.0
r=ex.open_with_protection(bad)
check("лонг с тейком ниже входа отклонён", not r["ok"], r)

bad=dict(PLAN_SHORT); bad["stop_price"]=99.0
r=ex.open_with_protection(bad)
check("шорт со стопом ниже входа отклонён", not r["ok"], r)

bad=dict(PLAN_SHORT); bad["take_price"]=101.0
r=ex.open_with_protection(bad)
check("шорт с тейком выше входа отклонён", not r["ok"], r)

bad=dict(PLAN_LONG); del bad["stop_price"]
r=ex.open_with_protection(bad)
check("план без стопа отклонён", not r["ok"], r)

bad=dict(PLAN_LONG); bad["side"]="sideways"
r=ex.open_with_protection(bad)
check("неизвестная сторона отклонена", not r["ok"], r)

# ---------- MIN_NOTIONAL ----------
c=FakeClient(); ex=WaltExecutor(c)
small=dict(PLAN_LONG); small["notional_usd"]=20.0; small["units"]=0.2
r=ex.open_with_protection(small)
check("номинал < $50 отклонён ДО отправки", not r["ok"], r)
check("при отказе по номиналу ордер не ушёл", len(c.calls)==0, c.calls)
check("причина называет минимальный номинал",
      any("номинал" in str(s.get("error","")) for s in r["steps"]), r)

c=FakeClient(); ex=WaltExecutor(c, min_notional=10.0)
small=dict(PLAN_LONG); small["notional_usd"]=20.0; small["units"]=0.2
r=ex.open_with_protection(small)
check("с пониженным порогом номинал проходит", r["ok"], r)

# ---------- ошибки биржи не роняют движок ----------
c=FakeClient(fail_on="set_leverage"); ex=WaltExecutor(c)
r=ex.open_with_protection(PLAN_LONG)
check("ошибка плеча не бросает исключение", not r["ok"], r)
check("после ошибки плеча ордер не уходит",
      not any(x[0]=="open_position" for x in c.calls), c.calls)

c=FakeClient(fail_on="open"); ex=WaltExecutor(c)
r=ex.open_with_protection(PLAN_LONG)
check("ошибка ордера не бросает исключение", not r["ok"], r)
check("ошибка попала в steps",
      any("отклонён" in str(s.get("error","")) for s in r["steps"]), r)

# ---------- dry_run ----------
c=FakeClient(); ex=WaltExecutor(c, dry_run=True)
r=ex.open_with_protection(PLAN_LONG)
check("dry_run возвращает ok", r["ok"], r)
check("dry_run НЕ отправляет ордер", len(c.calls)==0, c.calls)
check("dry_run считает номинал", r.get("notional_usd")==250.0, r)

# ---------- закрытие ----------
c=FakeClient(); ex=WaltExecutor(c)
r=ex.close_position(units=2.5, side="long", symbol="LIT")
check("закрытие успешно", r["ok"], r)
check("символ переведён", c.calls[0][1]=="LITUSDT", c.calls)

c=FakeClient(fail_on="close"); ex=WaltExecutor(c)
r=ex.close_position(units=2.5, side="long", symbol="LIT")
check("ошибка закрытия не бросает исключение", not r["ok"], r)

r=WaltExecutor(FakeClient()).close_position(units=1, side="long")
check("закрытие без символа - понятная ошибка", not r["ok"] and "символ" in r["error"], r)

# ---------- плечо ----------
c=FakeClient(); ex=WaltExecutor(c)
r=ex.set_leverage(7, symbol="LIT")
check("плечо ставится", r["ok"] and c.calls[0][2]==7, (r,c.calls))

# ---------- защита отдельно ----------
c=FakeClient(); ex=WaltExecutor(c)
r=ex.set_protection("LIT", stop_loss=97.0, take_profit=106.0, side="long")
check("отдельная защита работает", r["ok"], r)
check("символ переведён", c.calls[0][1]=="LITUSDT", c.calls)

# ---------- совместимость с LighterExecutor ----------
import inspect
lw=inspect.signature(WaltExecutor.open_with_protection).parameters
check("open_with_protection(plan, api_key_index) - сигнатура совместима",
      "plan" in lw and "api_key_index" in lw, list(lw))
lc=inspect.signature(WaltExecutor.close_position).parameters
check("close_position принимает units и side", "units" in lc and "side" in lc, list(lc))

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
