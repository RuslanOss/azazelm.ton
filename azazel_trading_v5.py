# -*- coding: utf-8 -*-
"""Azazel Trading Layer v5.

Dva sloya:
  1) Decision layer (chistaya logika) - reshaet, can-li vxodit, s kakim stopom/teikom/leverage.
     Ne imeet ni odnoy stroki I/O - testiruetsya chisto.
  2) Executor (Lighter SDK) - ispolnyaet plan cherez SignerClient.

Pravila v5 (istochnik pravdy - azazel_config.json + profil yuzera v Airtable):
  - Stop alty >= 3% (BTC/ETH >= 1.5%), dlya altkoinov stop = max(min_stop, atr_mult * ATR)
  - R:R >= 1:2
  - Plecho po fandingu: >0.05%/8h -> 3x, 0.01-0.05% -> 5x, <0.01% -> 10x (BTC/ETH);
    alty - ne bolee 5x vsehdy
  - BTC-filter: SHORT altkoinov zapreshen, esli BTC v predele 2% ot soprotivleniya
  - Fanding > 0.05%/8h -> LONG zapreshen
  - Korrelyatsionny potolok: <= 2 pozitsii s odinakovoy BTC-korrelyaciyey
  - Dnevnoj limit u bytka -$15 ili 3 stopa -> stop na den
  - Ne bolee 5 sdelok v den
  - Risk na sdelku: 33% marzhi (ROI 1/3)
"""
import math

# ---------------------------------------------------------------- konstanty
BTC_ETH = {"BTC", "ETH"}
MAJOR = BTC_ETH | {"SOL", "BNB", "XAU", "XAG"}

FUNDING_HIGH = 0.05      # %/8h
FUNDING_MID = 0.01

DEFAULT_PROFILE = {
    "tier": "средний",
    "mode": "scalp_daily",
    "lev_alts": 5,
    "lev_btc": 10,
    "stop_alts": 3.0,
    "stop_btc": 1.5,
    "atr": 1.0,
    "rr": 2,
    "btc_filter": 2.0,
    "funding": 0.05,
    "loss_limit": 15.0,
    "max_stops": 3,
    "corr_cap": 2,
    "max_trades": 5,
    "timeframes": "15m,1h,4h",
    "autoconfirm": True,
}


class Decision(object):
    """Rezultat reshcheniya: allow + plan, ili allow=False + prichina."""

    def __init__(self, allow, reason, plan=None, rule=None):
        self.allow = allow
        self.reason = reason
        self.plan = plan or {}
        self.rule = rule

    def to_dict(self):
        return {"allow": self.allow, "reason": self.reason,
                "rule": self.rule, "plan": self.plan}

    def __repr__(self):
        return "<Decision allow=%s rule=%s reason=%s>" % (
            self.allow, self.rule, self.reason)


# ---------------------------------------------------------------- pomoshchniki
def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def is_btc_eth(symbol):
    return (symbol or "").upper() in BTC_ETH


def resolve_leverage(symbol, funding_pct, profile):
    """Plecho po fandingu (pravilo v5). Alty - ne bolee lev_alts."""
    p = profile or DEFAULT_PROFILE
    lev_alts = int(_f(p.get("lev_alts"), 5))
    lev_btc = int(_f(p.get("lev_btc"), 10))
    if not is_btc_eth(symbol):
        return max(1, min(lev_alts, 5))
    f = _f(funding_pct, 0.0)
    if f > FUNDING_HIGH:
        cap = 3
    elif f >= FUNDING_MID:
        cap = 5
    else:
        cap = 10
    return max(1, min(lev_btc, cap))


def resolve_stop_pct(symbol, atr_pct, profile):
    """Stop v %: alty = max(min_stop, atr_mult*ATR), BTC/ETH = min_stop."""
    p = profile or DEFAULT_PROFILE
    mult = _f(p.get("atr"), 1.0)
    if is_btc_eth(symbol):
        return _f(p.get("stop_btc"), 1.5)
    base = _f(p.get("stop_alts"), 3.0)
    atr_stop = mult * _f(atr_pct, 0.0)
    return max(base, atr_stop, 1e-9)


def resolve_take_pct(symbol, stop_pct, profile):
    """Tek = stop * rr (R:R 1:2 po umolchaniyu)."""
    p = profile or DEFAULT_PROFILE
    rr = max(1.0, _f(p.get("rr"), 2))
    return stop_pct * rr


def size_by_risk(margin_usd, entry, stop_pct, risk_pct=33.0, leverage=5.0):
    """Notional po risku: poterya na stop = risk_pct% marzhi.

    margin = risk_usd / (stop_pct/100 * leverage)
    Esli trebuemyj margin bolshe dostupnogo - umenshaem pozitsiyu (risk tozhe padaet).
    vozvrashchaet {'margin', 'notional', 'risk_usd', 'units', 'leverage', 'stop_pct'}
    """
    margin = max(0.0, _f(margin_usd, 0.0))
    entry = _f(entry, 0.0)
    stop_pct = _f(stop_pct, 0.0)
    lev = max(1.0, _f(leverage, 5.0))
    if stop_pct <= 0 or entry <= 0 or margin <= 0:
        return {"margin": 0.0, "notional": 0.0, "risk_usd": 0.0,
                "leverage": lev, "stop_pct": stop_pct, "units": 0.0}
    risk_usd = margin * (_f(risk_pct, 33.0) / 100.0)
    notional = risk_usd / (stop_pct / 100.0)
    used_margin = notional / lev
    if used_margin > margin:
        used_margin = margin
        notional = used_margin * lev
        risk_usd = notional * (stop_pct / 100.0)
    return {"margin": used_margin, "notional": notional,
            "risk_usd": risk_usd, "leverage": lev, "stop_pct": stop_pct,
            "units": notional / entry}


# ---------------------------------------------------------------- filtry
def check_daily_limits(state, profile):
    """Dnevnoj limit u bytka / limit stopov / limit sdelok."""
    p = profile or DEFAULT_PROFILE
    st = state or {}
    if _f(st.get("pnl_day_usd"), 0.0) <= -abs(_f(p.get("loss_limit"), 15.0)):
        return Decision(False, "Дневной лимит убытка исчерпан",
                        rule="R7_loss_limit")
    if int(st.get("stops_today", 0)) >= int(p.get("max_stops", 3)):
        return Decision(False, "Достигнут лимит стопов за день",
                        rule="R7_stops_per_day")
    if int(st.get("trades_today", 0)) >= int(p.get("max_trades", 5)):
        return Decision(False, "Достигнут лимит сделок за день",
                        rule="R8_max_trades")
    return Decision(True, "Дневные лимиты в порядке")


def check_btc_filter(side, symbol, btc_price, btc_resistance, profile):
    """SHORT altkoinov zapreshen, esli BTC v predele btc_filter% ot soprotivleniya."""
    p = profile or DEFAULT_PROFILE
    if side != "short" or is_btc_eth(symbol):
        return Decision(True, "BTC-фильтр не применяется")
    r = _f(btc_resistance, 0.0)
    px = _f(btc_price, 0.0)
    if r <= 0 or px <= 0:
        return Decision(True, "Нет данных по сопротивлению BTC")
    dist = (r - px) / r * 100.0
    lim = _f(p.get("btc_filter"), 2.0)
    if dist <= lim:
        return Decision(False,
                        "BTC в %.2f%% от сопротивления $%.0f (<= %.1f%%) - "
                        "шорт альтов запрещён" % (dist, r, lim),
                        rule="R4_btc_filter")
    return Decision(True, "BTC далеко от сопротивления (%.2f%%)" % dist)


def check_funding(side, funding_pct, profile):
    """Fanding > limita -> LONG zapreshen."""
    p = profile or DEFAULT_PROFILE
    if side != "long":
        return Decision(True, "Фандинг ограничивает только лонги")
    f = _f(funding_pct, 0.0)
    lim = _f(p.get("funding"), 0.05)
    if f > lim:
        return Decision(False,
                        "Фандинг %.4f%%/8ч > %.2f%% - лонг запрещён" % (f, lim),
                        rule="R5_funding_long_block")
    return Decision(True, "Фандинг %.4f%% допустим" % f)


def check_correlation(side, symbol, open_positions, profile):
    """Ne bolee corr_cap pozitsiy s odinakovoy BTC-korrelyaciyey.

    Vse altkoiny schitayutsya odinovo korrelyirovannymi s BTC.
    """
    p = profile or DEFAULT_PROFILE
    cap = int(p.get("corr_cap", 2))
    positions = open_positions or []
    if not positions:
        return Decision(True, "Нет открытых позиций")
    same_group = 0
    for pos in positions:
        sym = (pos.get("symbol") or "").upper()
        if sym == "BTC":
            continue
        same_group += 1
    if same_group >= cap:
        return Decision(False,
                        "Уже %d позиции с BTC-корреляцией (потолок %d) - "
                        "диверсификация нулевая" % (same_group, cap),
                        rule="R4_correlation_cap")
    return Decision(True, "Корреляционный потолок не достигнут (%d/%d)"
                    % (same_group, cap))


def check_news_filter(news_event=None, min_score=0.7):
    """Novostnoj filtr: silnaya novost blokiruet vhod.

    news_event: dict s {'score': 0..1, 'direction': 'bull'|'bear', 'age_hours': N}
    """
    if not news_event:
        return Decision(True, "Новостных событий нет")
    score = _f(news_event.get("score"), 0.0)
    age = _f(news_event.get("age_hours"), 99.0)
    if score >= min_score and age <= 24:
        return Decision(False,
                        "Свежая сильная новость (score %.2f, %.0fч) - вход "
                        "заблокирован до подтверждения разворота" % (score, age),
                        rule="R6_news_filter")
    return Decision(True, "Новостной фильтр пройден")


def check_stop_sane(symbol, stop_pct, profile):
    """Minimalnyj stop: alty >= 3%, BTC/ETH >= 1.5%."""
    p = profile or DEFAULT_PROFILE
    need = _f(p.get("stop_btc"), 1.5) if is_btc_eth(symbol) else _f(p.get("stop_alts"), 3.0)
    if _f(stop_pct, 0.0) < need:
        return Decision(False,
                        "Стоп %.2f%% ниже минимума %.2f%%" % (_f(stop_pct), need),
                        rule="R1_stop_floor")
    return Decision(True, "Стоп %.2f%% проходит порог %.2f%%" % (_f(stop_pct), need))


def check_rr(stop_pct, take_pct, profile):
    p = profile or DEFAULT_PROFILE
    rr_min = _f(p.get("rr"), 2)
    if stop_pct <= 0:
        return Decision(False, "Нулевой стоп", rule="R3_rr")
    rr = take_pct / stop_pct
    if rr < rr_min:
        return Decision(False,
                        "R:R 1:%.2f < требуемого 1:%s" % (rr, rr_min),
                        rule="R3_rr")
    return Decision(True, "R:R 1:%.2f" % rr)


# ---------------------------------------------------------------- glavnaya vhodka
def plan_trade(symbol, side, entry, atr_pct=0.0, funding_pct=0.0,
               margin_usd=0.0, btc_price=0.0, btc_resistance=0.0,
               open_positions=None, state=None, news_event=None,
               profile=None, risk_pct=33.0):
    """Polnyy plan vxoda ili otkaz s pravilom.

    Parametry:
      symbol, side ('long'/'short'), entry - cena
      atr_pct - ATR v % (dlya stopa altkoinov)
      funding_pct - fanding %/8h
      margin_usd - svobodnaya marzha
      btc_price, btc_resistance - dlya BTC-filtra
      open_positions - spisok dict {'symbol':...}
      state - {'pnl_day_usd':..., 'stops_today':..., 'trades_today':...}
      news_event - {'score':..., 'age_hours':...}
      profile - parametry yuzera (Airtable), merge s DEFAULT_PROFILE
    """
    p = dict(DEFAULT_PROFILE)
    p.update({k: v for k, v in (profile or {}).items() if v is not None})

    if side not in ("long", "short"):
        return Decision(False, "Сторона должна быть long или short", rule="R0_input")
    if _f(margin_usd, 0.0) <= 0:
        return Decision(False, "Нет свободной маржи", rule="R0_margin")

    checks = [
        check_daily_limits(state, p),
        check_btc_filter(side, symbol, btc_price, btc_resistance, p),
        check_funding(side, funding_pct, p),
        check_correlation(side, symbol, open_positions, p),
        check_news_filter(news_event),
    ]
    for c in checks:
        if not c.allow:
            return c

    lev = resolve_leverage(symbol, funding_pct, p)
    stop_pct = resolve_stop_pct(symbol, atr_pct, p)
    take_pct = resolve_take_pct(symbol, stop_pct, p)

    c = check_stop_sane(symbol, stop_pct, p)
    if not c.allow:
        return c
    c = check_rr(stop_pct, take_pct, p)
    if not c.allow:
        return c

    entry = _f(entry, 0.0)
    if entry <= 0:
        return Decision(False, "Некорректная цена входа", rule="R0_input")

    sizing = size_by_risk(margin_usd, entry, stop_pct, risk_pct, leverage=lev)

    if side == "long":
        stop_price = entry * (1 - stop_pct / 100.0)
        take_price = entry * (1 + take_pct / 100.0)
    else:
        stop_price = entry * (1 + stop_pct / 100.0)
        take_price = entry * (1 - take_pct / 100.0)

    plan = {
        "symbol": symbol.upper(),
        "side": side,
        "entry": entry,
        "stop_price": stop_price,
        "take_price": take_price,
        "stop_pct": stop_pct,
        "take_pct": take_pct,
        "leverage": lev,
        "margin_usd": sizing["margin"],
        "notional_usd": sizing["notional"],
        "risk_usd": sizing["risk_usd"],
        "units": sizing["units"],
        "rr": take_pct / stop_pct,
        "atr_pct": _f(atr_pct, 0.0),
        "funding_pct": _f(funding_pct, 0.0),
        "mode": p.get("mode"),
        "auto_confirm": bool(p.get("autoconfirm")),
        "timeframes": p.get("timeframes"),
    }
    return Decision(True,
                    "План готов: %s %s x%d, стоп %.2f%%, R:R 1:%.1f" % (
                        side.upper(), symbol.upper(), lev, stop_pct, plan["rr"]),
                    plan=plan)


# ---------------------------------------------------------------- ispolnitel
class LighterExecutor(object):
    """Ispolnitel planov cherez Lighter SDK (opcionalno, import pri nalichii)."""

    def __init__(self, client, market_index, market_id=None):
        self.client = client
        self.market_index = market_index
        self.market_id = market_id

    def _is_ask(self, side):
        return side == "short"

    def open_with_protection(self, plan, api_key_index=255):
        """Otkryt pozitsiyu + postavit TP i SL. vozvrashchaet dict rezultata."""
        from lighter import SignerClient
        S = SignerClient
        out = {"ok": False, "steps": []}
        sym = plan["symbol"]
        mi = self.market_index
        units = float(plan["units"])
        is_ask = self._is_ask(plan["side"])

        # 1) market order
        try:
            tx, resp, err = self.client.create_market_order(
                market_index=mi, client_order_index=0, base_amount=units,
                avg_execution_price=float(plan["entry"]), is_ask=is_ask,
                reduce_only=False, api_key_index=api_key_index)
            if err:
                out["steps"].append({"op": "market_order", "error": str(err)})
                return out
            out["steps"].append({"op": "market_order", "ok": True})
        except Exception as e:
            out["steps"].append({"op": "market_order", "error": str(e)[:300]})
            return out

        # 2) stop-loss
        try:
            tx, resp, err = self.client.create_sl_order(
                market_index=mi, client_order_index=0, base_amount=units,
                trigger_price=float(plan["stop_price"]),
                price=float(plan["stop_price"]), is_ask=not is_ask,
                reduce_only=True, api_key_index=api_key_index)
            out["steps"].append({"op": "stop_loss",
                                 "ok": not err, "error": str(err) if err else None})
        except Exception as e:
            out["steps"].append({"op": "stop_loss", "error": str(e)[:300]})

        # 3) take-profit
        try:
            tx, resp, err = self.client.create_tp_order(
                market_index=mi, client_order_index=0, base_amount=units,
                trigger_price=float(plan["take_price"]),
                price=float(plan["take_price"]), is_ask=not is_ask,
                reduce_only=True, api_key_index=api_key_index)
            out["steps"].append({"op": "take_profit",
                                 "ok": not err, "error": str(err) if err else None})
        except Exception as e:
            out["steps"].append({"op": "take_profit", "error": str(e)[:300]})

        out["ok"] = all(s.get("ok") for s in out["steps"])
        return out

    def close_position(self, units, side, market_index=None):
        """Zakryt pozitsiyu reduce_only market orderom."""
        mi = market_index if market_index is not None else self.market_index
        try:
            tx, resp, err = self.client.create_market_order(
                market_index=mi, client_order_index=0, base_amount=float(units),
                avg_execution_price=0.0, is_ask=(side == "long"),
                reduce_only=True)
            return {"ok": not err, "error": str(err) if err else None}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    def set_leverage(self, leverage, margin_mode=1):
        """margin_mode: 1 = isolated, 0 = cross."""
        try:
            self.client.update_leverage(self.market_index, margin_mode, int(leverage))
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}


# ---------------------------------------------------------------- vhod-vyhody
def update_daily_state(state, event, profile=None):
    """Obnovit svyodku dnya: pnl, schyotchik stopov i sdelok.

    event: {'type': 'trade_closed', 'pnl_usd': float}
           {'type': 'stop_hit', 'pnl_usd': float}
    """
    st = dict(state or {})
    p = profile or DEFAULT_PROFILE
    st.setdefault("pnl_day_usd", 0.0)
    st.setdefault("stops_today", 0)
    st.setdefault("trades_today", 0)
    t = (event or {}).get("type")
    pnl = _f((event or {}).get("pnl_usd"), 0.0)
    if t == "trade_closed":
        st["trades_today"] = int(st["trades_today"]) + 1
        st["pnl_day_usd"] = _f(st["pnl_day_usd"]) + pnl
    elif t == "stop_hit":
        st["stops_today"] = int(st["stops_today"]) + 1
        st["trades_today"] = int(st["trades_today"]) + 1
        st["pnl_day_usd"] = _f(st["pnl_day_usd"]) + pnl
    st["trading_halted"] = bool(
        _f(st["pnl_day_usd"]) <= -abs(_f(p.get("loss_limit"), 15.0))
        or int(st["stops_today"]) >= int(p.get("max_stops", 3))
        or int(st["trades_today"]) >= int(p.get("max_trades", 5)))
    return st
