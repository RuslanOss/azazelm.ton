# -*- coding: utf-8 -*-
"""Тесты моста CE -> слой v5.

Ключевой сценарий - каскад 23.10 (убыток $51.22): ZEC + NEAR + SNDK считались
"разными" позициями, потолок корреляции не срабатывал. Здесь тот же сценарий
обязан быть заблокирован.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_v5_bridge as B

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

CFG = {"stops":{"alts_pct":3.0,"btc_eth_pct":1.5,"atr_mult":1.0},
       "leverage":{"alts_max":5,"btc_eth_max":10},
       "rr_min":2.0,"btc_filter_pct":2.0,"funding_long_block_pct":0.05,
       "daily_loss_limit_usd":15.0,"max_stops_per_day":3,"correlation_cap":2,
       "max_trades_per_day":5}

# --- профиль: cfg -> profile слоя v5 ---
P = B.build_profile(CFG)
check("профиль: stop_alts", P["stop_alts"]==3.0, P)
check("профиль: stop_btc", P["stop_btc"]==1.5, P)
check("профиль: lev_alts", P["lev_alts"]==5, P)
check("профиль: lev_btc", P["lev_btc"]==10, P)
check("профиль: btc_filter", P["btc_filter"]==2.0, P)
check("профиль: corr_cap", P["corr_cap"]==2, P)
check("профиль: loss_limit", P["loss_limit"]==15.0, P)
check("профиль: max_trades", P["max_trades"]==5, P)
P2 = B.build_profile(CFG, {"stop_alts":5.0,"corr_cap":3})
check("extra переопределяет профиль", P2["stop_alts"]==5.0 and P2["corr_cap"]==3, P2)
P3 = B.build_profile(CFG, {"stop_alts":None})
check("extra None не ломает профиль", P3["stop_alts"]==3.0, P3)

# --- КАСКАД 23.10: три разных альта = одна BTC-группа ---
pos3 = [{"symbol":"ZEC","side":"short"},{"symbol":"NEAR","side":"short"},
        {"symbol":"SNDK","side":"short"}]
ok, r = B.correlation_cap_check("LIT", pos3, CFG)
check("каскад 23.10: 4-я позиция заблокирована", not ok, r)
check("причина называет корреляцию", "корреляц" in r.lower() or "потолок" in r.lower(), r)

ok, r = B.correlation_cap_check("SNDK", [{"symbol":"ZEC"},{"symbol":"NEAR"}], CFG)
check("3-я позиция в группе заблокирована", not ok, r)
ok, r = B.correlation_cap_check("SNDK", [{"symbol":"ZEC"}], CFG)
check("2-я позиция в группе разрешена", ok, r)
ok, r = B.correlation_cap_check("LIT", [], CFG)
check("без позиций всё разрешено", ok, r)
ok, r = B.correlation_cap_check("LIT", [{"symbol":"BTC","side":"long"}], CFG)
check("BTC не занимает место в группе альтов", ok, r)
ok, r = B.correlation_cap_check("ZEC", [{"symbol":"BTC"},{"symbol":"ETH"}], CFG)
check("ETH считается в группе альтов -> 2-я разрешена", ok, r)
ok, r = B.correlation_cap_check("ZEC", [{"symbol":"BTC"},{"symbol":"ETH"},{"symbol":"SOL"}], CFG)
check("BTC+ETH+SOL = 2 в группе -> 3-я заблокирована", not ok, r)

# --- стопы ---
sp, pct, reason = B.stop_for("NEAR", 4.09, 0.5, CFG)
check("стоп альта >= 3%", pct >= 3.0, (pct, reason))
check("стоп ниже цены (семантика лонга)", sp < 4.09, sp)
sp, pct, reason = B.stop_for("NEAR", 4.09, 8.0, CFG)
check("стоп расширяется по ATR", pct >= 8.0, (pct, reason))
sp, pct, reason = B.stop_for("BTC", 77786, 8.0, CFG)
check("стоп BTC не расширяется по ATR", abs(pct-1.5)<1e-9, (pct, reason))
sp, pct, reason = B.stop_for("ETH", 2288, 5.0, CFG)
check("стоп ETH = 1.5%", abs(pct-1.5)<1e-9, (pct, reason))

# --- плечо ---
lev, r = B.leverage_for("BTC", 0.09, CFG); check("фандинг 0.09 -> 3x", lev==3, (lev,r))
lev, r = B.leverage_for("BTC", 0.03, CFG); check("фандинг 0.03 -> 5x", lev==5, (lev,r))
lev, r = B.leverage_for("BTC", 0.005, CFG); check("фандинг 0.005 -> 10x", lev==10, (lev,r))
lev, r = B.leverage_for("SNDK", 0.0, CFG); check("альт максимум 5x", lev==5, (lev,r))
lev, r = B.leverage_for("SNDK", 0.09, CFG); check("альт и при высоком фандинге 5x", lev==5, (lev,r))

# --- BTC-фильтр (расстояние ОТ СОПРОТИВЛЕНИЯ) ---
ok, r = B.btc_filter_check("SNDK","short",{"price":77900,"resistance":78880}, CFG)
check("шорт альта у сопротивления заблокирован", not ok, r)
check("причина содержит маркер 'фильтр'", "фильтр" in r.lower(), r)
ok, r = B.btc_filter_check("SNDK","short",{"price":70000,"resistance":78880}, CFG)
check("шорт альта далеко разрешён", ok, r)
ok, r = B.btc_filter_check("BTC","short",{"price":77900,"resistance":78880}, CFG)
check("шорт BTC не блокируется", ok, r)
ok, r = B.btc_filter_check("SNDK","long",{"price":77900,"resistance":78880}, CFG)
check("лонг не блокируется", ok, r)
ok, r = B.btc_filter_check("SNDK","short",{}, CFG)
check("нет данных BTC - разрешено", ok, r)

# --- фандинг ---
ok, r = B.funding_block_check("BTC","long",0.09, CFG)
check("лонг при высоком фандинге заблокирован", not ok, r)
ok, r = B.funding_block_check("BTC","short",0.09, CFG)
check("шорт не блокируется фандингом", ok, r)

# --- дневные лимиты ---
ok, r = B.daily_limit_check(0, -15.0, CFG); check("лимит -$15", not ok, r)
ok, r = B.daily_limit_check(5, 0.0, CFG); check("5 сделок", not ok, r)
ok, r = B.daily_limit_check(0, 0.0, CFG); check("норма", ok, r)
ok, r = B.stop_count_check(3, CFG); check("3 стопа", not ok, r)
ok, r = B.stop_count_check(2, CFG); check("2 стопа - ок", ok, r)

# --- sizing ---
s = B.size_position(1000, 100, 5.0, 10, CFG)
check("риск 33% маржи", abs(s["risk_usd"]-330.0)<0.01, s)
s = B.size_position(100, 100, 3.0, 5, CFG)
check("маржа ограничивает", s["notional"] <= 500.0+1e-9, s)
check("units считаются", abs(s["units"]-s["notional"]/100.0)<1e-9, s)

# --- цель по R:R ---
tp = B.take_pct_for("SNDK", 3.0, CFG)
check("цель = stop * rr", abs(tp-6.0)<1e-9, tp)

# --- полный план ---
ok, r, pl = B.plan("SNDK","short",1380, atr_pct_value=5.0, funding_pct=0.005,
                    margin_usd=500, btc_ctx={"price":77900,"resistance":78880},
                    positions=[], state={"pnl_day_usd":0,"stops_today":0,"trades_today":0},
                    cfg=CFG)
check("план: шорт заблокирован BTC-фильтром", not ok, r)
check("план пустой при отказе", pl == {}, pl)

ok, r, pl = B.plan("BTC","long",77786, atr_pct_value=1.0, funding_pct=0.005,
                    margin_usd=500, btc_ctx={"price":77900,"resistance":78880},
                    positions=[], state={"pnl_day_usd":0,"stops_today":0,"trades_today":0},
                    cfg=CFG)
check("план: лонг BTC разрешён", ok, r)
if ok:
    check("план: стоп", pl.get("stop_price",0) > 0, pl)
    check("план: тейк", pl.get("take_price",0) > 0, pl)
    check("план: R:R >= 2", pl.get("rr",0) >= 2, pl)
    check("план: маржа", pl.get("margin_usd",0) > 0, pl)
    check("план: units", pl.get("units",0) > 0, pl)

# план на шорт при высоком фандинге блокируется (правило слоя v5)
ok, r, pl = B.plan("ETH","short",2288, atr_pct_value=1.0, funding_pct=0.09,
                    margin_usd=500, btc_ctx={"price":77900,"resistance":78880},
                    positions=[], state={"pnl_day_usd":0,"stops_today":0,"trades_today":0},
                    cfg=CFG)
check("план: шорт при высоком фандинге разрешён (фандинг блокирует только лонг)", ok, r)

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
