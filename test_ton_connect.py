
"""Testy TON Connect v novom flow: Mini App -> HTTP API (/api/ton_nonce + /api/ton_connect).

Staryi test_ton_connect.py proveryal komandy bot'a (cmd_ton_nonce/cmd_ton_connect),
katorye udaleny v kommute 740c6406 - bot-side obrabotchiki byli mertvymi.
Realnyi put: front shlet POST napryamuyu v API, dostup po podpisi initData.

Test podnimaet SVOI server na efemernom portu s podmenoy _ton_save_wallet,
tak chto Airtable ne zapolnyaetsya testovym adresom.
"""
import base64, hashlib, hmac, json, os, sys, time, threading, urllib.error, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer
from urllib.parse import urlencode, quote

sys.path.insert(0, "/opt/azabot")

PASS = 0
FAIL = 0
RESULTS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS:", name)
    else:
        FAIL += 1
        print("FAIL:", name, "::", detail)
    RESULTS.append((name, bool(cond)))


def load_env():
    p = "/opt/azabot/.env"
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


import azazel_test_guard as _guard  # izolyaciya ot boevoy Airtable/Telegram

import azazel_initdata as idm
import azazel_tonproof as tp

# ── 1. Мёртвый код бота удалён (регрессия) ──────────────────────────
bot_src = open("/opt/azabot/bot.py", encoding="utf-8").read()
for dead in ("cmd_ton_nonce", "cmd_ton_connect", "_tonproof", "_ton_addr_raw"):
    check("bot.py без " + dead, dead not in bot_src)
check("bot.py сохранил _ton_addr_ok", "_ton_addr_ok" in bot_src)
check("bot.py сохранил finish_wallet", "finish_wallet" in bot_src)
check("bot.py: ветка cmd==ton_nonce удалена", 'cmd == "ton_nonce"' not in bot_src)
check("bot.py: ветка cmd==ton_connect удалена", 'cmd == "ton_connect"' not in bot_src)

# ── 2. Чувствительные команды остались в initdata ──────────────────
check("ton_nonce в SENSITIVE_COMMANDS", "ton_nonce" in idm.SENSITIVE_COMMANDS)
check("ton_connect в SENSITIVE_COMMANDS", "ton_connect" in idm.SENSITIVE_COMMANDS)
ok, _, reason = idm.authorize("ton_connect", "", "TOKEN", event_uid=None)
check("ton_connect без init_data отклонён", ok is False, reason)

# ── 3. Домены ───────────────────────────────────────────────────────
check("azazelm.com разрешён", "azazelm.com" in tp.ALLOWED_DOMAINS)
check("Pages-домен разрешён", "azazel-trader-yz2uw75a.agent.mira.tg" in tp.ALLOWED_DOMAINS)

# ── 4. Подпись initData ─────────────────────────────────────────────
TOKEN = os.environ.get("AZABOT_TOKEN") or ""
UID = 8459508879


def make_init(token=TOKEN, uid=UID, auth_date=None):
    user = json.dumps({"id": uid, "first_name": "Test"}, separators=(",", ":"))
    p = {"auth_date": str(int(auth_date if auth_date is not None else time.time())),
         "query_id": "AAF_testquery", "user": user}
    cs = "\n".join("%s=%s" % (k, p[k]) for k in sorted(p))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    p["hash"] = hmac.new(sec, cs.encode(), hashlib.sha256).hexdigest()
    return urlencode(p)


check("BOT_TOKEN прочитан", bool(TOKEN))
if not TOKEN:
    print("FAIL: нет BOT_TOKEN - дальнейшие проверки API невозможны")
    print("PASS: %d" % PASS)
    print("FAIL: %d" % FAIL)
    sys.exit(1)

init = make_init()
ok, uid, reason = idm.verify(init, TOKEN)
check("initData принята", ok, reason)
check("uid из подписи", uid == UID, uid)

# ── 5. Поднимаем API на эфемерном порту ─────────────────────────────
import azazel_api as api
_guard.protect_api(api)

SAVED = []
_real_save = api._ton_save_wallet


def fake_save(uid, addr, name=""):
    SAVED.append((uid, addr))
    return True, "ok"


api._ton_save_wallet = fake_save
api._at_query_uid = lambda table, uid, page_size=1: [
    {"id": "rec_test", "fields": {"Name": "Test"}}]

srv = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return "ERR", {"error": str(e)[:120]}


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return "ERR", {"error": str(e)[:120]}


try:
    # ── 6. /api/ton_nonce ───────────────────────────────────────────
    st, j = get("/api/ton_nonce?init_data=" + urllib.parse.quote("garbage", safe=""))
    check("ton_nonce без init_data -> 401", st == 401, "%s %s" % (st, j))

    st, j = get("/api/ton_nonce?init_data=" + urllib.parse.quote(init, safe=""))
    check("ton_nonce с init_data -> 200", st == 200, "%s %s" % (st, j))
    nonce = j.get("nonce") or ""
    check("ton_nonce вернул nonce", bool(nonce), j)
    check("ton_nonce domain = azazelm.com", j.get("domain") == "azazelm.com", j.get("domain"))
    check("nonce в хранилище", nonce in tp.load_nonces())

    # ── 7. Синтетический кошелёк (как в e2e) ───────────────────────
    from ton_core import Cell, begin_cell
    from nacl.signing import SigningKey

    def _hash(c):
        h = c.hash
        return h() if callable(h) else h

    sk = SigningKey.generate()
    pub = sk.verify_key.encode().hex()
    data = begin_cell().store_uint(0, 32).store_uint(0, 32).store_bytes(bytes.fromhex(pub)).end_cell()
    code = begin_cell().store_uint(0, 32).end_cell()
    si = begin_cell().store_ref(code).store_ref(data).end_cell()
    wsi = base64.b64encode(si.to_boc()).decode()
    addr_raw = "0:" + _hash(si).hex()

    def make_proof(n, domain="azazelm.com", ts=None, sign_key=None):
        ts = int(time.time()) if ts is None else ts
        msg = tp.build_message(addr_raw, domain, ts, n)
        digest = hashlib.sha256(b"\xff\xff" + tp.TON_CONNECT_PREFIX + hashlib.sha256(msg).digest()).digest()
        sig = (sign_key or sk).sign(digest).signature
        return {"timestamp": ts, "domain": {"value": domain, "lengthBytes": len(domain.encode())},
                "signature": base64.b64encode(sig).decode(), "payload": n,
                "public_key": pub, "walletStateInit": wsi}

    # ── 8. Негативные кейсы ton_connect ────────────────────────────
    st, j = post("/api/ton_connect", {"address": addr_raw})
    check("ton_connect без init_data -> 401", st == 401, "%s %s" % (st, j))

    st, j = post("/api/ton_connect", {"init_data": init})
    check("ton_connect без адреса -> 400", st == 400, "%s %s" % (st, j))

    st, j = post("/api/ton_connect", {"init_data": init, "address": "hello"})
    check("ton_connect с плохим адресом -> 400", st == 400, "%s %s" % (st, j))

    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "ton_proof": "не json"})
    check("ton_connect с мусорным proof -> 400", st == 400, "%s %s" % (st, j))

    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "ton_proof": make_proof("deadbeef" * 4)})
    check("ton_connect с чужим nonce -> 400", st == 400, "%s %s" % (st, j))
    check("чужая запись в Airtable не случилась", not SAVED, SAVED)

    # proof без walletStateInit
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "ton_proof": make_proof(nonce)})
    check("ton_connect без walletStateInit -> 400", st == 400, "%s %s" % (st, j))
    check("ошибка mentions walletStateInit", "walletStateInit" in str(j.get("error", "")), j)

    # подпись чужим ключом
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub,
                                       "ton_proof": make_proof(nonce, sign_key=SigningKey.generate())})
    check("ton_connect с чужой подписью -> 400", st == 400, "%s %s" % (st, j))
    check("подделка не записана", not SAVED, SAVED)

    # чужой домен
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub,
                                       "ton_proof": make_proof(nonce, domain="evil.example.com")})
    check("ton_connect с чужим доменом -> 400", st == 400, "%s %s" % (st, j))

    # протухший timestamp
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub,
                                       "ton_proof": make_proof(nonce, ts=int(time.time()) - 4000)})
    check("ton_connect со старым timestamp -> 400", st == 400, "%s %s" % (st, j))

    # ── 9. Happy path ───────────────────────────────────────────────
    st, j = get("/api/ton_nonce?init_data=" + urllib.parse.quote(init, safe=""))
    nonce2 = j.get("nonce") or ""
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "wallet_state_init": wsi,
                                       "ton_proof": make_proof(nonce2)})
    check("ton_connect happy path -> 200", st == 200, "%s %s" % (st, j))
    check("ответ содержит ok", j.get("ok") is True, j)
    check("ответ содержит адрес", j.get("address") == addr_raw, j)
    check("ответ содержит public_key", j.get("public_key") == pub, j)
    check("кошелёк записан", len(SAVED) == 1 and SAVED[0][1] == addr_raw, SAVED)
    check("uid в записи верный", SAVED and SAVED[0][0] == UID, SAVED)

    # ── 10. nonce одноразовый ───────────────────────────────────────
    st, j = get("/api/ton_nonce?init_data=" + urllib.parse.quote(init, safe=""))
    nonce3 = j.get("nonce") or ""
    pr = make_proof(nonce3)
    saved_before = len(SAVED)
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "wallet_state_init": wsi,
                                       "ton_proof": pr})
    check("первый раз с nonce -> 200", st == 200, "%s %s" % (st, j))
    check("первый раз записал кошелёк", len(SAVED) == saved_before + 1, SAVED)
    st, j = post("/api/ton_connect", {"init_data": init, "address": addr_raw,
                                       "public_key": pub, "wallet_state_init": wsi,
                                       "ton_proof": pr})
    check("повтор того же nonce -> 400", st == 400, "%s %s" % (st, j))
    check("повтор не записал кошелёк", len(SAVED) == saved_before + 1, SAVED)

    # ── 11. verify_proof напрямую ───────────────────────────────────
    # verify_proof proveryaet podpis, a ne nonce: nonce kontroliruet API cherez
    # consume_nonce (provenо vyshe - povtornyy nonce daet 400).
    ok, reason, got = tp.verify_proof(make_proof("x" * 32), addr_raw,
                                       expected_domain=tp.ALLOWED_DOMAINS)
    check("verify_proof prinimaet validnuyu podpis", ok is True, reason)
    check("verify_proof vernul pubkey", got == pub, got)
    ok, reason, got = tp.verify_proof(make_proof("x" * 32, domain="evil.example.com"), addr_raw,
                                       expected_domain=tp.ALLOWED_DOMAINS)
    check("verify_proof otbit чуждый домен", ok is False, reason)
    ok, reason, got = tp.verify_proof(make_proof("x" * 32, ts=int(time.time()) - 4000), addr_raw,
                                       expected_domain=tp.ALLOWED_DOMAINS)
    check("verify_proof otbit staryy timestamp", ok is False, reason)

finally:
    api._ton_save_wallet = _real_save
    srv.shutdown()

print("PASS: %d" % PASS)
print("FAIL: %d" % FAIL)
sys.exit(1 if FAIL else 0)
