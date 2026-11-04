
import sys, json
sys.path.insert(0,"/opt/azabot")
from walt_client import WaltClient, WaltError
c = WaltClient("dummy_key","dummy_secret")
print("UA:", c._headers()["User-Agent"])

# 1) публичные маршруты без ключа
try:
    info = c.exchange_info()
    syms = info.get("symbols") or []
    print("exchangeInfo: символов =", len(syms))
    names = [s.get("symbol") for s in syms][:12]
    print("примеры:", names)
    # есть ли BTCUSDT и его фильтры
    for s in syms:
        if s.get("symbol")=="BTCUSDT":
            print("BTCUSDT filters:", [f.get("filterType") for f in (s.get("filters") or [])])
            for f in (s.get("filters") or []):
                if f.get("filterType") in ("LOT_SIZE","MIN_NOTIONAL","PRICE_FILTER"):
                    print("   ", f.get("filterType"), f.get("stepSize") or f.get("notional") or f.get("tickSize"), f.get("minQty") or f.get("minNotional") or "")
except Exception as e:
    print("exchangeInfo FAIL:", type(e).__name__, e)

# 2) ticker и klines
for sym in ["BTCUSDT","ETHUSDT"]:
    try:
        px = c.ticker_price(sym); print(sym, "price =", px.get("price"))
    except Exception as e: print(sym,"ticker FAIL:", e)
try:
    k = c.klines("BTCUSDT","15m",3)
    print("klines BTCUSDT 15m:", len(k), "последняя:", k[-1] if k else None)
except Exception as e: print("klines FAIL:", e)

# 3) premiumIndex / fundingRate
try:
    pi = c.premium_index("BTCUSDT")
    print("premiumIndex: lastFundingRate =", pi.get("lastFundingRate"), "markPrice =", pi.get("markPrice"))
except Exception as e: print("premiumIndex FAIL:", e)
try:
    fr = c.funding_rate("BTCUSDT", 3)
    print("fundingRate:", [(x.get("fundingTime"), x.get("fundingRate")) for x in fr])
except Exception as e: print("fundingRate FAIL:", e)

# 4) подписанные маршруты с заведомо неверным ключом -> ожидаем -2015
try:
    c.account(); print("account: НЕОЖИДАННО прошёл")
except WaltError as e:
    print("account -> WaltError code =", e.code, "|", e.message[:120])
except Exception as e:
    print("account ->", type(e).__name__, str(e)[:200])
