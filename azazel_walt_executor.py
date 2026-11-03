# -*- coding: utf-8 -*-
"""Исполнитель торговых планов через Walt (замена LighterExecutor).

Почему отдельный модуль, а не правка слоя v5: azazel_trading_v5.py -
эталонная риск-логика, её трогать нельзя. Исполнитель - торговая часть,
она меняется.

Что изменилось по сравнению с LighterExecutor:
  * адресация - Lighter работал по числовому market_index, Walt - по тикеру.
    Нужен маппинг тикеров (LIT -> LITUSDT).
  * защита ставится В СОМ ордере (stopLossPrice/takeProfitPrice в /fapi/v1/order),
    а не тремя отдельными вызовами. Одна транзакция вместо трёх, и нет окна,
    когда позиция живёт без стопа.
  * quantity округляется под фильтры биржи (LOT_SIZE) клиентом.
  * проверка MIN_NOTIONAL: биржа требует от $50 номинала. Ордер меньше
    отклоняется, поэтому проверяем ДО отправки.

Интерфейс совместим с LighterExecutor: open_with_protection, close_position,
set_leverage. Планы приходят в формате слоя v5.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from walt_client import WaltError
except Exception:  # клиент не установлен - исполнитель просто не поднимется
    WaltError = Exception


# Тикеры Walt: базовый актив -> фьючерный тикер. Неизвестные символы
# получают суффикс USDT по умолчанию.
def walt_symbol(symbol):
    s = str(symbol or "").upper().strip()
    if not s:
        return s
    if s.endswith("USDT") or s.endswith("USDC") or s.endswith("USD"):
        return s
    return s + "USDT"


class WaltExecutor(object):
    """Исполнитель планов через Walt API."""

    # Минимальный номинал в USDT (фильтр MIN_NOTIONAL биржи).
    MIN_NOTIONAL_USD = 50.0

    def __init__(self, client, market_index=None, market_id=None,
                 min_notional=None, dry_run=False):
        self.client = client
        # market_index в Lighter был числом; здесь оставлен для совместимости
        # сигнатуры, но не используется - Walt адресуется тикером.
        self.market_index = market_index
        self.market_id = market_id
        self.min_notional = float(min_notional) if min_notional is not None \
            else self.MIN_NOTIONAL_USD
        # dry_run=True - считаем и проверяем, но НЕ отправляем ордер.
        self.dry_run = dry_run

    # ---------- вспомогательное ----------

    def _plan_symbol(self, plan):
        return walt_symbol(plan.get("symbol"))

    def _plan_notional(self, plan, symbol, price=None):
        """Номинал позиции: из плана, иначе маржа*плечо."""
        n = plan.get("notional_usd")
        if n:
            return float(n)
        units = float(plan.get("units") or 0)
        if units and price:
            return units * price
        margin = float(plan.get("margin_usd") or 0)
        lev = float(plan.get("leverage") or 1)
        return margin * lev

    def _check_notional(self, symbol, notional):
        """MIN_NOTIONAL биржи. Возвращает (ok, reason)."""
        if notional < self.min_notional - 1e-9:
            return False, ("номинал $%.2f < минимального $%.0f для %s"
                           % (notional, self.min_notional, symbol))
        return True, ""

    def _check_plan(self, plan):
        """Базовые проверки плана до похода на биржу."""
        for k in ("symbol", "side", "stop_price", "take_price"):
            if plan.get(k) is None:
                return False, "в плане нет поля %s" % k
        if plan["side"] not in ("long", "short"):
            return False, "неизвестная сторона: %s" % plan["side"]
        entry = float(plan.get("entry") or 0)
        stop = float(plan["stop_price"])
        take = float(plan["take_price"])
        if entry <= 0:
            return False, "нет цены входа"
        if plan["side"] == "long":
            if stop >= entry:
                return False, ("стоп лонга %.6f не ниже входа %.6f"
                               % (stop, entry))
            if take <= entry:
                return False, ("тейк лонга %.6f не выше входа %.6f"
                               % (take, entry))
        else:
            if stop <= entry:
                return False, ("стоп шорта %.6f не выше входа %.6f"
                               % (stop, entry))
            if take >= entry:
                return False, ("тейк шорта %.6f не ниже входа %.6f"
                               % (take, entry))
        return True, ""

    # ---------- основные операции ----------

    def open_with_protection(self, plan, api_key_index=255):
        """Открыть позицию вместе со стопом и тейком. -> dict результата.

        Возвращает {"ok": bool, "steps": [...], ...}. При ошибке "ok"=False
        и steps содержит причину. Никогда не бросает исключение наружу -
        вызывающий движок не должен падать из-за биржи.
        """
        out = {"ok": False, "steps": [], "symbol": None, "order_id": None}
        symbol = self._plan_symbol(plan)
        out["symbol"] = symbol

        ok, why = self._check_plan(plan)
        if not ok:
            out["steps"].append({"op": "validate", "error": why})
            return out

        try:
            price = float(plan.get("entry") or 0)
            notional = self._plan_notional(plan, symbol, price)
        except Exception as e:
            out["steps"].append({"op": "notional", "error": str(e)[:300]})
            return out

        ok, why = self._check_notional(symbol, notional)
        if not ok:
            out["steps"].append({"op": "min_notional", "error": why})
            return out

        # quantity: из юнитов плана, иначе номинал/цена
        units = plan.get("units")
        quantity = None
        if units:
            quantity = float(units)
        elif price > 0:
            quantity = notional / price

        margin = plan.get("margin_usd")
        lev = int(plan.get("leverage") or 1)

        if self.dry_run:
            out["steps"].append({"op": "dry_run", "ok": True,
                                 "detail": "ордер не отправлен (dry_run)"})
            out["ok"] = True
            out["notional_usd"] = notional
            out["quantity"] = quantity
            return out

        # 1) плечо и маржинальный режим
        try:
            self.client.set_leverage(symbol, lev)
            out["steps"].append({"op": "set_leverage", "ok": True,
                                 "leverage": lev})
        except WaltError as e:
            out["steps"].append({"op": "set_leverage", "error": str(e)[:300]})
            return out
        except Exception as e:
            out["steps"].append({"op": "set_leverage", "error": str(e)[:300]})
            return out

        # 2) позиция + защита в одном ордере
        try:
            res = self.client.open_position(
                symbol, plan["side"], margin_usd=margin, leverage=lev,
                stop_loss=float(plan["stop_price"]),
                take_profit=float(plan["take_price"]),
                quantity=quantity)
            out["steps"].append({"op": "open_with_protection", "ok": True})
            out["order_id"] = (res or {}).get("orderId")
            out["filled_price"] = (res or {}).get("avgPrice")
            out["filled_qty"] = (res or {}).get("executedQty")
        except WaltError as e:
            out["steps"].append({"op": "open_with_protection",
                                 "error": str(e)[:300]})
            return out
        except Exception as e:
            out["steps"].append({"op": "open_with_protection",
                                 "error": str(e)[:300]})
            return out

        out["ok"] = all(s.get("ok") for s in out["steps"])
        return out

    def close_position(self, units=None, side=None, market_index=None,
                       symbol=None):
        """Закрыть позицию по рынку. -> dict результата."""
        sym = walt_symbol(symbol or market_index or "")
        if not sym:
            return {"ok": False, "error": "не указан символ"}
        try:
            res = self.client.close_position(
                sym, quantity=float(units) if units else None)
            return {"ok": True, "order_id": (res or {}).get("orderId"),
                    "symbol": sym}
        except WaltError as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}

    def set_leverage(self, leverage, margin_mode=1, symbol=None):
        """Установить плечо. margin_mode: 1 = isolated, 0 = cross."""
        sym = walt_symbol(symbol or "")
        if not sym:
            return {"ok": False, "error": "не указан символ"}
        try:
            self.client.set_leverage(sym, int(leverage))
            return {"ok": True, "symbol": sym, "leverage": int(leverage)}
        except WaltError as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}

    def set_protection(self, symbol, stop_loss=None, take_profit=None,
                       side=None, quantity=None):
        """Поставить/обновить защиту на открытой позиции."""
        sym = walt_symbol(symbol)
        try:
            res = self.client.set_algo_tpsl(sym, stop_loss=stop_loss,
                                            take_profit=take_profit,
                                            side=side, quantity=quantity)
            return {"ok": True, "symbol": sym, "result": res}
        except WaltError as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300], "symbol": sym}

    def positions(self):
        """Открытые позиции в формате слоя v5."""
        try:
            return self.client.positions()
        except Exception:
            return []

    def cancel_order(self, symbol, order_id):
        sym = walt_symbol(symbol)
        try:
            return {"ok": True, "result": self.client.cancel_order(sym, order_id)}
        except WaltError as e:
            return {"ok": False, "error": str(e)[:300]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
