"""Integracionnyy test: bot prinimaet tol'ko podpisannye web_app_data."""
import hashlib, hmac, json, os, sys, time
from urllib.parse import urlencode
sys.path.insert(0, "/mnt/work/srv")
os.environ.setdefault("AZABOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("AIRTABLE_TOKEN", "patTEST")
os.environ.setdefault("AIRTABLE_BASE_ID", "appTEST")
import azazel_test_guard as _guard  # izolyaciya ot boevoy Airtable/Telegram
import bot
_guard.protect_bot(bot)

SENT = []
bot.send = lambda chat_id, text, buttons=None: (SENT.append((chat_id, text)) or {"ok": True})
bot.notify_admin = lambda *a, **k: None
_r = []
def check(name, cond, detail=""):
    _r.append((name, bool(cond)))
    print(("PASS: " if cond else "FAIL: ") + name + ((" :: " + str(detail)) if (detail and not cond) else ""))

TOKEN = bot.TOKEN
UID = 8459508879
def make(uid=UID, auth_date=None):
    user = json.dumps({"id": uid, "first_name": "T"}, separators=(",", ":"))
    p = {"auth_date": str(int(auth_date if auth_date is not None else time.time())),
         "query_id": "AAF_q", "user": user}
    cs = "\n".join("%s=%s" % (k, p[k]) for k in sorted(p))
    sec = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    p["hash"] = hmac.new(sec, cs.encode(), hashlib.sha256).hexdigest()
    return urlencode(p)
def run(data):
    SENT.clear()
    bot.handle_webapp_data(UID, UID, data)
    return SENT[0] if SENT else None

r = run(json.dumps({"cmd":"walt_key","key":"K","secret":"S"}))
check("walt_key without sig rejected", r is not None and ("trebuet" in (r[1] or "")), r[1] if r else None)
r = run(json.dumps({"cmd":"settings_save","params":{"tier":"krupnyy"}}))
check("settings_save without sig rejected", r is not None and "trebuet" in (r[1] or ""), r[1] if r else None)
r = run(json.dumps({"cmd":"status"}))
check("status without sig passes", r is not None and "trebuet" not in (r[1] or ""), r[1] if r else None)
r = run(json.dumps({"cmd":"walt_key","key":"K","secret":"S","init_data":make()}))
check("walt_key with sig not rejected", r is not None and "trebuet" not in (r[1] or ""), r[1] if r else None)
r = run(json.dumps({"cmd":"walt_key","key":"K","secret":"S","init_data":make(uid=111)}))
check("other uid sig rejected", r is not None and ("ne sovpal" in (r[1] or "")), r[1] if r else None)
bad = make(); bad = bad[:-1] + ("x" if bad[-1] != "x" else "y")
r = run(json.dumps({"cmd":"walt_key","key":"K","secret":"S","init_data":bad}))
check("broken sig rejected", r is not None and "ne sovpal" not in (r[1] or "") and "podpis" in (r[1] or "").lower(), r[1] if r else None)
r = run("just text")
check("plain text handled", r is not None, r)
r = run(json.dumps({"cmd":"status","initData":make()}))
check("initData alias accepted", r is not None and "ne sovpal" not in (r[1] or ""), r[1] if r else None)
r = run(json.dumps({"cmd":"status","init_data":make(auth_date=time.time()-7200)}))
check("expired sig rejected", r is not None and "ustarel" in (r[1] or ""), r[1] if r else None)
pp = sum(1 for _, ok in _r if ok); ff = len(_r)-pp
print("PASS: %d" % pp); print("FAIL: %d" % ff)
sys.exit(1 if ff else 0)
