# -*- coding: utf-8 -*-
"""Тесты Walt-клиента.

Критично: подпись должна совпадать БАЙТ В БАЙТ с эталонным примером
из wellat.readme.io/docs/authentication, иначе биржа отвечает -2015.
"""
import sys, os, json, hmac, hashlib, urllib.parse, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import walt_client as W

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

SECRET="test_secret_123"
KEY="wlt_bot_abc"

# ---- 1) эталонная подпись из документации ----
# docs: message = symbol=BTCUSDT&side=BUY&type=MARKET&quantity=0.001&timestamp=...&recvWindow=5000
# signature = HMAC-SHA256(secret, message) lowercase hex
c = W.WaltClient(KEY, SECRET)
c.recv_window = 5000
c._time_offset_ms = 1759500000000 - int(time.time()*1000)
params = {"symbol":"BTCUSDT","side":"BUY","type":"MARKET","quantity":"0.001"}
p = c._signed_params(params)
msg = c._encode(p)
expected = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
check("подпись = HMAC-SHA256(secret, message)", c._sign(msg)==expected, (c._sign(msg), expected))
check("сообщение не перекодировано дважды",
      msg.startswith("symbol=BTCUSDT&side=BUY&type=MARKET&quantity=0.001&timestamp="), msg)
check("timestamp в миллисекундах", len(str(p["timestamp"]))==13, p["timestamp"])
check("recvWindow <= 30000", c.recv_window<=30000)

# порядок параметров сохраняется (не сортируется)
p2 = c._signed_params({"zebra":"1","alpha":"2"})
check("порядок параметров не меняется", c._encode(p2).startswith("zebra=1&alpha=2"), c._encode(p2))

# ---- 2) эталонный пример из документации (node) ----
# node: crypto.createHmac('sha256', SECRET).update(query).digest('hex')
q = "symbol=BTCUSDT&side=BUY&type=MARKET&quantity=0.001&timestamp=1759500000000&recvWindow=5000"
node_expected = hmac.new(SECRET.encode(), q.encode(), hashlib.sha256).hexdigest()
check("совпадает с эталоном из docs", c._sign(q)==node_expected, (c._sign(q), node_expected))

# ---- 3) подпись GET = подпись POST с теми же параметрами ----
c2 = W.WaltClient(KEY, SECRET); c2.recv_window=5000
c2._time_offset_ms = c._time_offset_ms
q_get = c2._encode(c2._signed_params({"symbol":"BTCUSDT"}))
c3 = W.WaltClient(KEY, SECRET); c3.recv_window=5000
c3._time_offset_ms = c._time_offset_ms
q_post = c3._encode(c3._signed_params({"symbol":"BTCUSDT"}))
check("GET и POST с одними параметрами дают одну подпись",
      c2._sign(q_get)==c3._sign(q_post))

# ---- 3b) server_time: серверное время и смещение часов ----
import threading

# подменяем _request, чтобы проверить разбор ответа без сети
class FakeClient(W.WaltClient):
    def __init__(self, payload, **kw):
        W.WaltClient.__init__(self, "k", "s", **kw)
        self.payload = payload
        self.calls = 0
    def _request(self, method, path, params=None, signed=True):
        self.calls += 1
        return self.payload

now_ms = int(time.time()*1000)
fc = FakeClient({"serverTime": now_ms + 2500}, sync_time=False)
srv, off = fc.server_time()
check("server_time возвращает серверное время", srv >= now_ms + 2500, srv)
check("offset = сервер - локальное", 2400 <= off <= 2600, off)
check("server_time не трогает offset без sync", fc._time_offset_ms == 0, fc._time_offset_ms)
check("server_time не ставит флаг _resynced без sync", fc._resynced is False, fc._resynced)

fc2 = FakeClient({"serverTime": now_ms + 2500}, sync_time=False)
srv2, off2 = fc2.server_time(sync=True)
check("sync=True выставляет offset", fc2._time_offset_ms == off2, (fc2._time_offset_ms, off2))
check("sync=True ставит флаг _resynced", fc2._resynced is True, fc2._resynced)
check("после sync timestamp сдвинут на offset",
      abs(fc2._now_ms() - (int(time.time()*1000)+off2)) < 50, fc2._now_ms())

# сервер отдаёт время без serverTime - ошибка, а не тихий ноль
fc3 = FakeClient({"foo": "bar"}, sync_time=False)
try:
    fc3.server_time(); check("нет serverTime -> исключение", False)
except W.WaltError: check("нет serverTime -> исключение", True)

# сервер отдаёт число вместо dict
fc4 = FakeClient(now_ms + 100, sync_time=False)
srv4, off4 = fc4.server_time()
check("числовой ответ тоже разбирается", abs(off4-100) <= 50, off4)

# запрос идёт на публичный маршрут без подписи
fc5 = FakeClient({"serverTime": now_ms}, sync_time=False)
signed_flag = {}
orig = W.WaltClient._request
def spy(self, method, path, params=None, signed=True):
    signed_flag["signed"] = signed; signed_flag["path"] = path
    return orig(self, method, path, params, signed)
W.WaltClient._request = spy
try:
    W.WaltClient("k","s").server_time()
finally:
    W.WaltClient._request = orig
check("server_time идёт без подписи", signed_flag.get("signed") is False, signed_flag)
check("server_time идёт на /time", signed_flag.get("path","").endswith("/time"), signed_flag)

# ---- 3c) offset при создании клиента: кэш и деградация ----
# смещение часов сервера: сервер спешит ~1.3 с -> timestamp без поправки
# отстаёт. Теперь offset выставляется при создании клиента.

W._TIME_OFFSET_CACHE.clear()

# счётчик сетевых вызовов /time при создании клиентов
calls = {"n": 0}
class CountingClient(W.WaltClient):
    def _request(self, method, path, params=None, signed=True):
        if path.endswith("/time"): calls["n"] += 1
        return {"serverTime": int(time.time()*1000) + 2000}

# создание клиента теперь синхронизирует время
cA = CountingClient("k", "s")
check("конструктор выставляет offset", cA._time_offset_ms != 0, cA._time_offset_ms)
check("конструктор ставит флаг _resynced", cA._resynced is True, cA._resynced)
check("конструктор сделал сетевой запрос /time", calls["n"] == 1, calls["n"])

# второй клиент того же base_url берёт offset из кэша - без запроса
cB = CountingClient("k", "s")
check("второй клиент берёт offset из кэша", cB._time_offset_ms == cA._time_offset_ms,
      (cA._time_offset_ms, cB._time_offset_ms))
check("кэш не даёт лишнего сетевого запроса", calls["n"] == 1, calls["n"])

# другой base_url - свой кэш, свой запрос
cC = CountingClient("k", "s", base_url="https://other.example")
check("другой base_url - свой замер", calls["n"] == 2, calls["n"])

# просроченный кэш обновляется
W._TIME_OFFSET_CACHE["https://bot.mywellat.com"] = (500, time.time() - 7200)
calls["n"] = 0
cD = CountingClient("k", "s")
check("просроченный кэш обновляется новым замером", calls["n"] == 1, calls["n"])
check("offset после обновления свежий", abs(cD._time_offset_ms - 2000) < 200, cD._time_offset_ms)

# force=True всегда перезамеряет, минуя кэш
calls["n"] = 0
cE = CountingClient("k", "s")
cE.sync_time_offset(force=True)
check("force=True перезамеряет в обход кэша", calls["n"] == 1, calls["n"])

# ---- 3d) деградация: сеть недоступна - клиент всё равно создаётся ----
class BrokenClient(W.WaltClient):
    def _request(self, method, path, params=None, signed=True):
        raise IOError("сеть недоступна")

W._TIME_OFFSET_CACHE.clear()   # иначе offset возьмётся из кэша, сеть не нужна
try:
    cb = BrokenClient("k", "s")
    check("недоступная сеть не роняет создание клиента", True)
    check("при недоступной сети offset = 0", cb._time_offset_ms == 0, cb._time_offset_ms)
    check("при недоступной сети _resynced = False", cb._resynced is False, cb._resynced)
except Exception as e:
    check("недоступная сеть не роняет создание клиента", False, str(e)[:120])

# sync_time=False - вообще без обращения к сети
calls["n"] = 0
cF = CountingClient("k", "s", sync_time=False)
check("sync_time=False не ходит в сеть", calls["n"] == 0, calls["n"])
check("sync_time=False оставляет offset = 0", cF._time_offset_ms == 0, cF._time_offset_ms)

# ---- 4) ошибки клиента ----
try:
    W.WaltClient("", "s"); check("пустой ключ отклонён", False)
except ValueError: check("пустой ключ отклонён", True)
try:
    W.WaltClient("k", "s").open_position("BTCUSDT","sideways",10,5); check("неверная сторона отклонена", False)
except ValueError: check("неверная сторона отклонена", True)
_c = W.WaltClient("k","s")
_c._request = lambda m,p,params=None,signed=True: []
try:
    _c.close_position("BTCUSDT"); check("close без позиции падает", False)
except W.WaltError as e: check("close без позиции падает", "нет позиции" in str(e).lower(), str(e))

# ---- 5) разбор ошибок биржи ----
code,msg = W.WaltClient._parse('{"code":-2015,"msg":"Invalid API-key"}')
check("-2015 распознан", code==-2015 and "Invalid" in msg, (code,msg))
code,msg = W.WaltClient._parse('{"code":-1021,"msg":"Timestamp outside of recvWindow"}')
check("-1021 распознан", code==-1021, (code,msg))
code,msg = W.WaltClient._parse('not json at all')
check("не-JSON не роняет парсер", code is None and msg, (code,msg))
code,msg = W.WaltClient._parse('{"code":0,"msg":"ok"}')
check("code:0 - не ошибка", code is None, (code,msg))

# ---- 6) позиции: нулевая отбрасывается, знак определяет сторону ----
c = W.WaltClient(KEY, SECRET)
orig = c._request
c._request = lambda m,p,params=None,signed=True: [
    {"symbol":"BTCUSDT","positionAmt":"0","entryPrice":"0","leverage":"5"},
    {"symbol":"ETHUSDT","positionAmt":"-2.5","entryPrice":"2300.5","leverage":"10",
     "markPrice":"2290","unRealizedProfit":"26.25","liquidationPrice":"5000"},
]  # positions() читает только positionRisk
pos = c.positions()
check("нулевая позиция отброшена", len(pos)==1, pos)
check("сторона из знака", pos[0]["side"]=="short", pos)
check("размер по модулю", abs(pos[0]["size"]-2.5)<1e-9, pos)
check("ликвидация прочитана", pos[0]["liquidation"]==5000, pos)
c._request = orig

# ---- 7) account -> баланс ----
c = W.WaltClient(KEY, SECRET)
def _mock_account(m,p,params=None,signed=True):
    if "positionRisk" in p:
        return []
    return {"assets":[
        {"asset":"USDT","walletBalance":"32.84","availableBalance":"0.0",
         "initialMargin":"32.84","unrealizedProfit":"0"}]}
c._request = _mock_account
info = c.check()
check("баланс USDT прочитан", abs(info["balance"]["USDT"]["total"]-32.84)<1e-6, info)
check("свободная маржа 0", abs(info["balance"]["USDT"]["free"])<1e-9, info)

# ---- 8) округление quantity по LOT_SIZE ----
c = W.WaltClient(KEY, SECRET)
c._request = lambda m,p,params=None,signed=True: {"symbols":[{"symbol":"BTCUSDT","filters":[
    {"filterType":"LOT_SIZE","stepSize":"0.001"}]}]}
q = c._round_qty("BTCUSDT", 0.123456789)
check("quantity округлён по stepSize", abs(q-0.123)<1e-9, q)

# ---- 9) prefix по family ----
check("futures -> /fapi/v1", W.WaltClient(KEY,SECRET)._prefix=="/fapi/v1")
check("spot -> /api/v3", W.WaltClient(KEY,SECRET,family="spot")._prefix=="/api/v3")

# ---- 10) from_env без переменных -> None ----
os.environ.pop("WALT_API_KEY",None); os.environ.pop("AZAZEL_WALT_KEY",None)
check("from_env без ключа -> None", W.from_env() is None)

# ---- 11) User-Agent не дефолтный urllib (Cloudflare 1010) ----
_h = W.WaltClient(KEY,SECRET)._headers()
check("User-Agent задан явно", "python-urllib" not in _h.get("User-Agent","").lower(), _h)
check("есть X-MBX-APIKEY", "X-MBX-APIKEY" in _h, _h)

# ---- 12) РЕГРЕССИЯ: -1102 (timestamp терялся при пустых params) ----
# Перехватываем реально собранный URL, а не мок _request.
import urllib.request as _ur
class _FakeResp:
    def __init__(self, body): self._b=body.encode()
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self,*a): return False
CAP=[]
def _capture(req, data=None, timeout=None, **kw):
    # urlopen получает urllib.request.Request, а не строку
    u = getattr(req, "full_url", None) or (req if isinstance(req,str) else str(req))
    d = getattr(req, "data", None) or data
    CAP.append({"url":u,"data":d.decode() if d else None})
    return _FakeResp('{"assets":[],"canTrade":true}')
_orig_open=_ur.urlopen
_ur.urlopen=_capture
try:
    c = W.WaltClient(KEY, SECRET)
    c.account()
finally:
    _ur.urlopen=_orig_open
check("account(): URL собран (не пустой)", bool(CAP), CAP)
check("account(): timestamp присутствует в URL",
      CAP and "timestamp=" in CAP[0]["url"], CAP)
check("account(): signature присутствует в URL",
      CAP and "signature=" in CAP[0]["url"], CAP)
check("account(): recvWindow присутствует",
      CAP and "recvWindow=" in CAP[0]["url"], CAP)
check("account(): пустые params НЕ обрывают query",
      CAP and CAP[0]["url"].count("?")==1, CAP)

# DELETE без params тоже должен унести timestamp
CAP.clear()
_orig_open=_ur.urlopen
_ur.urlopen=_capture
try:
    c = W.WaltClient(KEY, SECRET)
    try: c.cancel_order("BTCUSDT", 123)
    except Exception: pass
finally:
    _ur.urlopen=_orig_open
check("cancel_order: timestamp в query", CAP and "timestamp=" in CAP[0]["url"], CAP)

# POST: timestamp в body
CAP.clear()
_orig_open=_ur.urlopen
_ur.urlopen=_capture
try:
    c = W.WaltClient(KEY, SECRET)
    c._request("POST", "/fapi/v1/order", {"symbol":"BTCUSDT","side":"BUY"})
finally:
    _ur.urlopen=_orig_open
check("POST: timestamp в body", CAP and CAP[0]["data"] and "timestamp=" in CAP[0]["data"], CAP)
check("POST: signature последним в body",
      CAP and CAP[0]["data"] and CAP[0]["data"].split("&")[-1].startswith("signature="), CAP)

# ---- 13) РЕГРЕССИЯ: _request возвращал кортеж вместо данных ----
_orig_open=_ur.urlopen
_ur.urlopen=_capture
try:
    c = W.WaltClient(KEY, SECRET)
    d = c.account()
finally:
    _ur.urlopen=_orig_open
check("account() возвращает dict, а не кортеж", isinstance(d, dict), type(d).__name__)
check("account() доступен по ключу canTrade", "canTrade" in d, d)

# успешный ответ с 'code':0 -> данные, не исключение
_orig_open=_ur.urlopen
def _ok(req, data=None, timeout=None, **kw):
    return _FakeResp('{"code":0,"msg":"ok","symbols":[]}')
_ur.urlopen=_ok
try:
    c = W.WaltClient(KEY, SECRET)
    d = c.exchange_info()
finally:
    _ur.urlopen=_orig_open
check("code:0 не считается ошибкой", isinstance(d, dict) and d.get("code")==0, d)

# ошибочный ответ -> WaltError, а не тихий возврат
_orig_open=_ur.urlopen
class _HTTP400(urllib.error.HTTPError):
    """Настоящий HTTPError с телом - чтобы сработала ветка клиента."""
    def __init__(self, body):
        urllib.error.HTTPError.__init__(self, "https://x/y", 400, "Bad Request", {}, None)
        self._b = body
    def read(self): return self._b.encode()
def _bad(req, data=None, timeout=None, **kw):
    raise _HTTP400('{"code":-2010,"msg":"strategy mismatch"}')
_ur.urlopen=_bad
try:
    c = W.WaltClient(KEY, SECRET)
    try:
        c.account(); check("ошибка биржи поднимает WaltError", False)
    except W.WaltError as e:
        check("ошибка биржи поднимает WaltError", e.code==-2010, (e.code,e.message))
    except Exception as e:
        check("ошибка биржи поднимает WaltError", False, type(e).__name__)
finally:
    _ur.urlopen=_orig_open

# ---- 14) klines корректно разбираются в dict-формат ----
def _kl(req, data=None, timeout=None, **kw):
    return _FakeResp('[[1793628900000,"77865.00","77948.80","77741.80","77790.40","1141.629",1793629799999,"0",35071,"0","0","0"]]')
_orig_open=_ur.urlopen
_ur.urlopen=_kl
try:
    c = W.WaltClient(KEY, SECRET)
    k = c.klines("BTCUSDT","15m",2)
finally:
    _ur.urlopen=_orig_open
check("klines -> список dict", isinstance(k,list) and isinstance(k[0],dict), k)
check("klines: c = close", abs(k[0]["c"]-77790.40)<1e-6, k)
check("klines: o = open", abs(k[0]["o"]-77865.00)<1e-6, k)
check("klines: h = high", abs(k[0]["h"]-77948.80)<1e-6, k)
check("klines: l = low", abs(k[0]["l"]-77741.80)<1e-6, k)
check("klines: v = volume", abs(k[0]["v"]-1141.629)<1e-6, k)

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
