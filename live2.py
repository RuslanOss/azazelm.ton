
import sys
sys.path.insert(0,"/opt/azabot")
from walt_client import WaltClient, WaltError
c = WaltClient("dummy_key","dummy_secret")

def try_(name, fn):
    try:
        r = fn()
        print("%-22s OK   %s" % (name, str(r)[:150]))
        return r
    except WaltError as e:
        print("%-22s ERR  code=%s | %s" % (name, e.code, e.message[:110]))
    except Exception as e:
        print("%-22s EXC  %s: %s" % (name, type(e).__name__, str(e)[:110]))
    return None

info = try_("exchangeInfo", c.exchange_info)
if info:
    syms = info.get("symbols") or []
    print("   символов:", len(syms), "первые:", [s.get("symbol") for s in syms[:8]])
    for s in syms:
        if s.get("symbol")=="BTCUSDT":
            for f in (s.get("filters") or []):
                if f.get("filterType") in ("LOT_SIZE","MIN_NOTIONAL","PRICE_FILTER"):
                    print("   BTCUSDT", f.get("filterType"), {k:v for k,v in f.items() if k!="filterType"})
try_("ticker_price BTCUSDT", lambda: c.ticker_price("BTCUSDT"))
try_("ticker_24h BTCUSDT", lambda: c.ticker_24h("BTCUSDT"))
k = try_("klines 15m", lambda: c.klines("BTCUSDT","15m",3))
if k: print("   последняя свеча:", k[-1])
try_("premiumIndex BTCUSDT", lambda: c.premium_index("BTCUSDT"))
try_("fundingRate BTCUSDT", lambda: c.funding_rate("BTCUSDT",3))
print("--- подписанные (ключ фиктивный, ожидаем -2015, а не -1102) ---")
try_("account", c.account)
try_("positions", c.positions)
try_("open_orders", c.open_orders)
