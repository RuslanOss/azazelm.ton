# -*- coding: utf-8 -*-
"""
Walt API client - USDⓈ-M perps через bot.mywellat.com/fapi/v1.

Схема подписи - Binance-style HMAC-SHA256 (docs: wellat.readme.io/docs/authentication):
  message   = query string + request body в том порядке, в котором отправлены,
              БЕЗ параметра signature
  signature = HMAC-SHA256(secret, message), lowercase hex
  GET  -> параметры в query string
  POST -> параметры в body, application/x-www-form-urlencoded

Важные детали, из-за которых биржа отвечает -2015:
  - параметры НЕ сортируются и НЕ перекодируются после подписи
  - urlencode ровно один раз, тем же энкодером, что и отправка
  - timestamp в миллисекундах, recvWindow <= 30000
  - при расхождении часов -1021: читаем серверное время и смещаем offset

Торговые маршруты /fapi/v1 (фьючерсы), спот - /api/v3. Ключ привязан к одной
стратегии (futures или spot); ключ спота на фьючерсном маршруте даёт -2010.

Расширения Wellat для входа одной заявкой:
  takeProfitPrice, stopLossPrice, leverage - расширения к POST /fapi/v1/order.
"""
import hashlib
import hmac
import json
import time
import uuid
import urllib.parse
import urllib.request
import urllib.error

# ---------- кэш смещения часов (на уровне процесса) ----------
# Серверные часы Wellat спешат примерно на 1.3 с. Клиент создаётся на каждый
# прогон цикла, а цикл идёт каждые 15 минут, поэтому замер часов кэшируем:
# один сетевой запрос на процесс вместо запроса на каждый клиент.
_TIME_OFFSET_CACHE = {}   # base_url -> (offset_ms, saved_at)
_TIME_CACHE_TTL_S = 3600


def _cache_get(base_url, now=None):
    """Смещение из кэша, если оно свежее. Иначе None."""
    item = _TIME_OFFSET_CACHE.get(base_url)
    if not item:
        return None
    off, saved = item
    now = time.time() if now is None else now
    if now - saved > _TIME_CACHE_TTL_S:
        return None
    return off


def _cache_set(base_url, offset_ms, now=None):
    now = time.time() if now is None else now
    _TIME_OFFSET_CACHE[base_url] = (int(offset_ms), now)


def _new_client_order_id(prefix="az"):
    # Unikalnyy newClientOrderId: -1001 voznikaet, kogda birzha
    # uje videla takoy id. Kazhdyy novy zapros poluchaet svoy id.
    return "%s-%s" % (prefix, uuid.uuid4().hex[:26])


class WaltError(Exception):
    """Ошибка Walt API. code/msg - как в ответе биржи."""

    def __init__(self, message, code=None, status=None, raw=None):
        Exception.__init__(self, message)
        self.message = message
        self.code = code
        self.status = status
        self.raw = raw

    def __str__(self):
        if self.code is not None:
            return "%s (code=%s, http=%s)" % (self.message, self.code, self.status)
        return self.message


class WaltClient(object):
    def __init__(self, api_key, api_secret, base_url="https://bot.mywellat.com",
                 family="futures", recv_window=15000, timeout=25, log=None,
                 user_agent="AzazelTrader/1.0", sync_time=True):
        if not api_key or not api_secret:
            raise ValueError("нужен api_key и api_secret")
        self.api_key = api_key.strip()
        self.secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.family = family  # "futures" -> /fapi/v1, "spot" -> /api/v3
        self.recv_window = min(int(recv_window), 30000)
        self.timeout = timeout
        self.log = log
        self.user_agent = user_agent
        self._time_offset_ms = 0
        self._resynced = False
        if sync_time:
            # Не роняем создание клиента, если сеть недоступна: смещение
            # часов - улучшение точности, а не условие работы.
            self.sync_time_offset()

    # ---------- инфраструктура ----------

    @property
    def _prefix(self):
        return "/fapi/v1" if self.family == "futures" else "/api/v3"

    def _now_ms(self):
        return int(time.time() * 1000) + self._time_offset_ms

    def _encode(self, params):
        """Ровно один urlencode, порядок сохраняется."""
        return urllib.parse.urlencode(params)

    def _signed_params(self, params):
        p = dict(params or {})
        p["timestamp"] = self._now_ms()
        p["recvWindow"] = self.recv_window
        return p

    def _sign(self, payload):
        return hmac.new(self.secret.encode("utf-8"),
                        payload.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _headers(self):
        # Cloudflare (error 1010) блокирует дефолтный User-Agent python-urllib,
        # поэтому отдаем явный идентификатор клиента.
        return {"X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": self.user_agent}

    def _request(self, method, path, params=None, signed=True):
        url = self.base_url + path
        body = None
        if method == "GET" or method == "DELETE":
            # ВАЖНО: query собирается ВСЕГДА, даже при пустых params.
            # Раньше здесь стояло "if params:", и маршруты без параметров
            # (account, positionRisk, openOrders) уходили без timestamp ->
            # биржа отвечала -1102 "Mandatory parameter 'timestamp' was not sent".
            p = self._signed_params(params) if signed else (params or {})
            qs = self._encode(p)
            if signed:
                qs = qs + "&signature=" + self._sign(qs)
            if qs:
                url = url + "?" + qs
        else:
            p = self._signed_params(params) if signed else (params or {})
            payload = self._encode(p)
            if signed:
                payload = payload + "&signature=" + self._sign(payload)
            body = payload.encode("utf-8")
        req = urllib.request.Request(url, data=body, method=method,
                                     headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace") if e.fp else ""
            code, msg = self._parse(raw)
            if code == -1021 and not getattr(self, "_resynced", False):
                # расхождение часов: сдвигаем offset по серверному времени
                # и повторяем запрос ровно один раз
                self._resynced = True
                self._sync_time()
                return self._request(method, path, params, signed)
            # -1001: birzha uje videla takoy newClientOrderId.
            # Reshёm novym id i povtorim rovno odin raz.
            if code == -1001 and method == "POST" and params:
                p2 = dict(params)
                p2["newClientOrderId"] = _new_client_order_id()
                if self.log:
                    self.log.info("walt: -1001, retry newClientOrderId=%s", p2["newClientOrderId"])
                return self._request(method, path, p2, signed)
            raise WaltError(msg, code, e.code, raw)
        except urllib.error.URLError as e:
            raise WaltError("сеть недоступна: %s" % e.reason, None, None, None)
        return self._decode(raw)

    def _decode(self, raw):
        """Разбор успешного ответа: вернуть данные, а кортеж (code,msg)."""
        code, msg = self._parse(raw)
        if code is not None:
            raise WaltError(msg, code, None, raw)
        if raw is None or raw == "":
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    @staticmethod
    def _parse(raw):
        if not raw:
            return None, "пустой ответ"
        try:
            data = json.loads(raw)
        except ValueError:
            return None, raw[:300]
        if isinstance(data, dict) and "code" in data and data.get("code") not in (0, None):
            return data.get("code"), data.get("msg") or json.dumps(data, ensure_ascii=False)[:300]
        return None, raw

    def _sync_time(self):
        """Считать серверное время и выставить offset (лечит -1021)."""
        try:
            req = urllib.request.Request(self.base_url + self._prefix + "/time",
                                         headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            server = int(data.get("serverTime") or 0)
            if server:
                self._time_offset_ms = server - int(time.time() * 1000)
                if self.log:
                    self.log.info("walt: server time offset = %d ms", self._time_offset_ms)
        except Exception as e:
            if self.log:
                self.log.warning("walt: не удалось синхронизировать время: %s", e)

    # ---------- публичные данные ----------

    def time(self):
        return self._request("GET", self._prefix + "/time", signed=False)

    def sync_time_offset(self, force=False):
        """Выставить offset по серверным часам. Никогда не бросает исключений.

        Смещение кэшируется на уровне процесса (base_url -> offset, TTL 1 час):
        клиент создаётся на каждый прогон цикла, а цикл идёт каждые 15 минут,
        поэтому одного замера на процесс достаточно.

        Возвращает offset в мс (или None, если замер не удался).
        """
        cached = None if force else _cache_get(self.base_url)
        if cached is not None:
            self._time_offset_ms = cached
            self._resynced = True
            return cached
        try:
            _srv, off = self.server_time(sync=False)
        except Exception as e:
            if self.log:
                self.log.warning("walt: не удалось синхронизировать время: %s", e)
            return None
        self._time_offset_ms = off
        self._resynced = True
        _cache_set(self.base_url, off)
        if self.log:
            self.log.info("walt: server time offset = %d ms", off)
        return off

    def server_time(self, sync=False):
        """Серверное время биржи в мс. -> (server_ms, offset_ms)

        offset_ms = server_ms - локальное_время_на_момент_запроса.
        Именно это смещение клиент подставляет в timestamp, поэтому
        расхождение часов видно заранее, а не по факту отказа -1021.

        sync=True - сразу выставить offset (то же, что делает _sync_time
        при -1021, но без ожидания ошибки).
        """
        t0 = int(time.time() * 1000)
        raw = self._request("GET", self._prefix + "/time", signed=False)
        server = 0
        if isinstance(raw, dict):
            server = int(raw.get("serverTime") or 0)
        elif isinstance(raw, (int, float)):
            server = int(raw)
        if not server:
            raise WaltError("сервер не вернул serverTime", None, None, None)
        # задержка сети делим пополам: сервер отдал время где-то между
        # t0 и t1, значит истина - посередине
        t1 = int(time.time() * 1000)
        server_mid = server + (t1 - t0) // 2
        offset = server_mid - t0
        if sync:
            self._time_offset_ms = offset
            self._resynced = True
            if self.log:
                self.log.info("walt: server time offset = %d ms (sync)", offset)
        return server_mid, offset

    def exchange_info(self):
        return self._request("GET", self._prefix + "/exchangeInfo", signed=False)

    def ticker_price(self, symbol):
        return self._request("GET", self._prefix + "/ticker/price",
                             {"symbol": symbol}, signed=False)

    def ticker_24h(self, symbol=None):
        p = {"symbol": symbol} if symbol else {}
        return self._request("GET", self._prefix + "/ticker/24hr", p, signed=False)

    def klines(self, symbol, interval="15m", limit=200):
        """-> список свечей [{"t","o","h","l","c","v"}, ...]"""
        raw = self._request("GET", self._prefix + "/klines",
                             {"symbol": symbol, "interval": interval,
                              "limit": min(int(limit), 1000)}, signed=False)
        out = []
        for k in (raw or []):
            out.append({"t": k[0], "o": float(k[1]), "h": float(k[2]),
                        "l": float(k[3]), "c": float(k[4]), "v": float(k[5]),
                        "T": k[6]})
        return out

    def premium_index(self, symbol):
        return self._request("GET", self._prefix + "/premiumIndex",
                             {"symbol": symbol}, signed=False)

    def funding_rate(self, symbol, limit=10):
        return self._request("GET", self._prefix + "/fundingRate",
                             {"symbol": symbol, "limit": min(int(limit), 1000)},
                             signed=False)

    # ---------- аккаунт ----------

    def account(self):
        return self._request("GET", "/fapi/v3/account")

    def positions(self):
        """-> [{symbol, positionAmt, entryPrice, leverage, unRealizedProfit, ...}]"""
        raw = self._request("GET", "/fapi/v3/positionRisk")
        out = []
        for p in (raw or []):
            amt = float(p.get("positionAmt") or 0)
            if abs(amt) < 1e-12:
                continue
            out.append({
                "symbol": p.get("symbol"),
                "side": "long" if amt > 0 else "short",
                "size": abs(amt),
                "entry": float(p.get("entryPrice") or 0),
                "leverage": int(p.get("leverage") or 1),
                "mark": float(p.get("markPrice") or 0),
                "unrealized": float(p.get("unRealizedProfit") or 0),
                "liquidation": float(p.get("liquidationPrice") or 0),
            })
        return out

    def open_orders(self, symbol=None):
        p = {"symbol": symbol} if symbol else {}
        return self._request("GET", self._prefix + "/openOrders", p)

    def set_leverage(self, symbol, leverage):
        return self._request("POST", self._prefix + "/leverage",
                             {"symbol": symbol, "leverage": int(leverage)})

    def set_margin_type(self, symbol, margin_type="ISOLATED"):
        return self._request("POST", self._prefix + "/marginType",
                             {"symbol": symbol, "marginType": margin_type})

    # ---------- торговля ----------

    def open_position(self, symbol, side, margin_usd, leverage,
                      stop_loss=None, take_profit=None, quantity=None,
                      reduce_only=False, position_side=None):
        """Открыть позицию. quantity считается из маржи и плеча, если не задан.

        size = margin_usd * leverage (notional) -> quantity = notional / price
        Возвращает ответ биржи (dict).
        """
        if side not in ("long", "short"):
            raise ValueError("side: long или short")
        params = {"symbol": symbol, "side": "BUY" if side == "long" else "SELL",
                  "type": "MARKET", "leverage": int(leverage)}
        # Unikalnyy id zakaza: -1001 voznikaet, kogda birzha uje videla takoy id.
        params["newClientOrderId"] = _new_client_order_id()
        if quantity is None:
            price = self._last_price(symbol)
            if not price:
                raise WaltError("не удалось получить цену %s" % symbol)
            notional = float(margin_usd) * float(leverage)
            quantity = notional / price
        params["quantity"] = self._round_qty(symbol, quantity)
        if stop_loss:
            params["stopLossPrice"] = float(stop_loss)
        if take_profit:
            params["takeProfitPrice"] = float(take_profit)
        if reduce_only:
            params["reduceOnly"] = "true"
        if position_side:
            params["positionSide"] = position_side
        return self._request("POST", self._prefix + "/order", params)

    def close_position(self, symbol, quantity=None, position_side=None):
        """Закрыть позицию по рынку (reduceOnly)."""
        params = {"symbol": symbol, "side": "SELL", "type": "MARKET",
                  "reduceOnly": "true"}
        if quantity is None:
            q = 0.0
            for p in self.positions():
                if p["symbol"] == symbol:
                    q = p["size"]
                    if position_side is None:
                        position_side = "LONG" if p["side"] == "long" else "SHORT"
            if not q:
                raise WaltError("нет позиции по %s" % symbol)
            params["quantity"] = self._round_qty(symbol, q)
        else:
            params["quantity"] = self._round_qty(symbol, quantity)
        if position_side:
            params["positionSide"] = position_side
        return self._request("POST", self._prefix + "/order", params)

    def cancel_order(self, symbol, order_id):
        return self._request("DELETE", self._prefix + "/order",
                             {"symbol": symbol, "orderId": int(order_id)})

    def set_algo_tpsl(self, symbol, stop_loss=None, take_profit=None,
                      side=None, quantity=None):
        """Отдельные TP/SL-ноги через algoOrder (если не смогли сразу с ордером)."""
        params = {"symbol": symbol}
        if stop_loss:
            params["stopLossPrice"] = float(stop_loss)
        if take_profit:
            params["takeProfitPrice"] = float(take_profit)
        if side:
            params["side"] = "BUY" if side == "short" else "SELL"
        if quantity:
            params["quantity"] = self._round_qty(symbol, quantity)
        return self._request("POST", self._prefix + "/algoOrder", params)

    # ---------- вспомогательное ----------

    _price_cache = {}

    def _last_price(self, symbol):
        d = self.ticker_price(symbol)
        try:
            px = float(d["price"])
            self._price_cache[symbol] = px
            return px
        except Exception:
            return self._price_cache.get(symbol)

    def _round_qty(self, symbol, qty):
        """Округление quantity под фильтры биржи из exchangeInfo."""
        try:
            info = self.exchange_info()
            for s in (info.get("symbols") or []):
                if s.get("symbol") != symbol:
                    continue
                for f in (s.get("filters") or []):
                    if f.get("filterType") == "LOT_SIZE":
                        step = float(f.get("stepSize") or 0)
                        if step > 0:
                            import math
                            return round(math.floor(qty / step) * step, 10)
        except Exception:
            pass
        return round(float(qty), 8)

    def check(self):
        """Проверка ключа: account + позиции. -> dict с балансом и позициями."""
        acc = self.account()
        bal = {}
        for a in (acc.get("assets") or []):
            bal[a.get("asset")] = {
                "total": float(a.get("walletBalance") or 0),
                "free": float(a.get("availableBalance") or 0),
                "used": float(a.get("initialMargin") or 0),
                "pnl": float(a.get("unrealizedProfit") or 0),
            }
        return {"balance": bal,
                "positions": self.positions(),
                "can_trade": acc.get("canTrade")}


def from_env(log=None, path="/opt/azabot/.env"):
    """Собрать клиент из переменных окружения:
       WALT_API_KEY / WALT_API_SECRET (или AZAZEL_WALT_KEY / AZAZEL_WALT_SECRET).
    """
    import os
    key = os.environ.get("WALT_API_KEY") or os.environ.get("AZAZEL_WALT_KEY") or ""
    sec = os.environ.get("WALT_API_SECRET") or os.environ.get("AZAZEL_WALT_SECRET") or ""
    base = os.environ.get("WALT_BASE_URL") or "https://bot.mywellat.com"
    fam = os.environ.get("WALT_FAMILY") or "futures"
    if not key or not sec:
        return None
    return WaltClient(key, sec, base_url=base, family=fam, log=log)
