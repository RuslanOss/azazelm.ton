"""Testy proverki initData."""
import hashlib, hmac, json, sys, time
from urllib.parse import urlencode
sys.path.insert(0, "/mnt/work/srv")
import azazel_initdata as A

TOKEN = "123456:TESTTOKEN"
UID = 8459508879
_r = []
def check(name, cond, detail=""):
    _r.append((name, bool(cond)))
    print(("PASS: " if cond else "FAIL: ") + name + ((" :: " + str(detail)) if (detail and not cond) else ""))

def make(token=TOKEN, uid=UID, auth_date=None, break_hash=False):
    user = json.dumps({"id": uid, "first_name": "Test"}, separators=(",", ":"))
    p = {"auth_date": str(int(auth_date if auth_date is not None else time.time())),
         "query_id": "AAF_testquery", "user": user}
    cs = "\n".join("%s=%s" % (k, p[k]) for k in sorted(p))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(sec, cs.encode(), hashlib.sha256).hexdigest()
    if break_hash:
        h = ("0" if h[0] != "0" else "1") + h[1:]
    p["hash"] = h
    return urlencode(p)

ok, uid, r = A.verify(make(), TOKEN); check("valid accepted", ok, r)
check("uid from signature", uid == UID, uid)
ok, _, r = A.verify(make(break_hash=True), TOKEN); check("broken hash rejected", not ok, r)
ok, _, r = A.verify(make(token="999:WRONG"), TOKEN); check("wrong token rejected", not ok, r)
alice = make(uid=111)
ok, uid, r = A.verify(alice, TOKEN); check("other uid sig valid", ok, r)
check("uid is own only", uid == 111, uid)
al, _, r = A.authorize("walt_key", alice, TOKEN, event_uid=UID)
check("other uid rejected", not al, r)
check("reason mentions mismatch", "ne sovpal" in r, r)
al, _, r = A.authorize("walt_key", alice, TOKEN, event_uid=111)
check("own uid + own sig allowed", al, r)
for c in ("walt_key", "settings_save"):
    al, _, r = A.authorize(c, "", TOKEN, event_uid=UID)
    check("'" + c + "' without sig rejected", not al, r)
    check("'" + c + "' explains", "trebuet" in r, r)
for c in ("status", "report", "menu", "start", "params", "metrics"):
    al, uid, r = A.authorize(c, "", TOKEN, event_uid=UID)
    check("'" + c + "' without sig allowed", al, r)
    check("'" + c + "' uid from event", uid == UID, uid)
al, _, r = A.authorize("status", make(auth_date=time.time()-7200), TOKEN, event_uid=UID)
check("expired rejected", not al, r); check("expired reason", "ustarel" in r, r)
al, _, r = A.authorize("status", make(auth_date=time.time()-60), TOKEN, event_uid=UID)
check("fresh accepted", al, r)
al, _, r = A.authorize("status", make(auth_date=time.time()+600), TOKEN, event_uid=UID)
check("future rejected", not al, r)
check("empty init_data", A.verify("", TOKEN)[0] is False)
check("no token", A.verify(make(), "")[0] is False)
check("garbage", A.verify("garbage%%%", TOKEN)[0] is False)
check("no hash", A.verify("auth_date=1&user=%7B%7D", TOKEN)[0] is False)
cs = A.build_check_string([("b","2"),("a","1"),("hash","HASHVAL"),("signature","SIGVAL")])
check("check_string sorted", cs == "a=1\nb=2\nsignature=SIGVAL", repr(cs))
check("hash excluded", "hash=" not in cs, repr(cs))
check("signature included (Telegram 8.0+)", "signature=SIGVAL" in cs, repr(cs))
check("cmd normalized", A.authorize("/WALT_KEY", "", TOKEN, event_uid=UID)[0] is False)
check("hmac key right", A.secret_key(TOKEN) == hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest())
p = [("auth_date","111"),("query_id","AAA"),("user",'{"id":5}')]
check("check_string manual match", A.build_check_string(p) == "\n".join("%s=%s"%(k,v) for k,v in sorted(p)))
pp = sum(1 for _, ok in _r if ok); ff = len(_r)-pp
print("PASS: %d" % pp); print("FAIL: %d" % ff)
sys.exit(1 if ff else 0)
