# -*- coding: utf-8 -*-
# ============================================================
# CONTINUATION ENGINE v3.0 - исполняемый
# Azazel Trader | 2026-11-02
# ============================================================
"""
CONTINUATION ENGINE v3.0 - каноническая реализация.

Раньше этот файл был СПЕЦИФИКАЦИЕЙ: TRADING_LOOP лежал в docstring как
псевдокод, а функции scan_top5_for_entry / open_position / partial_close /
detect_manipulation вызывались, но нигде не были определены. Исполнять
было нечего.

Теперь это рабочий движок. Правда v5 соблюдаются на входе.

КОНТРАКТ:
  - Движок НЕ ходит на биржу. Принимает данные (свечи, позиции, макро)
    и возвращает список НАМЕРЕНИЙ. Исполнение - через Walt.
  - Только стандартная библиотека.
  - Каждое решение содержит reason - что именно заставило движок так решить.

ФОРМАТ СВЕЧИ: dict с o/h/l/c/v (регистр не важен), опционально ts.
ФОРМАТ ПОЗИЦИИ: dict(symbol, side, entry, size, leverage, tp, sl).
"""

import json
import os

__version__ = "3.0"

DEFAULT_CFG = {
    "stops": {"alts_pct": 3.0, "btc_eth_pct": 1.5, "atr_mult": 1.0},
    "leverage": {"alts_max": 5, "btc_eth_max": 10},
    "rr_min": 2.0,
    "btc_filter_pct": 2.0,
    "funding_long_block_pct": 0.05,
    "daily_loss_limit_usd": 15.0,
    "max_stops_per_day": 3,
    "correlation_cap": 2,
    "max_trades_per_day": 5,
    "timeframes": ["15m", "1h", "4h"],
    "target_roi": "1:3",
}

BTC_ETH = ("BTC", "ETH")


def load_config(path=None):
    """Читает azazel_config.json; при отсутствии - дефолты."""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "azazel_config.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        algo = raw.get("algo", {})
        cfg = json.loads(json.dumps(DEFAULT_CFG))
        for k, v in algo.items():
            if k in cfg and isinstance(cfg[k], dict) and isinstance(v, dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        return cfg, "file:" + path
    except Exception as e:
        return json.loads(json.dumps(DEFAULT_CFG)), "defaults:" + str(e)


def _f(c, *keys):
    for k in keys:
        if k in c:
            try:
                return float(c[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def norm(c):
    """Свеча -> {o,h,l,c,v,ts}."""
    return {
        "o": _f(c, "o", "open", "O"),
        "h": _f(c, "h", "high", "H"),
        "l": _f(c, "l", "low", "L"),
        "c": _f(c, "c", "close", "C"),
        "v": _f(c, "v", "volume", "V"),
        "ts": c.get("ts", c.get("time", c.get("t"))),
    }


def closes(candles):
    return [x["c"] for x in candles]


def volumes(candles):
    return [x["v"] for x in candles]


def avg(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


# ---------- ИНДИКАТОРЫ ----------

def ema(values, period):
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values, period=14):
    """RSI по Wilder."""
    if len(values) <= period:
        return [50.0] * len(values)
    gains, losses = [0.0], [0.0]
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[1:period + 1]) / period
    al = sum(losses[1:period + 1]) / period
    out = [50.0] * period
    for i in range(period, len(values)):
        if i > period:
            ag = (ag * (period - 1) + gains[i]) / period
            al = (al * (period - 1) + losses[i]) / period
        out.append(100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al))
    return out


def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow:
        return [], [], []
    ef, es = ema(values, fast), ema(values, slow)
    line = [ef[i] - es[i] for i in range(len(values))]
    sig = ema(line, signal)
    hist = [line[i] - sig[i] for i in range(len(values))]
    return line, sig, hist


def atr(candles, period=14):
    """ATR по Wilder."""
    if not candles:
        return []
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c["h"] - c["l"])
        else:
            pc = candles[i - 1]["c"]
            trs.append(max(c["h"] - c["l"], abs(c["h"] - pc), abs(c["l"] - pc)))
    if len(trs) <= period:
        return [sum(trs) / len(trs)] * len(trs)
    out = [sum(trs[:period]) / period]
    for i in range(period, len(trs)):
        out.append((out[-1] * (period - 1) + trs[i]) / period)
    # добиваем до len(candles): Wilder-ATR начинается с полного окна
    while len(out) < len(candles):
        out.append(out[-1])
    return out


def atr_pct(candles, period=14):
    """ATR в процентах от цены."""
    a = atr(candles, period)
    if not a:
        return 0.0
    last = candles[-1]["c"] or 1.0
    return 100.0 * a[-1] / last


def supertrend(candles, period=10, mult=3.0):
    """Возвращает (direction, line). direction: 1 лонг, -1 шорт, 0 нет данных."""
    if len(candles) < period + 1:
        return 0, 0.0
    a = atr(candles, period)
    hl2 = [(c["h"] + c["l"]) / 2.0 for c in candles]
    upper = [hl2[i] + mult * a[i] for i in range(len(candles))]
    lower = [hl2[i] - mult * a[i] for i in range(len(candles))]
    direction, fu, fl = 1, upper[period], lower[period]
    for i in range(period + 1, len(candles)):
        pc = candles[i - 1]["c"]
        if candles[i]["c"] > fu:
            direction = 1
        elif candles[i]["c"] < fl:
            direction = -1
        if direction == 1:
            fu = upper[i] if upper[i] < fu and pc <= fu else fu
            fl = lower[i] if lower[i] > fl else fl
        else:
            fu = upper[i] if upper[i] < fu else fu
            fl = lower[i] if lower[i] > fl and pc >= fl else fl
    return direction, (fl if direction == 1 else fu)


def cvd(candles):
    """Кумулятивный дельта объёма (прокси: (c-o)*v)."""
    out, acc = [], 0.0
    for c in candles:
        acc += (c["c"] - c["o"]) * c["v"]
        out.append(acc)
    return out


def swing_lows(candles, left=2, right=2):
    res = []
    for i in range(left, len(candles) - right):
        w = candles[i - left:i + right + 1]
        if candles[i]["l"] == min(x["l"] for x in w):
            res.append(i)
    return res


def swing_highs(candles, left=2, right=2):
    res = []
    for i in range(left, len(candles) - right):
        w = candles[i - left:i + right + 1]
        if candles[i]["h"] == max(x["h"] for x in w):
            res.append(i)
    return res


# ---------- СИГНАЛЫ ПРОДОЛЖЕНИЯ ----------

def _hidden_divergence(candles, rsi_vals, side):
    """Скрытая дивергенция: цена HL, RSI LL (бычья) и наоборот."""
    lows = swing_lows(candles)
    highs = swing_highs(candles)
    if side == "long":
        if len(lows) < 2:
            return False
        i2, i1 = lows[-1], lows[-2]
        return candles[i2]["l"] > candles[i1]["l"] and rsi_vals[i2] < rsi_vals[i1]
    if len(highs) < 2:
        return False
    i2, i1 = highs[-1], highs[-2]
    return candles[i2]["h"] < candles[i1]["h"] and rsi_vals[i2] > rsi_vals[i1]


def _momentum_confirmation(candles, side):
    line, sig, hist = macd(closes(candles))
    if len(hist) < 2:
        return False
    if side == "long":
        return line[-1] > sig[-1] and hist[-1] > hist[-2]
    return line[-1] < sig[-1] and hist[-1] < hist[-2]


def _volume_trend(candles, side):
    win = candles[-20:]
    if len(win) < 10:
        return False
    up = [c["v"] for c in win if c["c"] >= c["o"]]
    dn = [c["v"] for c in win if c["c"] < c["o"]]
    if not up or not dn:
        return False
    if side == "long":
        return avg(up) > avg(dn) * 1.3
    return avg(dn) > avg(up) * 1.3


def _ema_structure(candles, side):
    cl = closes(candles)
    if len(cl) < 50:
        return False
    e5, e13, e50 = ema(cl, 5), ema(cl, 13), ema(cl, 50)
    if side == "long":
        ok = e5[-1] > e13[-1] > e50[-1]
        cross = any(e5[i] < e13[i] and e5[i + 1] >= e13[i + 1]
                    for i in range(len(e5) - 20, len(e5) - 1))
        return ok and not cross
    ok = e5[-1] < e13[-1] < e50[-1]
    cross = any(e5[i] > e13[i] and e5[i + 1] <= e13[i + 1]
                for i in range(len(e5) - 20, len(e5) - 1))
    return ok and not cross


def continuation_signals(candles, side):
    """4 сигнала продолжения тренда (веса - в CONTINUATION_WEIGHTS)."""
    cl = closes(candles)
    if len(cl) < 20:
        return {}
    r = rsi(cl, 14)
    return {
        "hidden_divergence": _hidden_divergence(candles, r, side),
        "momentum_confirmation": _momentum_confirmation(candles, side),
        "volume_trend": _volume_trend(candles, side),
        "ema_structure": _ema_structure(candles, side),
    }


# ---------- СИГНАЛЫ РАЗВОРОТА ----------

def _regular_divergence(candles, rsi_vals, side):
    highs = swing_highs(candles)
    lows = swing_lows(candles)
    if side == "long":
        if len(highs) < 2:
            return False
        i2, i1 = highs[-1], highs[-2]
        return candles[i2]["h"] > candles[i1]["h"] and rsi_vals[i2] < rsi_vals[i1]
    if len(lows) < 2:
        return False
    i2, i1 = lows[-1], lows[-2]
    return candles[i2]["l"] < candles[i1]["l"] and rsi_vals[i2] > rsi_vals[i1]


def _volume_climax(candles, side):
    if len(candles) < 21:
        return False
    base = avg(volumes(candles[-21:-1]))
    if base <= 0:
        return False
    c = candles[-1]
    if c["v"] < base * 3:
        return False
    return (c["c"] < c["o"]) if side == "long" else (c["c"] > c["o"])


def _ema_cross(candles, side):
    cl = closes(candles)
    if len(cl) < 20:
        return False
    e5, e13 = ema(cl, 5), ema(cl, 13)
    crossed_down = any(e5[i] > e13[i] and e5[i + 1] <= e13[i + 1]
                        for i in range(len(e5) - 3, len(e5) - 1))
    crossed_up = any(e5[i] < e13[i] and e5[i + 1] >= e13[i + 1]
                      for i in range(len(e5) - 3, len(e5) - 1))
    return crossed_down if side == "long" else crossed_up


def _round_level(price):
    if not price:
        return 0.0
    mag = 10 ** (len(str(int(abs(price)))) - 1)
    return round(price / mag) * mag


def _sr_rejection(candles, side):
    """Отказ от круглого уровня: коснулся и отскочил."""
    if len(candles) < 10:
        return False
    c = candles[-1]
    level = _round_level(c["c"])
    if not level:
        return False
    if side == "long":
        return c["l"] <= level * 1.001 and c["c"] > level
    return c["h"] >= level * 0.999 and c["c"] < level


def _funding_flip(funding_hist, side):
    """Фандинг сменил знак против позиции."""
    if not funding_hist or len(funding_hist) < 2:
        return False
    a, b = funding_hist[-2], funding_hist[-1]
    if a == 0 or b == 0:
        return False
    return (a > 0 > b) if side == "long" else (a < 0 < b)


def reversal_signals(candles, side, funding_hist=None):
    """5 стоп-сигналов (веса - в REVERSAL_WEIGHTS)."""
    cl = closes(candles)
    if len(cl) < 20:
        return {}
    r = rsi(cl, 14)
    return {
        "regular_divergence": _regular_divergence(candles, r, side),
        "volume_climax": _volume_climax(candles, side),
        "ema_cross": _ema_cross(candles, side),
        "support_resistance_rejection": _sr_rejection(candles, side),
        "funding_flip": _funding_flip(funding_hist or [], side),
    }


# ---------- ВЕРОЯТНОСТИ ----------

CONTINUATION_WEIGHTS = {
    "hidden_divergence": 0.35,
    "momentum_confirmation": 0.25,
    "volume_trend": 0.20,
    "ema_structure": 0.20,
}

REVERSAL_WEIGHTS = {
    "regular_divergence": 0.30,
    "volume_climax": 0.25,
    "ema_cross": 0.20,
    "support_resistance_rejection": 0.15,
    "funding_flip": 0.10,
}


def calculate_continuation_probability(signals_active):
    """Вероятность продолжения тренда 0..1 по активным сигналам."""
    if not signals_active:
        return 0.0
    total = sum(CONTINUATION_WEIGHTS.get(k, 0.0)
                for k in signals_active if signals_active[k])
    return round(min(1.0, total), 4)


def calculate_reversal_probability(signals_active):
    if not signals_active:
        return 0.0
    total = sum(REVERSAL_WEIGHTS.get(k, 0.0)
                for k in signals_active if signals_active[k])
    return round(min(1.0, total), 4)


# ---------- ДЕТЕКТОР МАНИПУЛЯЦИЙ ----------

def detect_manipulation(candles, book=None):
    """Спуфинг / вош-трейдинг / охота за стопами + композитный anomaly_score."""
    res = {"spoofing": False, "wash_trading": False,
           "stop_hunting": False, "anomaly_score": 0.0}
    if len(candles) < 20:
        return res

    c = candles[-1]
    base = avg(volumes(candles[-21:-1]))
    rng_pct = 100.0 * (c["h"] - c["l"]) / (c["c"] or 1.0)

    if base > 0 and c["v"] > base * 3 and rng_pct < 0.1:
        res["wash_trading"] = True

    if book:
        bid_q = sum(q for _, q in book.get("bids", [])[:10])
        ask_q = sum(q for _, q in book.get("asks", [])[:10])
        if bid_q > 0 and ask_q > 0 and (bid_q / ask_q) > 10:
            res["spoofing"] = True

    for kind, level_key, wick_dir in (("low", "l", "down"), ("high", "h", "up")):
        idxs = swing_lows(candles) if kind == "low" else swing_highs(candles)
        if not idxs:
            continue
        lvl = candles[idxs[-1]][level_key]
        for i in range(max(0, len(candles) - 3), len(candles)):
            if wick_dir == "down":
                wick_pct = 100.0 * (lvl - candles[i]["l"]) / (lvl or 1.0)
            else:
                wick_pct = 100.0 * (candles[i]["h"] - lvl) / (lvl or 1.0)
            if wick_pct <= 0.3:
                continue
            for j in range(i + 1, min(i + 4, len(candles))):
                if wick_dir == "down":
                    rev = 100.0 * (candles[j]["c"] - candles[i]["l"]) / (candles[i]["l"] or 1.0)
                else:
                    rev = 100.0 * (candles[i]["h"] - candles[j]["c"]) / (candles[i]["h"] or 1.0)
                if rev > 0.5:
                    res["stop_hunting"] = True
                    break
            if res["stop_hunting"]:
                break

    score = 0.0
    if res["spoofing"]:
        score += 0.25
    if res["wash_trading"]:
        score += 0.30
    if res["stop_hunting"]:
        score += 0.20
    res["anomaly_score"] = round(min(1.0, score), 4)
    return res


# ---------- РИСК-МЕНЕДЖМЕНТ ----------

def is_btc_eth(symbol):
    return str(symbol).upper() in BTC_ETH


def stop_for(symbol, price, candles, cfg):
    """Стоп: max(минимальный %, ATR x atr_mult). -> (stop_price, stop_pct, reason)."""
    st = cfg["stops"]
    floor = st["btc_eth_pct"] if is_btc_eth(symbol) else st["alts_pct"]
    ap = atr_pct(candles)
    atr_stop = ap * st["atr_mult"]
    use = max(floor, atr_stop)
    reason = ("ATR x %.1f (ATR %.2f%%)" % (st["atr_mult"], ap)
              if atr_stop > floor else "минимум %.1f%%" % floor)
    return price * (1 - use / 100.0), use, reason


def leverage_for(symbol, funding_pct, cfg):
    """Плечо по фандингу (правило v5.2). -> (leverage, reason)."""
    lv = cfg["leverage"]
    if not is_btc_eth(symbol):
        return lv["alts_max"], "альт, максимум %dx" % lv["alts_max"]
    if funding_pct is None:
        return lv["btc_eth_max"], "BTC/ETH, фандинг неизвестен -> %dx" % lv["btc_eth_max"]
    if funding_pct > 0.05:
        return 3, "фандинг %.4f%%/ч > 0.05%% -> 3x" % funding_pct
    if funding_pct >= 0.01:
        return 5, "фандинг %.4f%%/ч -> 5x" % funding_pct
    return lv["btc_eth_max"], "фандинг %.4f%%/ч < 0.01%% -> %dx" % (funding_pct, lv["btc_eth_max"])


def target_from_stop(entry, stop_price, side, rr):
    """Цель по R:R."""
    risk = abs(entry - stop_price)
    if risk <= 0:
        return 0.0
    return entry + risk * rr if side == "long" else entry - risk * rr


def btc_filter_check(symbol, side, btc_ctx, cfg):
    """Правило v5.4: шорт альтов запрещён при BTC в 2% от сопротивления.
    btc_ctx: {'price':..,'resistance':..,'support':..,'bars_since_break':..}
    -> (allowed: bool, reason: str)
    """
    if side != "short" or is_btc_eth(symbol):
        return True, ""
    if not btc_ctx:
        return True, "BTC-фильтр: данных нет"
    price = btc_ctx.get("price")
    res = btc_ctx.get("resistance")
    sup = btc_ctx.get("support")
    if not price or not res:
        return True, "BTC-фильтр: сопротивление неизвестно"
    dist = 100.0 * (res - price) / price
    if dist <= cfg["btc_filter_pct"]:
        return False, ("BTC в %.2f%% от сопротивления $%.0f (фильтр %.0f%%) - "
                       "шорт альтов запрещён" % (dist, res, cfg["btc_filter_pct"]))
    if sup:
        d_sup = 100.0 * (price - sup) / price
        if d_sup <= cfg["btc_filter_pct"]:
            return False, ("BTC в %.2f%% от поддержки $%.0f - шорт альтов запрещён"
                           % (d_sup, sup))
    return True, "BTC-фильтр пройден (%.2f%% до сопротивления)" % dist


def funding_block_check(symbol, side, funding_pct, cfg):
    """Правило v5.5: лонг запрещён при фандинге > 0.05%/ч."""
    if side != "long" or not funding_pct:
        return True, ""
    if funding_pct > cfg["funding_long_block_pct"]:
        return False, ("фандинг %.4f%%/ч > %.2f%%/ч - лонг заблокирован"
                       % (funding_pct, cfg["funding_long_block_pct"]))
    return True, ""


def correlation_cap_check(symbol, positions, cfg):
    """Правило v5.14: максимум N позиций с одинаковой BTC-корреляцией."""
    cap = cfg["correlation_cap"]
    same = [p for p in positions
            if str(p.get("symbol", "")).upper() == str(symbol).upper()]
    if len(same) >= cap:
        return False, ("уже %d позиций в %s (cap %d)"
                       % (len(same), symbol, cap))
    return True, "correlation cap %d - ок" % cap


def daily_limit_check(trades_today, pnl_today, cfg):
    """Правило v5.7: стоп на день при -$15 или 3 стопах."""
    if pnl_today is not None and pnl_today <= -cfg["daily_loss_limit_usd"]:
        return False, "дневной лимит убытка $%.0f исчерпан" % cfg["daily_loss_limit_usd"]
    if trades_today >= cfg["max_trades_per_day"]:
        return False, "лимит сделок в день (%d) исчерпан" % cfg["max_trades_per_day"]
    return True, ""


def stop_count_check(stops_today, cfg):
    """Правило v5.7: 3 стопа -> стоп на день."""
    if stops_today >= cfg["max_stops_per_day"]:
        return False, "%d стопов за день - торговля остановлена" % stops_today
    return True, ""


# ---------- РЕШЕНИЯ ПО ПОЗИЦИЯМ ----------

def decide_position(position, candles, cfg, funding_hist=None):
    """
    Что делать с открытой позицией.
    -> dict(action, reason, continuation_probability, reversal_probability, ...)
    action: hold | extend | trail | partial_close | close
    """
    symbol = position.get("symbol")
    side = position.get("side", "long").lower()
    entry = float(position.get("entry", 0) or 0)
    tp = position.get("tp")
    sl = position.get("sl")
    price = candles[-1]["c"] if candles else entry

    cont_sig = continuation_signals(candles, side)
    rev_sig = reversal_signals(candles, side, funding_hist)
    p_cont = calculate_continuation_probability(cont_sig)
    p_rev = calculate_reversal_probability(rev_sig)

    manip = detect_manipulation(candles)
    out = {
        "symbol": symbol,
        "action": "hold",
        "reason": "",
        "continuation_probability": p_cont,
        "reversal_probability": p_rev,
        "continuation_signals": cont_sig,
        "reversal_signals": rev_sig,
        "manipulation": manip,
        "price": price,
    }

    active_cont = [k for k, v in cont_sig.items() if v]
    active_rev = [k for k, v in rev_sig.items() if v]

    # 1) манипуляция -> заморозка
    if manip["anomaly_score"] >= 0.7:
        out["action"] = "hold"
        out["reason"] = ("манипуляция, anomaly_score %.2f - заморозка на 5 минут"
                         % manip["anomaly_score"])
        return out

    # 2) стоп сработал -> закрыть
    if sl and side == "long" and price <= float(sl):
        out["action"] = "close"
        out["reason"] = "сработал стоп $%.4f" % float(sl)
        return out
    if sl and side == "short" and price >= float(sl):
        out["action"] = "close"
        out["reason"] = "сработал стоп $%.4f" % float(sl)
        return out

    # 3) разворот >= 40% -> закрыть
    if p_rev >= 0.40:
        out["action"] = "close"
        out["reason"] = ("вероятность разворота %.0f%% (сигналы: %s)"
                         % (p_rev * 100, ", ".join(active_rev)))
        return out

    # 4) тейк достигнут + вероятность продолжения > 40% -> продлить, не закрывать
    tp_hit = bool(tp) and ((side == "long" and price >= float(tp))
                           or (side == "short" and price <= float(tp)))
    if tp_hit and p_cont > 0.40:
        out["action"] = "extend"
        out["reason"] = ("тейк $%s достигнут, но вероятность продолжения %.0f%% "
                         "(сигналы: %s) - продлить, трейлить стоп"
                         % (tp, p_cont * 100, ", ".join(active_cont)))
        return out

    # 5) тейк достигнут, продолжения нет -> закрыть
    if tp_hit:
        out["action"] = "close"
        out["reason"] = ("тейк $%s достигнут, вероятность продолжения %.0f%% - "
                         "закрывать по плану" % (tp, p_cont * 100))
        return out

    # 6) тренд сильный -> трейлить стоп
    if p_cont >= 0.60 and sl:
        new_sl = stop_for(symbol, price, candles, cfg)[0]
        old = float(sl)
        better = (new_sl > old) if side == "long" else (new_sl < old)
        if better:
            out["action"] = "trail"
            out["new_stop"] = round(new_sl, 6)
            out["reason"] = ("вероятность продолжения %.0f%% - трейлить стоп "
                             "$%.4f -> $%.4f" % (p_cont * 100, old, new_sl))
            return out

    out["action"] = "hold"
    out["reason"] = ("продолжение %.0f%% / разворот %.0f%% - держать"
                     % (p_cont * 100, p_rev * 100))
    return out


# ---------- ТОЧКИ ВХОДА ----------

def find_entries(candidates, cfg, state=None):
    """
    candidates: список dict(symbol, side, candles, price, funding_pct, btc_ctx)
    Возвращает список намерений на вход (отфильтрованных по правилам v5).
    """
    state = state or {}
    positions = state.get("positions", [])
    pnl_today = state.get("pnl_today")
    trades_today = state.get("trades_today", 0)
    stops_today = state.get("stops_today", 0)

    ok_limit, why_limit = daily_limit_check(trades_today, pnl_today, cfg)
    ok_stops, why_stops = stop_count_check(stops_today, cfg)

    intents = []
    for cand in candidates:
        symbol = cand.get("symbol")
        side = (cand.get("side") or "long").lower()
        candles = [norm(c) for c in cand.get("candles", [])]
        if len(candles) < 50:
            continue
        price = float(cand.get("price") or candles[-1]["c"])
        funding = cand.get("funding_pct")

        reasons = []
        if not ok_limit:
            reasons.append(why_limit)
        if not ok_stops:
            reasons.append(why_stops)
        if reasons:
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": "; ".join(reasons)})
            continue

        ok_fund, r_fund = funding_block_check(symbol, side, funding, cfg)
        if not ok_fund:
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": r_fund})
            continue

        ok_btc, r_btc = btc_filter_check(symbol, side, cand.get("btc_ctx"), cfg)
        if not ok_btc:
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": r_btc})
            continue

        ok_corr, r_corr = correlation_cap_check(symbol, positions, cfg)
        if not ok_corr:
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": r_corr})
            continue

        st_dir, st_line = supertrend(candles)
        if st_dir and st_dir != (1 if side == "long" else -1):
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": ("SuperTrend против позиции (%s)"
                                       % ("лонг" if st_dir == 1 else "шорт"))})
            continue

        cont_sig = continuation_signals(candles, side)
        p_cont = calculate_continuation_probability(cont_sig)
        active = [k for k, v in cont_sig.items() if v]
        if p_cont < 0.40:
            intents.append({"symbol": symbol, "side": side, "action": "skip",
                            "reason": ("сигналов продолжения мало: %.0f%% < 40%% "
                                       "(%s)" % (p_cont * 100,
                                                ", ".join(active) or "нет"))})
            continue

        lev, lev_reason = leverage_for(symbol, funding, cfg)
        stop_price, stop_pct, stop_reason = stop_for(symbol, price, candles, cfg)
        if side == "short":
            stop_price = price * (1 + stop_pct / 100.0)
        rr = cfg["rr_min"]
        target = target_from_stop(price, stop_price, side, rr)

        intents.append({
            "symbol": symbol,
            "side": side,
            "action": "enter",
            "price": round(price, 6),
            "leverage": lev,
            "stop_loss": round(stop_price, 6),
            "stop_pct": round(stop_pct, 2),
            "take_profit": round(target, 6),
            "rr": rr,
            "continuation_probability": p_cont,
            "signals": active,
            "reason": ("%s %s, продолжение %.0f%% (%s); плечо %dx - %s; "
                       "стоп %.2f%% - %s" % (symbol, side, p_cont * 100,
                                             ", ".join(active), lev, lev_reason,
                                             stop_pct, stop_reason)),
        })
    return intents


def engine_cycle(candidates=None, positions=None, cfg=None, src="defaults",
                 state=None, funding_map=None):
    """
    Один прогон движка.
    candidates: dict(symbol -> candles) либо список кандидатов.
    positions: список открытых позиций.
    Возвращает dict с решениями по позициям и намерениями на вход.
    """
    if cfg is None:
        cfg, src = load_config()
    positions = positions or []
    funding_map = funding_map or {}

    decisions = []
    for p in positions:
        sym = str(p.get("symbol", "")).upper()
        cand = None
        if isinstance(candidates, dict):
            cand = candidates.get(sym) or candidates.get(p.get("symbol"))
        if not cand:
            decisions.append({"symbol": sym, "action": "hold",
                              "reason": "нет свечей для анализа"})
            continue
        candles = cand["candles"] if isinstance(cand, dict) else cand
        candles = [norm(c) for c in candles]
        d = decide_position(p, candles, cfg, funding_map.get(sym))
        decisions.append(d)

    entries = []
    if candidates:
        if isinstance(candidates, dict):
            cands = []
            for sym, cc in candidates.items():
                cl = cc["candles"] if isinstance(cc, dict) else cc
                cands.append({"symbol": sym, "side": "long",
                              "candles": cl,
                              "price": cl[-1]["c"] if cl else None,
                              "funding_pct": funding_map.get(sym),
                              "btc_ctx": (cc.get("btc_ctx") if isinstance(cc, dict) else None)})
        else:
            cands = candidates
        entries = find_entries(cands, cfg, state)

    return {
        "config_source": src,
        "positions": decisions,
        "entries": entries,
        "stats": {
            "positions_analyzed": len(decisions),
            "entries_ready": len([e for e in entries if e.get("action") == "enter"]),
            "entries_skipped": len([e for e in entries if e.get("action") == "skip"]),
        },
    }


# ============================================================
# СПЕЦИФИКАЦИЯ СИГНАЛОВ (перенесена из v1-файла как исполняемая)
# ============================================================

CONTINUATION_SIGNALS = {
    "hidden_divergence": {
        "name": "Скрытая дивергенция",
        "weight": 0.35,
        "description": ("Цена делает higher low, а RSI - lower low (бычья). "
                        "Или цена делает lower high, а RSI - higher high (медвежья)."),
        "bullish": "price_higher_low AND rsi_lower_low",
        "bearish": "price_lower_high AND rsi_higher_high",
    },
    "momentum_confirmation": {
        "name": "Подтверждение моментума",
        "weight": 0.25,
        "description": ("MACD не пересекал сигнальную линию против тренда, "
                        "гистограмма растёт в сторону тренда."),
        "bullish": "MACD_line > signal_line AND MACD_histogram > prev_histogram",
        "bearish": "MACD_line < signal_line AND MACD_histogram < prev_histogram",
    },
    "volume_trend": {
        "name": "Объём по тренду",
        "weight": 0.20,
        "description": ("Объём на свечах продолжения выше, чем на откатных "
                        "свечах (соотношение > 1.3x)."),
        "bullish": "avg_volume_up > avg_volume_down * 1.3",
        "bearish": "avg_volume_down > avg_volume_up * 1.3",
    },
    "ema_structure": {
        "name": "EMA-структура",
        "weight": 0.20,
        "description": ("EMA5 > EMA13 > EMA50 (бычий веер) или наоборот. "
                        "Без пересечений против тренда."),
        "bullish": "EMA5 > EMA13 > EMA50 AND no_cross_against_trend(20)",
        "bearish": "EMA5 < EMA13 < EMA50 AND no_cross_against_trend(20)",
    },
}

REVERSAL_SIGNALS = {
    "regular_divergence": {
        "name": "Обычная дивергенция",
        "weight": 0.30,
        "description": ("Цена делает higher high, а RSI - lower high (медвежья). "
                        "Или цена делает lower low, а RSI - higher low (бычья)."),
    },
    "volume_climax": {
        "name": "Кульминация объёма",
        "weight": 0.25,
        "description": "Объём > 3x среднего на свече ПРОТИВ тренда.",
    },
    "ema_cross": {
        "name": "EMA-кросс против тренда",
        "weight": 0.20,
        "description": "EMA5 пересекла EMA13 против направления позиции.",
    },
    "support_resistance_rejection": {
        "name": "Отказ от уровня",
        "weight": 0.15,
        "description": "Цена коснулась уровня и развернулась с объёмом.",
    },
    "funding_flip": {
        "name": "Переворот фандинга",
        "weight": 0.10,
        "description": "Фандинг сменил знак против позиции.",
    },
}

MANIPULATION_DETECTOR = {
    "spoofing": {
        "name": "Спуфинг (ложные стенки)",
        "check": "bid/ask imbalance > 10x in top-10 of book",
        "action": "игнорировать уровень, ждать подтверждения реальным объёмом",
    },
    "wash_trading": {
        "name": "Вош-трейдинг",
        "check": "volume > 3x avg AND price_range < 0.1%",
        "action": "пропустить сигнал, объём ненастоящий",
    },
    "stop_hunting": {
        "name": "Охота за стопами",
        "check": "wick > 0.3% AND reversal > 0.5% within 3 bars",
        "action": "расширить стоп за уровнем, не закрывать на вике",
    },
    "anomaly_score": {
        "name": "Композитная аномалия",
        "threshold": 0.7,
        "components": ["spoofing", "wash_trading", "stop_hunting"],
        "action": "заморозить торговлю на 5 минут, перепроверить все сигналы",
    },
}

CONTINUATION_RULES = {
    "threshold": 0.40,
    "max_extensions": 5,
    "trailing_after_extension": {1: 0.5, 2: 0.4, 3: 0.3, 4: 0.2, 5: 0.15},
    "pyramiding": {
        "enabled": True,
        "max_additions": 3,
        "addition_size_pct": 50,
        "condition": "continuation_probability > 0.60 AND price_pulled_back_to_ema13",
    },
    "partial_take": {"enabled": True, "at_extension": 3, "size_pct": 50},
}

ASSET_ROTATION = {
    "scan_interval_minutes": 5,
    "min_volume_24h": 10_000_000,
    "max_positions": 3,
    "priority": ["continuation_probability", "volume_24h", "atr_pct", "funding_rate"],
    "cooldown_after_rotation_minutes": 2,
    "blacklist": {"after_two_losses": True, "duration_minutes": 60},
}

# Цикл исполнения (бывший псевдокод v1 - теперь указывает на реальные функции)
TRADING_LOOP = """Цикл выполняет агент, а не серверный код:
рынок -> мониторинг >5% по монетам из списка Walt -> позиции/баланс Walt
-> точки входа по активной стратегии -> пост-анализ каждого закрытия
-> запись в working memory.

Реализация в этом же файле:
  scan_top5_for_entry()  - отбор кандидатов (до 5) по CONTINUATION_RULES/ASSET_ROTATION
  find_entries()         - прогон фильтров v5, расчёт стопа/цели/плеча
  open_position()        - спецификация ордера для Walt
  decide_position()      - решение по открытой позиции (hold/extend/trail/close)
  partial_close()        - частичное закрытие по CONTINUATION_RULES.partial_take
  freeze_trading()       - заморозка при аномалии
  engine_cycle()         - один полный прогон
Исполнение ордеров - через Walt (у сервера нет ключей биржи)."""

# Заморозка торговли при аномалии
FREEZE = {"symbol": None, "until_ts": 0.0, "reason": ""}


def freeze_trading(symbol, seconds, reason, now_ts=0.0):
    """Заморозить торговлю по символу (правило v5: аномалия -> пауза)."""
    FREEZE["symbol"] = symbol
    FREEZE["until_ts"] = now_ts + float(seconds)
    FREEZE["reason"] = reason
    return dict(FREEZE)


def is_frozen(symbol, now_ts=0.0):
    """Символ заморожен? -> (bool, reason)"""
    if FREEZE["symbol"] == symbol and now_ts < FREEZE["until_ts"]:
        return True, FREEZE["reason"]
    return False, ""


# ============================================================
# СКАНИРОВАНИЕ И ОТБОР АКТИВОВ
# ============================================================

def scan_top5_for_entry(candidates, cfg=None, state=None):
    """
    Отбор до 5 лучших кандидатов на вход по CONTINUATION_RULES и ASSET_ROTATION.
    candidates: [{symbol, side, candles, price, volume_24h, funding_pct, atr_pct, btc_ctx}]
    Возвращает отсортированный список (до 5) готовых намерений на вход.
    """
    if cfg is None:
        cfg, _ = load_config()
    state = state or {}
    intents = find_entries(candidates, cfg, state)
    ready = [i for i in intents if i.get("action") == "enter"]
    ready = [i for i in ready
             if (i.get("volume_24h") or 0) >= ASSET_ROTATION["min_volume_24h"]
             or i.get("volume_24h") is None]
    ready.sort(key=lambda x: (-x.get("continuation_probability", 0),
                              -(x.get("volume_24h") or 0)))
    top = ready[:5]
    for idx, item in enumerate(top):
        item["rank"] = idx + 1
    return top


def open_position(symbol, side, price, candles, cfg=None, funding_pct=None,
                  margin_usd=None, btc_ctx=None):
    """
    Сформировать параметры позиции для открытия.
    НЕ открывает её - возвращает спецификацию ордера для Walt.
    """
    if cfg is None:
        cfg, _ = load_config()
    candles = [norm(c) for c in candles]
    lev, lev_reason = leverage_for(symbol, funding_pct, cfg)
    stop_price, stop_pct_base, stop_reason = stop_for(symbol, price, candles, cfg)
    if side == "short":
        # stop_for() всегда даёт стоп ниже цены (семантика лонга) - для шорта инвертируем
        stop_price = price * (1 + stop_pct_base / 100.0)
    rr = cfg["rr_min"]
    target = target_from_stop(price, stop_price, side, rr)
    return {
        "symbol": symbol,
        "side": side,
        "price": round(price, 6),
        "leverage": lev,
        "margin_usd": margin_usd,
        "stop_loss": round(stop_price, 6),
        "stop_pct": round(stop_pct_base, 2),
        "take_profit": round(target, 6),
        "rr": rr,
        "reason": ("плечо %dx (%s); стоп %.2f%% (%s); цель по R:R 1:%d"
                   % (lev, lev_reason, stop_pct_base, stop_reason, rr)),
    }


def partial_close(position, price, extension_number=1, cfg=None):
    """
    Частичное закрытие по правилу CONTINUATION_RULES.partial_take.
    Возвращает спецификацию (доля, объём в USD) - исполняет Walt.
    """
    if cfg is None:
        cfg, _ = load_config()
    rules = CONTINUATION_RULES["partial_take"]
    if not rules.get("enabled"):
        return {"action": "none", "reason": "частичное закрытие выключено"}
    if extension_number < rules["at_extension"]:
        return {"action": "none",
                "reason": "частичное закрытие с расширения %d (порог %d)"
                          % (extension_number, rules["at_extension"])}
    size = float(position.get("size", 0) or 0)
    frac = rules["size_pct"] / 100.0
    return {
        "action": "partial_close",
        "symbol": position.get("symbol"),
        "fraction": frac,
        "amount_usd": round(size * frac, 2),
        "reason": "частичное закрытие %.0f%% на расширении %d"
                  % (rules["size_pct"], extension_number),
    }


def trailing_stop_after_extension(symbol, side, entry, price, extension_number,
                                  cfg=None):
    """Стоп за ценой на N-м расширении (CONTINUATION_RULES)."""
    if cfg is None:
        cfg, _ = load_config()
    steps = CONTINUATION_RULES["trailing_after_extension"]
    if extension_number not in steps:
        return {"action": "none", "reason": "нет правила для расширения %d" % extension_number}
    off = steps[extension_number]
    stop = (price * (1 - off / 100.0) if side == "long"
            else price * (1 + off / 100.0))
    return {"symbol": symbol, "action": "trail", "new_stop": round(stop, 6),
            "reason": "расширение %d: стоп %.2f%% за ценой $%.6f"
                      % (extension_number, off, stop)}
