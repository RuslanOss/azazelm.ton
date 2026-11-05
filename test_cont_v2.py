# -*- coding: utf-8 -*-
# Тесты continuation_engine v2.0 на синтетических данных.
# Запуск: python3 test_cont_v2.py

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import azazel_test_guard  # izolyaciya ot boevoy Airtable/Telegram
import continuation_engine_v2 as ce

FAILED = []
PASSED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
    else:
        FAILED.append((name, detail))
    print(("  PASS  " if cond else "  FAIL  ") + name + ("  " + detail if detail and not cond else ""))


def synth_up(n=120, start=100.0, step=0.5, vol=1000.0):
    """Рост с шумом."""
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + step + (0.3 if i % 7 == 0 else -0.1)
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        out.append({"o": o, "h": h, "l": l, "c": c, "v": vol * (1 + (i % 5) * 0.1)})
        p = c
    return out


def synth_down(n=120, start=100.0, step=-0.5, vol=1000.0):
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + step + (0.3 if i % 7 == 0 else -0.1)
        h = max(o, c) + 0.2
        l = min(o, c) - 0.2
        out.append({"o": o, "h": h, "l": l, "c": c, "v": vol * (1 + (i % 5) * 0.1)})
        p = c
    return out


def synth_flat(n=120, start=100.0, vol=1000.0):
    out = []
    p = start
    for i in range(n):
        o = p
        c = p + (0.05 if i % 2 == 0 else -0.05)
        out.append({"o": o, "h": max(o, c) + 0.1, "l": min(o, c) - 0.1,
                    "c": c, "v": vol})
        p = c
    return out


def synth_zigzag(n=120, start=100.0, amp=3.0, vol=1000.0):
    """Зигзаг - есть локальные максимумы и минимумы."""
    out = []
    p = start
    for i in range(n):
        o = p
        c = start + amp * math.sin(i / 4.0)
        out.append({"o": o, "h": max(o, c) + 0.2, "l": min(o, c) - 0.2,
                    "c": c, "v": vol})
        p = c
    return out


def synth_wash(n=120, start=100.0):
    """Последняя свеча - объём x10 при почти нулевом диапазоне."""
    out = synth_flat(n, start)
    c = out[-1]
    out[-1] = {"o": c["c"], "h": c["c"] + 0.01, "l": c["c"] - 0.01,
                "c": c["c"], "v": c["v"] * 10}
    return out


print("\n=== 1. ИНДИКАТОРЫ ===")
up = [ce.norm(c) for c in synth_up()]
flat = [ce.norm(c) for c in synth_flat()]

r = ce.rsi(ce.closes(up), 14)
check("RSI восходящего тренда > 60", r[-1] > 60, "got %.1f" % r[-1])
r2 = ce.rsi(ce.closes(flat), 14)
check("RSI боковика около 50", 40 < r2[-1] < 60, "got %.1f" % r2[-1])

a = ce.atr(up, 14)
check("ATR > 0", a[-1] > 0, "got %.4f" % a[-1])
ap = ce.atr_pct(up, 14)
check("ATR в процентах 0.1..20", 0.1 < ap < 20, "got %.2f%%" % ap)

m_l, m_s, m_h = ce.macd(ce.closes(up))
check("MACD линия выше сигнала на росте", m_l[-1] > m_s[-1])
d, line = ce.supertrend(up)
check("SuperTrend лонг на восходящем тренде", d == 1, "dir=%s" % d)
d2, _ = ce.supertrend([ce.norm(c) for c in synth_down()])
check("SuperTrend шорт на нисходящем", d2 == -1, "dir=%s" % d2)

cv = ce.cvd(up)
check("CVD растёт на восходящем", cv[-1] > cv[0])

zig = [ce.norm(c) for c in synth_zigzag()]
sl = ce.swing_lows(zig)
sh = ce.swing_highs(zig)
check("Swing lows найдены на зигзаге", len(sl) > 0, "n=%d" % len(sl))
check("Swing highs найдены на зигзаге", len(sh) > 0, "n=%d" % len(sh))
check("в чистом тренде свингов нет", len(ce.swing_lows(up)) == 0,
      "n=%d" % len(ce.swing_lows(up)))
check("индекс свинга в границах", all(0 <= i < len(zig) for i in sl), str(sl[:5]))

print("\n=== 2. СИГНАЛЫ И ВЕРОЯТНОСТИ ===")
sig = ce.continuation_signals(up, "long")
check("4 сигнала продолжения", len(sig) == 4, str(list(sig)))
pc = ce.calculate_continuation_probability(sig)
check("вероятность продолжения 0..1", 0.0 <= pc <= 1.0, "got %.2f" % pc)
check("взвешенная сумма = 1.0 если все активны",
      abs(ce.calculate_continuation_probability({k: True for k in sig}) - 1.0) < 1e-9)
check("пустые сигналы -> 0", ce.calculate_continuation_probability({}) == 0.0)

rsig = ce.reversal_signals(up, "long")
check("5 сигналов разворота", len(rsig) == 5, str(list(rsig)))
pr = ce.calculate_reversal_probability(rsig)
check("вероятность разворота 0..1", 0.0 <= pr <= 1.0, "got %.2f" % pr)
check("все активны -> 1.0",
      abs(ce.calculate_reversal_probability({k: True for k in rsig}) - 1.0) < 1e-9)

print("\n=== 3. ДЕТЕКТОР МАНИПУЛЯЦИЙ ===")
man = ce.detect_manipulation([ce.norm(c) for c in synth_wash()])
check("вош-трейдинг обнаружен", man["wash_trading"] is True, str(man))
check("anomaly_score > 0", man["anomaly_score"] > 0, "got %.2f" % man["anomaly_score"])
man2 = ce.detect_manipulation(up)
check("чистый рынок - anomaly 0", man2["anomaly_score"] == 0.0, str(man2))
book = {"bids": [[100.0, 50000.0]] + [[99.0, 100.0]] * 10,
        "asks": [[101.0, 100.0]] + [[102.0, 100.0]] * 10}
man3 = ce.detect_manipulation(up, book)
check("спуфинг обнаружен по стакану", man3["spoofing"] is True, str(man3))

print("\n=== 4. РИСК-МЕНЕДЖМЕНТ (правила v5) ===")
cfg, src = ce.load_config()
print("  конфиг из:", src)
check("конфиг загружен из файла", src.startswith("file:"), src)

sp, s_pct, s_reason = ce.stop_for("LIT", 100.0, up, cfg)
check("стоп альта >= 3%", s_pct >= 3.0, "got %.2f%%" % s_pct)
sp2, s_pct2, _ = ce.stop_for("BTC", 100.0, up, cfg)
check("стоп BTC >= 1.5%", s_pct2 >= 1.5, "got %.2f%%" % s_pct2)
check("стоп ниже входа для лонга", sp < 100.0)

lv, _ = ce.leverage_for("LIT", 0.001, cfg)
check("плечо альта = 5", lv == 5, "got %s" % lv)
lv2, _ = ce.leverage_for("BTC", 0.005, cfg)
check("BTC при фандинге 0.005% -> 10x", lv2 == 10, "got %s" % lv2)
lv3, _ = ce.leverage_for("BTC", 0.02, cfg)
check("BTC при фандинге 0.02% -> 5x", lv3 == 5, "got %s" % lv3)
lv4, _ = ce.leverage_for("BTC", 0.06, cfg)
check("BTC при фандинге 0.06% -> 3x", lv4 == 3, "got %s" % lv4)

tgt = ce.target_from_stop(100.0, 97.0, "long", 2.0)
check("цель лонга = вход + 2R", abs(tgt - 106.0) < 1e-6, "got %.2f" % tgt)
tgt2 = ce.target_from_stop(100.0, 103.0, "short", 2.0)
check("цель шорта = вход - 2R", abs(tgt2 - 94.0) < 1e-6, "got %.2f" % tgt2)

btc_ctx = {"price": 100.0, "resistance": 101.0, "support": 95.0}
ok, why = ce.btc_filter_check("LIT", "short", btc_ctx, cfg)
check("шорт альта заблокирован у сопротивления", ok is False, why)
ok2, _ = ce.btc_filter_check("LIT", "long", btc_ctx, cfg)
check("лонг альта не блокируется", ok2 is True)
ok3, _ = ce.btc_filter_check("BTC", "short", btc_ctx, cfg)
check("шорт BTC не блокируется", ok3 is True)
ok4, _ = ce.btc_filter_check("LIT", "short", {"price": 100.0, "resistance": 110.0}, cfg)
check("шорт разрешён далеко от сопротивления", ok4 is True)

ok5, why5 = ce.funding_block_check("LIT", "long", 0.06, cfg)
check("лонг заблокирован при высоком фандинге", ok5 is False, why5)
ok6, _ = ce.funding_block_check("LIT", "long", 0.01, cfg)
check("лонг разрешён при низком фандинге", ok6 is True)
ok7, _ = ce.funding_block_check("LIT", "short", 0.06, cfg)
check("шорт не блокируется фандингом", ok7 is True)

ok8, _ = ce.daily_limit_check(0, -20.0, cfg)
check("дневной лимит убытка срабатывает", ok8 is False)
ok9, _ = ce.daily_limit_check(0, -5.0, cfg)
check("в пределах лимита - ок", ok9 is True)
ok10, _ = ce.daily_limit_check(5, 0.0, cfg)
check("лимит сделок в день", ok10 is False)
ok11, _ = ce.stop_count_check(3, cfg)
check("3 стопа - стоп на день", ok11 is False)
ok12, _ = ce.correlation_cap_check("LIT", [{"symbol": "LIT"}, {"symbol": "LIT"}], cfg)
check("correlation cap срабатывает", ok12 is False)

print("\n=== 5. РЕШЕНИЯ ПО ПОЗИЦИЯМ ===")
pos_long = {"symbol": "LIT", "side": "long", "entry": 100.0, "tp": 110.0, "sl": 95.0}
d = ce.decide_position(pos_long, up, cfg)
check("решение содержит reason", bool(d.get("reason")), d.get("reason"))
check("action в допустимом наборе",
      d["action"] in ("hold", "extend", "trail", "partial_close", "close"), d["action"])

d_stop = ce.decide_position({"symbol": "LIT", "side": "long", "entry": 100.0,
                              "tp": 110.0, "sl": 200.0}, up, cfg)
check("сработавший стоп -> close", d_stop["action"] == "close", d_stop["reason"])

d_short = ce.decide_position({"symbol": "LIT", "side": "short", "entry": 100.0,
                               "tp": 90.0, "sl": 50.0}, up, cfg)
check("шорт с пробитым стопом -> close", d_short["action"] == "close", d_short["reason"])

flat_n = [ce.norm(c) for c in synth_flat()]
d_tp = ce.decide_position({"symbol": "LIT", "side": "long", "entry": 100.0,
                            "tp": flat_n[-1]["c"] - 0.01, "sl": 50.0}, flat_n, cfg)
check("тейк без продолжения -> close", d_tp["action"] == "close", d_tp["reason"])

# на сильном тренде тейк -> extend, а не close (правило "продлить при >40%")
d_ext = ce.decide_position({"symbol": "LIT", "side": "long", "entry": 100.0,
                            "tp": up[-1]["c"] - 0.01, "sl": 50.0}, up, cfg)
check("тейк при продолжении >40% -> extend", d_ext["action"] == "extend", d_ext["reason"])
check("extend не равен close", d_ext["action"] != "close")

print("\n=== 6. ТОЧКИ ВХОДА ===")
cands = [{"symbol": "LIT", "side": "long", "candles": up,
          "price": up[-1]["c"], "funding_pct": 0.001, "btc_ctx": btc_ctx}]
res = ce.find_entries(cands, cfg, {"positions": [], "trades_today": 0,
                                    "pnl_today": 0, "stops_today": 0})
check("найден хотя бы один intent", len(res) == 1, str(len(res)))
e = res[0]
if e["action"] == "enter":
    check("R:R >= 2", e["rr"] >= 2, str(e["rr"]))
    check("стоп ниже цены входа", e["stop_loss"] < e["price"])
    check("тейк выше цены входа", e["take_profit"] > e["price"])
    check("плечо не больше 5 для альта", e["leverage"] <= 5, str(e["leverage"]))
else:
    check("интент не заблокирован фильтром", False, e.get("reason", ""))

cands_short = [{"symbol": "LIT", "side": "short", "candles": up,
                "price": up[-1]["c"], "funding_pct": 0.001, "btc_ctx": btc_ctx}]
res2 = ce.find_entries(cands_short, cfg, {"positions": [], "trades_today": 0,
                                          "pnl_today": 0, "stops_today": 0})
check("шорт альта заблокирован BTC-фильтром",
      res2 and res2[0]["action"] == "skip" and "фильтр" in res2[0]["reason"].lower(),
      res2[0].get("reason") if res2 else "нет результата")

res3 = ce.find_entries(cands, cfg, {"positions": [], "trades_today": 5,
                                    "pnl_today": 0, "stops_today": 0})
check("лимит сделок блокирует вход", res3[0]["action"] == "skip", res3[0].get("reason", ""))

res4 = ce.find_entries(cands, cfg, {"positions": [{"symbol": "LIT"}, {"symbol": "LIT"}],
                                    "trades_today": 0, "pnl_today": 0, "stops_today": 0})
check("correlation cap блокирует вход", res4[0]["action"] == "skip", res4[0].get("reason", ""))

print("\n=== 7. ЦИКЛ ДВИЖКА ===")
cyc = ce.engine_cycle(candidates={"LIT": up}, positions=[pos_long], cfg=cfg,
                       state={"positions": [], "trades_today": 0,
                              "pnl_today": 0, "stops_today": 0})
check("цикл вернул решение по позиции", len(cyc["positions"]) == 1)
check("цикл вернул записи о входах", "entries" in cyc)
check("в статистике есть счётчик", "stats" in cyc and "entries_ready" in cyc["stats"])

print("\n" + "=" * 50)
print("PASS: %d   FAIL: %d" % (len(PASSED), len(FAILED)))
if FAILED:
    print("\nПРОВАЛЕНО:")
    for n, dtl in FAILED:
        print("  -", n, "|", dtl)
    sys.exit(1)
print("ВСЕ ТЕСТЫ ПРОШЛИ")
