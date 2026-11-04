# -*- coding: utf-8 -*-
"""Тесты торгового слоя v5.

Каждый тест привязан к реальному уроку из пост-анализов:
  - WHIPSAW 23.10: новости >24ч невалидны; разворот требует закрепления
  - CASCADE 23.10: корреляция, стопы 1.87% при 15-16x, вход без подтверждения BTC
  - NEAR 20.10: стоп 2.67% - слишком близко к ликвидности
  - SNDK 20.10: не шортить альты при BTC-ралли, не входить на отскоке
  - TSLA 02.11: вход без стопа не окупается
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_trading_v5 as T

FAILS = []
PASSES = []

def check(name, cond, detail=""):
    if cond:
        PASSES.append(name)
    else:
        FAILS.append("%s :: %s" % (name, detail))

P = dict(T.DEFAULT_PROFILE)

# --- R1: stop floor (урок NEAR 20.10, CASCADE 23.10) ---
d = T.resolve_stop_pct("NEAR", atr_pct=0.5, profile=P)
check("stop alts >= 3% (ATR 0.5%)", d >= 3.0, "got %s" % d)
d = T.resolve_stop_pct("NEAR", atr_pct=8.0, profile=P)
check("stop alts расширяется по ATR (8%)", d >= 8.0, "got %s" % d)
d = T.resolve_stop_pct("BTC", atr_pct=8.0, profile=P)
check("stop BTC не расширяется по ATR", d == 1.5, "got %s" % d)

# --- R1: leverage by funding ---
check("fanding 0.09% -> 3x BTC", T.resolve_leverage("BTC", 0.09, P) == 3,
      T.resolve_leverage("BTC", 0.09, P))
check("fanding 0.03% -> 5x BTC", T.resolve_leverage("BTC", 0.03, P) == 5,
      T.resolve_leverage("BTC", 0.03, P))
check("fanding 0.005% -> 10x BTC", T.resolve_leverage("BTC", 0.005, P) == 10,
      T.resolve_leverage("BTC", 0.005, P))
check("альт максимум 5x при низком фандинге",
      T.resolve_leverage("SNDK", 0.0, P) == 5, T.resolve_leverage("SNDK", 0.0, P))

# --- R2: R:R ---
check("R:R 1:2 по умолчанию", T.resolve_take_pct("BTC", 1.5, P) == 3.0)
d = T.check_rr(3.0, 4.0, P)
check("R:R 1:1.33 отклонён", not d.allow, d.reason)
d = T.check_rr(3.0, 6.0, P)
check("R:R 1:2 принят", d.allow, d.reason)

# --- R3: BTC-фильтр (урок SNDK 20.10 - не шортить альты при BTC-ралли) ---
d = T.check_btc_filter("short", "SNDK", btc_price=77900, btc_resistance=78880, profile=P)
check("шорт альта заблокирован при BTC в 1.24% от сопротивления", not d.allow, d.reason)
d = T.check_btc_filter("short", "SNDK", btc_price=70000, btc_resistance=78880, profile=P)
check("шорт альта разрешён при BTC далеко", d.allow, d.reason)
d = T.check_btc_filter("long", "SNDK", btc_price=77900, btc_resistance=78880, profile=P)
check("лонг не блокируется BTC-фильтром", d.allow, d.reason)
d = T.check_btc_filter("short", "BTC", btc_price=77900, btc_resistance=78880, profile=P)
check("шорт BTC не блокируется BTC-фильтром", d.allow, d.reason)

# --- R4: фандинг блокирует лонг ---
d = T.check_funding("long", 0.09, P)
check("лонг заблокирован при высоком фандинге", not d.allow, d.reason)
d = T.check_funding("long", 0.02, P)
check("лонг разрешён при умеренном фандинге", d.allow, d.reason)
d = T.check_funding("short", 0.09, P)
check("шорт не блокируется фандингом", d.allow, d.reason)

# --- R4: корреляционный потолок (урок каскада 23.10) ---
d = T.check_correlation("short", "ZEC", [{"symbol": "NEAR"}, {"symbol": "SNDK"}], P)
check("3-я коррелированная позиция заблокирована", not d.allow, d.reason)
d = T.check_correlation("short", "ZEC", [{"symbol": "NEAR"}], P)
check("2-я позиция разрешена", d.allow, d.reason)

# --- R6: новостной фильтр (урок WHIPSAW 23.10 - новости >24ч невалидны) ---
d = T.check_news_filter({"score": 0.9, "age_hours": 5})
check("свежая сильная новость блокирует вход", not d.allow, d.reason)
d = T.check_news_filter({"score": 0.9, "age_hours": 40})
check("старая новость (>24ч) не блокирует", d.allow, d.reason)
d = T.check_news_filter({"score": 0.3, "age_hours": 2})
check("слабая новость не блокирует", d.allow, d.reason)

# --- R7/R8: дневные лимиты ---
d = T.check_daily_limits({"pnl_day_usd": -15.0}, P)
check("лимит убытка -$15 останавливает", not d.allow, d.reason)
d = T.check_daily_limits({"stops_today": 3}, P)
check("3 стопа останавливают", not d.allow, d.reason)
d = T.check_daily_limits({"trades_today": 5}, P)
check("5 сделок останавливают", not d.allow, d.reason)
d = T.check_daily_limits({"pnl_day_usd": -5.0, "stops_today": 1, "trades_today": 2}, P)
check("в нормальных лимитах - разрешено", d.allow, d.reason)

# --- sizing: риск 33% маржи, ограниченный маржой x плечо ---
# Маржа $100, стоп 3%, плечо 5: риск 33% = $33 требует номинала $1100,
# но маржа дает максимум маржа*плечо = $500 -> риск $15 (15% маржи).
s = T.size_by_risk(margin_usd=100, entry=100, stop_pct=3.0, risk_pct=33, leverage=5)
check("маржа не превышает доступную", s["margin"] <= 100.0 + 1e-9, s)
check("номинал <= маржа*плечо", s["notional"] <= 100.0 * 5 + 1e-9, s)
check("риск не превышает 33% маржи", s["risk_usd"] <= 33.0 + 1e-9, s)
check("риск соответствует стопу", abs(s["risk_usd"] - s["notional"] * 0.03) < 1e-6, s)

# Маржа $1000, стоп 3%, плечо 5: номинал ограничен $5000 -> риск $150, не $330.
s = T.size_by_risk(margin_usd=1000, entry=100, stop_pct=3.0, risk_pct=33, leverage=5)
check("номинал ограничен маржой x плечо", abs(s["notional"] - 5000.0) < 1e-6, s)
check("риск ограничен стопом, а не 33%", abs(s["risk_usd"] - 150.0) < 0.01, s)
check("маржа использована полностью", abs(s["margin"] - 1000.0) < 1e-6, s)

# Маржа $1000, стоп 5%, плечо 10: риск 33% ($330) достижим, маржа 660.
s = T.size_by_risk(margin_usd=1000, entry=100, stop_pct=5.0, risk_pct=33, leverage=10)
check("при широком стопе и высоком плече риск = 33%", abs(s["risk_usd"] - 330.0) < 0.01, s)
check("маржа использована частично", abs(s["margin"] - 660.0) < 1e-6, s)

# --- полный план: нормальный вход ---
d = T.plan_trade("BTC", "long", 78000, atr_pct=1.0, funding_pct=0.005,
                 margin_usd=500, btc_price=77900, btc_resistance=78880,
                 open_positions=[], state={"pnl_day_usd": 0, "stops_today": 0, "trades_today": 0},
                 profile=P)
check("нормальный вход разрешён", d.allow, d.reason)
if d.allow:
    pl = d.plan
    check("плечо 10x при низком фандинге", pl["leverage"] == 10, pl)
    check("стоп BTC 1.5%", abs(pl["stop_pct"] - 1.5) < 0.01, pl)
    check("тейк = 2x стоп (3%)", abs(pl["take_pct"] - 3.0) < 0.01, pl)
    check("стоп ниже входа для лонга", pl["stop_price"] < pl["entry"], pl)
    check("тейк выше входа для лонга", pl["take_price"] > pl["entry"], pl)

# --- полный план: заблокирован ---
d = T.plan_trade("SNDK", "short", 1380, atr_pct=5.0, funding_pct=0.005,
                 margin_usd=500, btc_price=77900, btc_resistance=78880,
                 open_positions=[], state={"pnl_day_usd": 0, "stops_today": 0, "trades_today": 0},
                 profile=P)
check("шорт альта у сопротивления BTC заблокирован", not d.allow, d.reason)
check("причина - именно BTC-фильтр", d.rule == "R4_btc_filter", d.rule)

d = T.plan_trade("BTC", "long", 78000, funding_pct=0.09, margin_usd=500,
                 btc_price=77900, btc_resistance=78880,
                 state={"pnl_day_usd": 0, "stops_today": 0, "trades_today": 0}, profile=P)
check("лонг при высоком фандинге заблокирован", not d.allow, d.reason)

d = T.plan_trade("BTC", "long", 78000, funding_pct=0.005, margin_usd=0,
                 state={}, profile=P)
check("вход без маржи заблокирован", not d.allow, d.reason)

# --- дневное состояние ---
st = T.update_daily_state({"pnl_day_usd": 0, "stops_today": 0, "trades_today": 0},
                           {"type": "stop_hit", "pnl_usd": -12.0}, P)
check("стоп засчитан", st["stops_today"] == 1, st)
check("PnL дня обновлён", abs(st["pnl_day_usd"] + 12.0) < 0.01, st)
# стоп на $12: PnL дня -12, лимит -$15 -> еще НЕ остановлено
check("один стоп не останавливает день", not st["trading_halted"], st)
# второй стоп на $5: PnL дня -17 -> лимит убытка перекрыт -> день остановлен
st = T.update_daily_state(st, {"type": "stop_hit", "pnl_usd": -5.0}, P)
check("лимит убытка -$15 останавливает день", st["trading_halted"], st)
check("PnL дня перекрыл лимит", st["pnl_day_usd"] <= -15.0, st)
st2 = T.update_daily_state({"pnl_day_usd": 0, "stops_today": 0, "trades_today": 0},
                            {"type": "stop_hit", "pnl_usd": -3.0}, P)
st2 = T.update_daily_state(st2, {"type": "stop_hit", "pnl_usd": -3.0}, P)
check("2 стопа при малом убытке - день ещё идёт", not st2["trading_halted"], st2)
st2 = T.update_daily_state(st2, {"type": "stop_hit", "pnl_usd": -3.0}, P)
check("3-й стоп останавливает день", st2["stops_today"] == 3 and st2["trading_halted"], st2)
st = T.update_daily_state(st, {"type": "stop_hit", "pnl_usd": -5.0}, P)
check("достигнут лимит стопов - день остановлен", st["trading_halted"], st)

# --- риск-менеджмент: стоп всегда есть в плане (урок TSLA 02.11) ---
d = T.plan_trade("BTC", "long", 78000, funding_pct=0.005, margin_usd=500,
                 btc_price=77900, btc_resistance=78880, state={}, profile=P)
check("план всегда содержит стоп", d.allow and d.plan.get("stop_price", 0) > 0, d.plan)

print("PASS: %d" % len(PASSES))
for f in FAILS:
    print("FAIL: " + f)
print("FAIL: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
