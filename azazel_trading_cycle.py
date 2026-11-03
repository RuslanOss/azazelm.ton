# -*- coding: utf-8 -*-
"""Торговый цикл: рынок -> решения -> исполнение -> лог.

Четыре шага:
  1) собрать свечи по кандидатам (публичные методы Walt, ключ не нужен);
  2) отдать их движку engine_cycle - тот применяет риск-фильтры v5;
  3) по намерениям, которые движок разрешил, построить план позиции
     (плечо, стоп, цель, размер) через open_position;
  4) исполнить план через execute_plan - но только если разрешено
     автоподтверждением.

Автоподтверждение по умолчанию ВЫКЛ. Пока пользователь явно не включил
его в профиле, цикл готовит планы и пишет их в лог, но ордера не
отправляет: до первой живой сделки все проверки должны быть видны.

Ключ Walt берётся из профиля пользователя (JSON), а не из окружения:
ключи у каждого свои. Без ключа цикл всё равно отрабатывает рыночную
часть (публичные методы не требуют подписи) и честно пишет, что
торговать нельзя.

Клиент можно подставить снаружи (client=...) - это нужно тестам, чтобы
не ходить в сеть, и это же позволяет использовать один цикл с разными
источниками данных.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import continuation_engine as ce
except Exception:
    ce = None

try:
    from walt_client import WaltClient
except Exception:
    WaltClient = None

DEFAULT_CANDIDATES = ["BTC", "ETH", "SOL", "LIT", "HYPE", "ZEC",
                       "LINK", "ENA", "SUI", "AVAX"]
DEFAULT_INTERVAL = "15m"
DEFAULT_LIMIT = 200
BASE_URL = "https://bot.mywellat.com"

# Поля профиля Airtable -> плоские ключи extra движка.
PROFILE_TO_EXTRA = {
    "Стоп альты %": "stop_alts",
    "Стоп BTC/ETH %": "stop_btc",
    "ATR-множитель": "atr",
    "Мин R:R": "rr",
    "BTC-фильтр %": "btc_filter",
    "Блок лонга фандинг %": "funding",
    "Дневной лимит убытка $": "loss_limit",
    "Стопов в день": "max_stops",
    "Correlation cap": "corr_cap",
    "Сделок в день": "max_trades",
    "Плечо альты": "lev_alts",
    "Плечо BTC/ETH": "lev_btc",
}


def profile_to_extra(profile):
    """Плоские ключи extra из профиля Airtable."""
    out = {}
    for field, key in PROFILE_TO_EXTRA.items():
        v = (profile or {}).get(field)
        if v is None or v == "":
            continue
        try:
            out[key] = float(v)
        except (TypeError, ValueError):
            out[key] = v
    return out


def make_client(key=None, secret=None, base_url=None):
    """Клиент Walt: из профиля пользователя, иначе из окружения.

    -> (client, error). error=None если клиент создан.
    """
    if WaltClient is None:
        return None, "модуль walt_client не импортируется"
    key = (key or os.environ.get("WALT_API_KEY") or "").strip()
    secret = (secret or os.environ.get("WALT_API_SECRET") or "").strip()
    url = (base_url or os.environ.get("WALT_BASE_URL") or BASE_URL).strip()
    try:
        if not key or not secret:
            # публичные методы (свечи, тикер, фандинг) подписи не требуют
            return WaltClient("public", "public", base_url=url), "нет ключа Walt - только публичные данные"
        return WaltClient(key, secret, base_url=url), None
    except Exception as e:
        return None, "клиент Walt: %s" % str(e)[:200]


def collect_market(client, symbols, interval=DEFAULT_INTERVAL,
                   limit=DEFAULT_LIMIT, btc_symbol="BTCUSDT"):
    """Собрать свечи, фандинг и контекст BTC. -> dict."""
    out = {"candles": {}, "funding": {}, "btc_ctx": None, "errors": []}
    if client is None:
        out["errors"].append("нет клиента Walt")
        return out
    for sym in symbols:
        ticker = str(sym).upper()
        if not ticker.endswith("USDT"):
            ticker += "USDT"
        try:
            kl = client.klines(ticker, interval, limit)
        except Exception as e:
            out["errors"].append("%s: свечи %s" % (ticker, str(e)[:120]))
            continue
        if not kl:
            out["errors"].append("%s: свечей нет" % ticker)
            continue
        out["candles"][ticker] = kl
        try:
            fr = client.funding_rate(ticker, 3)
            if fr:
                out["funding"][ticker] = float(fr[-1].get("fundingRate") or 0) * 100.0
        except Exception:
            pass
    try:
        px = client.ticker_price(btc_symbol)
        btc_price = float((px or {}).get("price") or 0)
        resistance = btc_price
        kl = out["candles"].get(btc_symbol) or []
        highs = [float(k.get("h") or 0) for k in kl[-48:] if k.get("h")]
        if highs:
            resistance = max(highs)
        out["btc_ctx"] = {"price": btc_price, "resistance": resistance,
                          "symbol": btc_symbol}
    except Exception as e:
        out["errors"].append("BTC-контекст: %s" % str(e)[:120])
    return out


def build_candidates(market):
    """Из собранного рынка собрать кандидатов для движка."""
    cands = []
    for ticker, kl in (market.get("candles") or {}).items():
        if not kl:
            continue
        price = float(kl[-1].get("c") or 0)
        if price <= 0:
            continue
        cands.append({
            "symbol": ticker.replace("USDT", ""),
            "side": "long",
            "candles": kl,
            "price": price,
            "funding_pct": (market.get("funding") or {}).get(ticker),
            "btc_ctx": market.get("btc_ctx"),
        })
    return cands


def run_cycle(profile=None, state=None, symbols=None, key=None, secret=None,
              dry_run=None, auto_confirm=None, executor=None, client=None,
              cfg=None):
    """Один прогон торгового цикла. -> dict отчёта.

    Никогда не бросает исключение: сбой одного шага не должен ронять
    весь цикл - остальные пользователи должны отработать.
    """
    rep = {"ok": False, "stage": "start", "market": None, "decisions": [],
           "entries": [], "plans": [], "executed": [], "errors": [],
           "traded": False, "reason": "", "auto_confirm": False}
    try:
        if ce is None:
            rep["reason"] = "движок не импортируется"
            return rep
        profile = profile or {}
        state = state or {}
        symbols = symbols or DEFAULT_CANDIDATES
        extra = profile_to_extra(profile)

        if auto_confirm is None:
            auto_confirm = bool(profile.get("Автоподтверждение"))
        rep["auto_confirm"] = bool(auto_confirm)

        # 1) рынок
        rep["stage"] = "market"
        if client is None:
            client, cerr = make_client(key, secret)
            if client is None:
                rep["errors"].append(cerr or "нет клиента Walt")
                rep["reason"] = cerr or "нет клиента Walt"
                return rep
            if cerr:
                rep["public_only"] = True
                rep["errors"].append(cerr)

        market = collect_market(client, symbols)
        rep["market"] = {"candles": len(market.get("candles") or {}),
                         "btc_ctx": market.get("btc_ctx"),
                         "errors": market.get("errors")}
        if not market.get("candles"):
            rep["reason"] = "рынок не собран"
            return rep

        # 2) решения движка
        rep["stage"] = "decide"
        cands = build_candidates(market)
        if cfg is None:
            try:
                # load_config() возвращает (cfg, src) - кортеж, а не словарь
                loaded = ce.load_config()
                if isinstance(loaded, tuple):
                    cfg = loaded[0]
                else:
                    cfg = loaded
            except Exception as e:
                rep["errors"].append("конфиг: %s" % str(e)[:150])
                cfg = {}
        cyc = ce.engine_cycle(candidates=cands,
                               positions=state.get("positions") or [],
                               cfg=cfg, state=state,
                               funding_map=market.get("funding"),
                               extra=extra)
        rep["decisions"] = cyc.get("positions") or []
        rep["entries"] = cyc.get("entries") or []
        rep["stats"] = cyc.get("stats") or {}
        rep["config_source"] = cyc.get("config_source")

        # 3) планы на вход. open_position требует свечи - берём их из рынка
        rep["stage"] = "plan"
        free_margin = float(state.get("free_margin") or 0)
        candles_by_symbol = {}
        for c in cands:
            candles_by_symbol[str(c["symbol"]).upper()] = c.get("candles") or []
        for ent in rep["entries"]:
            if ent.get("action") != "enter":
                continue
            sym = str(ent.get("symbol") or "").upper()
            try:
                op = ce.open_position(sym, ent.get("side") or "long",
                                      ent.get("price"),
                                      candles_by_symbol.get(sym) or [],
                                      cfg,
                                      funding_pct=ent.get("funding_pct"),
                                      margin_usd=free_margin,
                                      extra=extra)
            except Exception as e:
                rep["errors"].append("план %s: %s" % (sym, str(e)[:150]))
                continue
            op["signals"] = ent.get("signals")
            op["continuation_probability"] = ent.get("continuation_probability")
            op["reason_entry"] = ent.get("reason")
            rep["plans"].append(op)

        # 4) исполнение
        rep["stage"] = "execute"
        if not rep["plans"]:
            rep["reason"] = "нет разрешённых входов"
            return rep
        if not auto_confirm:
            rep["reason"] = ("автоподтверждение выключено - планы подготовлены, "
                             "ордера не отправлены")
            return rep
        if free_margin <= 0:
            rep["reason"] = "нет свободной маржи"
            return rep
        for plan in rep["plans"]:
            try:
                res = ce.execute_plan(plan, executor=executor, dry_run=dry_run,
                                      key=key, secret=secret)
            except Exception as e:
                rep["errors"].append("исполнение %s: %s" % (plan.get("symbol"),
                                                            str(e)[:150]))
                continue
            rep["executed"].append({"symbol": plan.get("symbol"),
                                    "ok": res.get("ok"),
                                    "error": res.get("error")})
            if res.get("ok"):
                rep["traded"] = True
        rep["ok"] = True
        rep["reason"] = "цикл отработан"
        return rep

    except Exception as e:
        rep["errors"].append(traceback.format_exc(limit=3)[-500:])
        rep["reason"] = "цикл упал: %s" % str(e)[:200]
        return rep
