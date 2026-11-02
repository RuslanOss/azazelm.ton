# -*- coding: utf-8 -*-
# Тесты исполняемой части continuation_engine v3.0
# (спецификация + scan_top5_for_entry / open_position / partial_close /
#  freeze_trading / trailing_stop_after_extension)

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import continuation_engine as ce

FAILED, PASSED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name if cond else (name, detail))
    print(("  PASS  " if cond else "  FAIL  ") + name +
          ("  " + detail if detail and not cond else ""))


def synth_up(n=120, start=100.0, step=0.5, vol=1000.0):
    out, p = [], start
    for i in range(n):
        o = p
        c = p + step + (0.3 if i % 7 == 0 else -0.1)
        out.append({"o": o, "h": max(o, c) + 0.2, "l": min(o, c) - 0.2,
                    "c": c, "v": vol * (1 + (i % 5) * 0.1)})
        p = c
    return out


up = [ce.norm(c) for c in synth_up()]
cfg, src = ce.load_config()

print("\n=== 1. СПЕЦИФИКАЦИЯ СОХРАНЕНА ===")
check("CONTINUATION_SIGNALS: 4 сигнала", len(ce.CONTINUATION_SIGNALS) == 4,
      str(len(ce.CONTINUATION_SIGNALS)))
check("REVERSAL_SIGNALS: 5 сигналов", len(ce.REVERSAL_SIGNALS) == 5,
      str(len(ce.REVERSAL_SIGNALS)))
check("MANIPULATION_DETECTOR на месте", "spoofing" in ce.MANIPULATION_DETECTOR)
check("CONTINUATION_RULES на месте", "threshold" in ce.CONTINUATION_RULES)
check("ASSET_ROTATION на месте", "max_positions" in ce.ASSET_ROTATION)
check("веса продолжения совпадают с исполняемыми",
      all(ce.CONTINUATION_SIGNALS[k]["weight"] == v
          for k, v in ce.CONTINUATION_WEIGHTS.items()),
      str({k: (ce.CONTINUATION_SIGNALS[k]["weight"], ce.CONTINUATION_WEIGHTS[k])
           for k in ce.CONTINUATION_WEIGHTS}))
check("веса разворота совпадают с исполняемыми",
      all(ce.REVERSAL_SIGNALS[k]["weight"] == v
          for k, v in ce.REVERSAL_WEIGHTS.items()))
check("вероятность по спецификации = исполняемой",
      abs(ce.calculate_continuation_probability(
          {k: True for k in ce.CONTINUATION_SIGNALS}) - 1.0) < 1e-9)
check("TRADING_LOOP указывает на исполняемый код",
      "engine_cycle" in ce.TRADING_LOOP and hasattr(ce, "engine_cycle"))
check("версия 3.0", ce.__version__ == "3.0", ce.__version__)

print("\n=== 2. ЗАМОРОЗКА (freeze_trading) ===")
ce.freeze_trading("LIT", 300, "anomaly_score 0.75", now_ts=1000.0)
frozen, why = ce.is_frozen("LIT", 1100.0)
check("символ заморожен", frozen is True, why)
check("причина заморозки сохранена", "anomaly" in why, why)
check("после истечения разморожен", ce.is_frozen("LIT", 1400.0)[0] is False)
check("другой символ не заморожен", ce.is_frozen("BTC", 1100.0)[0] is False)

print("\n=== 3. open_position ===")
op = ce.open_position("LIT", "long", 100.0, up, cfg, funding_pct=0.001, margin_usd=50)
check("op возвращает спецификацию", "stop_loss" in op and "take_profit" in op)
check("стоп ниже входа", op["stop_loss"] < op["price"],
      "%.4f vs %.4f" % (op["stop_loss"], op["price"]))
check("тейп выше входа", op["take_profit"] > op["price"])
check("плечо альта = 5", op["leverage"] == 5, str(op["leverage"]))
check("R:R = 1:2", op["rr"] == 2.0, str(op["rr"]))
check("задана маржа", op["margin_usd"] == 50)
check("есть reason", bool(op.get("reason")))
op_s = ce.open_position("LIT", "short", 100.0, up, cfg, funding_pct=0.001)
check("шорт: стоп выше входа", op_s["stop_loss"] > op_s["price"],
      "%.4f vs %.4f" % (op_s["stop_loss"], op_s["price"]))
check("шорт: тейп ниже входа", op_s["take_profit"] < op_s["price"])
check("шорт: симметрия стопов лонг/шорт",
      abs((100.0 - op["stop_loss"]) - (op_s["stop_loss"] - 100.0)) < 1e-6,
      "%.6f vs %.6f" % (100.0 - op["stop_loss"], op_s["stop_loss"] - 100.0))
op_btc = ce.open_position("BTC", "long", 100.0, up, cfg, funding_pct=0.005)
check("BTC при низком фандинге -> 10x", op_btc["leverage"] == 10, str(op_btc["leverage"]))

print("\n=== 4. partial_close ===")
pos = {"symbol": "LIT", "size": 200.0}
pc1 = ce.partial_close(pos, 100.0, extension_number=1)
check("на расширении 1 частичного закрытия нет", pc1["action"] == "none",
      pc1.get("reason", ""))
pc3 = ce.partial_close(pos, 100.0, extension_number=3)
check("на расширении 3 - частичное закрытие 50%", pc3["action"] == "partial_close",
      pc3.get("reason", ""))
check("доля = 0.5", abs(pc3.get("fraction", 0) - 0.5) < 1e-9)
check("объём посчитан", abs(pc3.get("amount_usd", 0) - 100.0) < 1e-6,
      str(pc3.get("amount_usd")))

print("\n=== 5. trailing_stop_after_extension ===")
t1 = ce.trailing_stop_after_extension("LIT", "long", 100.0, 110.0, 1)
check("расширение 1 -> стоп на 0.5% за ценой",
      abs(t1["new_stop"] - 110.0 * 0.995) < 1e-6, str(t1.get("new_stop")))
t3 = ce.trailing_stop_after_extension("LIT", "long", 100.0, 110.0, 3)
check("расширение 3 -> стоп на 0.3% за ценой",
      abs(t3["new_stop"] - 110.0 * 0.997) < 1e-6, str(t3.get("new_stop")))
ts = ce.trailing_stop_after_extension("LIT", "short", 100.0, 90.0, 2)
check("шорт: стоп выше цены", ts["new_stop"] > 90.0)
check("нет правила для расширения 9",
      ce.trailing_stop_after_extension("LIT", "long", 100.0, 110.0, 9)["action"] == "none")

print("\n=== 6. scan_top5_for_entry ===")
btc_ctx = {"price": 100.0, "resistance": 110.0, "support": 95.0}
cands = [{"symbol": "LIT", "side": "long", "candles": up, "price": up[-1]["c"],
          "funding_pct": 0.001, "btc_ctx": btc_ctx, "volume_24h": 50_000_000}]
top = ce.scan_top5_for_entry(cands, cfg, {"positions": [], "trades_today": 0,
                                          "pnl_today": 0, "stops_today": 0})
check("scan вернул список", isinstance(top, list), str(type(top)))
check("не больше 5 кандидатов", len(top) <= 5, str(len(top)))
if top:
    check("у кандидата есть ранг", "rank" in top[0])
    check("кандидат имеет стоп", "stop_loss" in top[0])
else:
    print("  (кандидатов нет - сигналов недостаточно, это корректно)")
many = []
for sym in ["LIT", "SOL", "ZRO", "XPL", "ENA", "AAA"]:
    many.append({"symbol": sym, "side": "long", "candles": up,
                 "price": up[-1]["c"], "funding_pct": 0.001,
                 "btc_ctx": btc_ctx, "volume_24h": 50_000_000})
top2 = ce.scan_top5_for_entry(many, cfg, {"positions": [], "trades_today": 0,
                                           "pnl_today": 0, "stops_today": 0})
check("из 6 кандидатов отобрано не больше 5", len(top2) <= 5, str(len(top2)))
check("фильтр по объёму 24ч работает",
      all((c.get("volume_24h") or 0) >= ce.ASSET_ROTATION["min_volume_24h"]
          or c.get("volume_24h") is None for c in top2))

print("\n=== 7. СОВМЕСТИМОСТЬ ОБЁРТКИ v2 ===")
import continuation_engine_v2 as v2
check("v2 импортируется", v2.__version__ == "2.0", v2.__version__)
check("v2 реэкспортирует engine_cycle", hasattr(v2, "engine_cycle"))
check("v2 реэкспортирует open_position", hasattr(v2, "open_position"))
check("v2 реэкспортирует scan_top5_for_entry", hasattr(v2, "scan_top5_for_entry"))
check("v2 имеет алиас scan_top5", hasattr(v2, "scan_top5"))
check("v2 имеет TRADING_LOOP", hasattr(v2, "TRADING_LOOP"))
v2r = v2.calculate_continuation_probability({k: True for k in v2.CONTINUATION_SIGNALS})
check("вероятность в v2 совпадает с канонической", abs(v2r - 1.0) < 1e-9, str(v2r))
check("v2 и канонический - один и тот же объект",
      v2.CONTINUATION_SIGNALS is ce.CONTINUATION_SIGNALS)

print("\n" + "=" * 50)
print("PASS: %d   FAIL: %d" % (len(PASSED), len(FAILED)))
if FAILED:
    print("\nПРОВАЛЕНО:")
    for item in FAILED:
        print("  -", item[0], "|", item[1] if len(item) > 1 else "")
    sys.exit(1)
print("ВСЕ ТЕСТЫ ПРОШЛИ")
