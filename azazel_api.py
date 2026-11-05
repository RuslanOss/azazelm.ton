#!/usr/bin/env python3
"""
Azazel - server API dlya fronta "Metriki".
Otvechaet na GET /api/metrics?uid=<telegram_id>.

Vozvrashchaet JSON v forme, kotoruyu ozhidayet azazel-metrics/index.html:
  {account_name, updated, balance:{total,free,used}, flow24:{net,deposit,withdraw},
   pnl:{open,day24}, positions:[{symbol,side,entry,price,pnl}],
   trades:[{symbol,side,entry,exit,pnl}]}

Dannie berutsya iz Airtable (tablica "PolzovatelI") i lokalnogo sostoianiya
runtime (autotrading_config.json). Esli dostup k Walt API est - berutsya
sviezie dannye ottuda, inache - iz lokalnogo sostoyaniya.

Bez vneshnih zavisimostey: tolko stdlib.
"""
import json
import logging
import os
import sys
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "autotrading_config.json")
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN", "")
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "") or "app2PXtG16d227eoJ"
AIRTABLE_USERS_TABLE = os.environ.get("AIRTABLE_USERS_TABLE", "") or "tbl9q101sD0zmvrXx"
AIRTABLE_EVENTS_TABLE = os.environ.get("AIRTABLE_EVENTS_TABLE", "") or "tbl19AGwivPnURT5L"
ADMIN_ID = int(os.environ.get("ADMIN_TG_ID") or 0)
BOT_TOKEN = os.environ.get("AZABOT_TOKEN", "")
try:
    import azazel_initdata as _idm
except Exception:
    _idm = None
try:
    import azazel_ton_approval as _apv
except Exception:
    _apv = None
WALT_API_KEY = os.environ.get("WALT_API_KEY", "")
WALT_API_URL = os.environ.get("WALT_API_URL", "https://walt.bot/api")
PORT = int(os.environ.get("AZAZEL_API_PORT", "8787"))
CACHE_TTL = 5
log = logging.getLogger('azazel_api')
logging.basicConfig(level=logging.INFO)
_cache = {"t": 0.0, "data": None, "uid": None}   # KLYUCH = uid: ranee odin globalnyi kэsh otdaval dannye drugogo yuid


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_state():
    """Lokalnoe runtime-sostoyanie: balans, pozicii, sdelki."""
    out = {
        "account_name": "Agent subcount",
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "balance": {"total": 0.0, "free": 0.0, "used": 0.0},
        "flow24": {"net": 0.0, "deposit": 0.0, "withdraw": 0.0},
        "pnl": {"open": 0.0, "day24": 0.0},
        "positions": [],
        "trades": [],
    }
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return out

    bal = st.get("balance") or {}
    if isinstance(bal, dict):
        out["balance"] = {
            "total": _num(bal.get("total") or bal.get("equity")),
            "free": _num(bal.get("free") or bal.get("available")),
            "used": _num(bal.get("used") or bal.get("margin")),
        }
    for key in ("account_name", "name"):
        if st.get(key):
            out["account_name"] = str(st[key])
            break

    for p in st.get("positions") or []:
        if not isinstance(p, dict):
            continue
        out["positions"].append({
            "symbol": p.get("symbol") or p.get("market") or "",
            "side": (p.get("side") or "").lower(),
            "entry": _num(p.get("entry") or p.get("entry_price")),
            "price": _num(p.get("price") or p.get("mark_price") or p.get("last")),
            "pnl": _num(p.get("pnl") or p.get("unrealized_pnl")),
        })

    for t in st.get("trades") or st.get("closed_trades") or []:
        if not isinstance(t, dict):
            continue
        out["trades"].append({
            "symbol": t.get("symbol") or t.get("market") or "",
            "side": (t.get("side") or "").lower(),
            "entry": _num(t.get("entry") or t.get("entry_price")),
            "exit": _num(t.get("exit") or t.get("exit_price") or t.get("close")),
            "pnl": _num(t.get("pnl")),
        })

    flow = st.get("flow24") or {}
    if isinstance(flow, dict):
        out["flow24"] = {
            "net": _num(flow.get("net")),
            "deposit": _num(flow.get("deposit")),
            "withdraw": _num(flow.get("withdraw")),
        }
    pnl = st.get("pnl") or {}
    if isinstance(pnl, dict):
        out["pnl"] = {"open": _num(pnl.get("open")), "day24": _num(pnl.get("day24"))}
    return out


def airtable_user(uid):
    """Polzovatel iz Airtable: imya, status podpiski, parametry."""
    if not AIRTABLE_TOKEN:
        return {}
    from urllib.parse import quote as _q
    _flt = _q('{Telegram ID}="' + str(uid) + '"', safe="")
    url = ("https://api.airtable.com/v0/" + AIRTABLE_BASE_ID + "/" + AIRTABLE_USERS_TABLE
           + "?filterByFormula=" + _flt)
    try:
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + AIRTABLE_TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            recs = (json.load(r) or {}).get("records") or []
        if recs:
            return recs[0].get("fields") or {}
    except Exception as e:
        log.warning("airtable_user(%s) failed: %s", uid, e)
    return {}


def walt_snapshot():
    """Svezhie dannye iz Walt API, esli est klyuch."""
    if not WALT_API_KEY:
        return None
    try:
        req = urllib.request.Request(
            WALT_API_URL.rstrip("/") + "/agent/account",
            headers={"Authorization": "Bearer " + WALT_API_KEY, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception:
        return None


# ---------------- TON Connect: zapis koshelyka ----------------

def _airtable(method, path, body=None):
    """Airtable: GET/PATCH/POST. vozvrashchaet (status, parsed) ili (0, None)."""
    if not AIRTABLE_TOKEN:
        return 0, None
    try:
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://api.airtable.com/v0" + path, method=method, data=payload,
            headers={"Authorization": "Bearer " + AIRTABLE_TOKEN,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, None
    except Exception as e:
        log.warning("Airtable %s %s: %s", method, path, e)
        return 0, None


def _at_query_uid(table, uid, page_size=1):
    from urllib.parse import quote as _q
    flt = _q("{Telegram ID} = " + str(uid), safe="")
    st, d = _airtable("GET", "/" + AIRTABLE_BASE_ID + "/" + table
                      + "?filterByFormula=" + flt + "&maxRecords=" + str(page_size))
    if st != 200 or not isinstance(d, dict):
        return []
    return d.get("records") or []


def _tg_send(chat_id, text, buttons=None):
    """Otpravka soobshcheniya v Telegram. True/False."""
    if not BOT_TOKEN or not chat_id:
        return False
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    if buttons:
        rows = []
        for label, data in buttons:
            rows.append([{"text": label, "callback_data": data}])
        payload["reply_markup"] = {"inline_keyboard": rows}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
            method="POST", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8")).get("ok", False)
    except Exception as e:
        log.warning("tg_send failed: %s", e)
        return False



def _user_walt_credentials(uid):
    """Klyuch/sekret Walt polzovatelya iz lokalnogo JSON. -> (key, secret)."""
    data_dir = os.environ.get("AZAZEL_DATA_DIR") or "/opt/azazel-data"
    p = os.path.join(data_dir, "%s.json" % uid)
    try:
        with open(p, encoding="utf-8") as f:
            j = json.load(f)
    except Exception:
        return "", ""
    return (str(j.get("walt_key") or "").strip(),
            str(j.get("walt_secret") or "").strip())


def _execute_approved_order(uid, rec):
    """Ispolnit' odobrennyy order cherez Walt API.

    Plan stroit iz odobrennoy zayavki i ukhodit v tot zhe ispolnitel',
    chto i avtotsikl. Nikogda ne brosaet isklyuchenie naruzhu.
    """
    order = rec.get("order") or {}
    key, secret = _user_walt_credentials(uid)
    if not key or not secret:
        return {"ok": False, "error": "net klyucha Walt u polzovatelya"}
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import continuation_engine as ce
    except Exception as e:
        return {"ok": False, "error": "dvigok nedostupen: %s" % str(e)[:150]}
    plan = {
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "entry": float(order.get("entry") or 0),
        "stop_price": float(order.get("stop_price") or 0),
        "take_price": float(order.get("take_price") or 0),
        "leverage": int(order.get("leverage") or 1),
        "margin_usd": float(order.get("margin_usd") or 0),
    }
    try:
        res = ce.execute_plan(plan, key=key, secret=secret)
    except Exception as e:
        return {"ok": False, "error": str(e)[:250]}
    if not isinstance(res, dict):
        return {"ok": bool(res), "result": res}
    return {"ok": bool(res.get("ok")), "error": res.get("error"),
            "result": res.get("result")}


def _ton_addr_raw(addr):
    """Privetitnyy adres TON (UQ../EQ..) -> raw '<wc>:<hex>'."""
    a = (addr or "").strip()
    if not a:
        return a
    if ":" in a:
        return a
    try:
        import base64
        from ton_core.crypto import crc16
        if len(a) != 48:
            return a
        raw = base64.urlsafe_b64decode(a + "=" * (-len(a) % 4))
        if len(raw) != 36:
            return a
        if raw[0] not in (0x11, 0x01, 0x51):
            return a
        calc = crc16(raw[:34])
        if isinstance(calc, bytes):
            calc = int.from_bytes(calc, "big")
        if calc != int.from_bytes(raw[34:36], "big"):
            return a
        wc = -1 if raw[1] == 0xFF else raw[1]
        return "%d:%s" % (wc, raw[2:34].hex())
    except Exception:
        return a


def _ton_log_event(kind, uid, name, details=""):
    import datetime
    fields = {
        "Событие": kind,
        "Тип": "активация",
        "Дата": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "Пользователь": name or "",
        "Telegram ID": uid,
        "Источник": "miniapp",
        "Детали": (details or "")[:1900],
    }
    st, _ = _airtable("POST", "/" + AIRTABLE_BASE_ID + "/" + AIRTABLE_EVENTS_TABLE,
                      {"records": [{"fields": fields}]})
    return st in (200, 201)


def _ton_save_wallet(uid, addr, name=""):
    """Zapisyvaet koshelek v Airtable. vozvrashchaet (ok, message)."""
    rows = _at_query_uid(AIRTABLE_USERS_TABLE, uid, 1)
    if rows:
        rec_id = rows[0].get("id")
        st, _ = _airtable("PATCH", "/" + AIRTABLE_BASE_ID + "/" + AIRTABLE_USERS_TABLE
                          + "/" + str(rec_id), {"fields": {"Кошелёк Walt": addr}})
        if st not in (200, 201):
            return False, "Airtable: %s" % st
    _ton_log_event("кошелёк", uid, name, addr)
    if ADMIN_ID:
        _tg_send(ADMIN_ID, "Кошелёк подключён: %s -> %s" % (name or str(uid), addr))
    return True, "ok"


def build(uid):
    d = load_state()
    user = airtable_user(uid)
    if user.get("Name"):
        d["account_name"] = str(user["Name"])
    snap = walt_snapshot()
    if isinstance(snap, dict):
        bal = snap.get("balance") or snap.get("account") or {}
        if isinstance(bal, dict):
            d["balance"] = {
                "total": _num(bal.get("total") or bal.get("equity")),
                "free": _num(bal.get("free") or bal.get("available")),
                "used": _num(bal.get("used") or bal.get("margin")),
            }
        if snap.get("positions") is not None:
            d["positions"] = [{
                "symbol": (p.get("symbol") or ""),
                "side": (p.get("side") or "").lower(),
                "entry": _num(p.get("entry_price")),
                "price": _num(p.get("price") or p.get("mark_price")),
                "pnl": _num(p.get("pnl")),
            } for p in (snap.get("positions") or []) if isinstance(p, dict)]
    return d


class Handler(BaseHTTPRequestHandler):
    server_version = "AzazelAPI/1.0"

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        body = b""
        self.send_response(204)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/metrics"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            init_data = (q.get("init_data") or [""])[0]
            # UID beretsya TOLKO iz podpisannogo init_data.
            # initDataUnsafe forgeable -> zapros uid iz query ne doveryaem.
            if _idm is None or not BOT_TOKEN:
                self._json(503, {"error": "initdata module unavailable"})
                return
            ok, uid, reason = _idm.verify(init_data, BOT_TOKEN, max_age=86400)
            if not ok:
                self._json(401, {"error": "auth failed: " + str(reason)})
                return
            now = time.time()
            if (_cache["data"] is not None and _cache.get("uid") == uid
                    and now - _cache["t"] < CACHE_TTL):
                self._json(200, _cache["data"])
                return
            try:
                d = build(uid)
                _cache["t"], _cache["data"], _cache["uid"] = now, d, uid
                self._json(200, d)
            except Exception as e:
                self._json(500, {"error": str(e)})
            return
        if self.path.startswith("/api/ton_order_pending"):
            # Poslednyaya nedopodpisannaya zayavka polzovatelya.
            # Nuzhna, chtoby Mini App podхватил zayavku sozdannuyu botom.
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            init_data = (q.get("init_data") or [""])[0]
            if _idm is None or not BOT_TOKEN:
                self._json(503, {"error": "initdata module unavailable"})
                return
            ok, uid, reason = _idm.verify(init_data, BOT_TOKEN, max_age=86400)
            if not ok:
                self._json(401, {"error": "auth failed: " + str(reason)})
                return
            if _apv is None:
                self._json(503, {"error": "модуль подтверждения недоступен"})
                return
            try:
                pend = _apv.list_approvals(uid, only_pending=True)
            except Exception as e:
                self._json(500, {"error": str(e)[:150]})
                return
            if not pend:
                self._json(200, {"ok": True, "pending": None})
                return
            rec = pend[0]
            self._json(200, {"ok": True, "pending": {
                "approval_id": rec.get("id"),
                "nonce": rec.get("nonce"),
                "order": rec.get("order"),
                "order_hash": rec.get("order_hash"),
            }})
            return
        if self.path.startswith("/api/ton_nonce"):
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            init_data = (q.get("init_data") or [""])[0]
            if _idm is None or not BOT_TOKEN:
                self._json(503, {"error": "initdata module unavailable"})
                return
            ok, uid, reason = _idm.verify(init_data, BOT_TOKEN, max_age=86400)
            if not ok:
                self._json(401, {"error": "auth failed: " + str(reason)})
                return
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                if here not in sys.path:
                    sys.path.insert(0, here)
                import azazel_tonproof as tp
                rec = tp.issue_nonce()
                self._json(200, {"nonce": rec["nonce"], "domain": rec.get("domain", ""),
                                 "expires_in": int(tp.NONCE_TTL)})
            except Exception as e:
                log.exception("ton_nonce: %s", e)
                self._json(500, {"error": str(e)})
            return
        if self.path in ("/health", "/api/health"):
            self._json(200, {"ok": True, "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path.startswith("/api/ton_connect"):
            self._handle_ton_connect()
            return
        if self.path.startswith("/api/ton_order_request"):
            self._handle_ton_order_request()
            return
        if self.path.startswith("/api/ton_order_approve"):
            self._handle_ton_order_approve()
            return
        self._json(404, {"error": "not found"})

    def _handle_ton_connect(self):
        """Prinyat koshelyka ot Mini App: init_data (podpis) + ton_proof.

        Rabotaet bez web_app_data: front shlet POST napryamuyu.
        Dostup tol'ko po podpisi initData, uid beretsya iz nee.
        """
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 512 * 1024:
                self._json(400, {"error": "empty or too large body"})
                return
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception as e:
            self._json(400, {"error": "bad json: %s" % str(e)[:80]})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be an object"})
            return

        init_data = body.get("init_data") or ""
        if not init_data:
            self._json(401, {"error": "no init_data"})
            return
        if _idm is None or not BOT_TOKEN:
            self._json(503, {"error": "initdata module unavailable"})
            return
        ok, uid, reason = _idm.verify(init_data, BOT_TOKEN, max_age=86400)
        if not ok:
            log.warning("ton_connect: init_data rejected: %s", reason)
            self._json(401, {"error": "auth failed: " + str(reason)})
            return

        addr = (body.get("address") or body.get("wallet") or "").strip()
        if not addr:
            self._json(400, {"error": "no address"})
            return
        raw_addr = _ton_addr_raw(addr)
        if not raw_addr or ":" not in raw_addr:
            self._json(400, {"error": "bad address"})
            return

        raw = body.get("ton_proof") or body.get("proof") or ""
        if isinstance(raw, dict):
            proof = raw
        else:
            try:
                proof = json.loads(raw)
            except Exception:
                self._json(400, {"error": "cannot parse ton_proof"})
                return
        if not isinstance(proof, dict):
            self._json(400, {"error": "ton_proof is not an object"})
            return

        pk = body.get("public_key") or body.get("publicKey")
        if pk:
            proof["public_key"] = pk
        wsi = (body.get("wallet_state_init") or body.get("walletStateInit")
               or body.get("state_init") or body.get("stateInit") or "")
        if wsi:
            proof["walletStateInit"] = wsi
        if not wsi:
            self._json(400, {"error": "no walletStateInit"})
            return

        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            import azazel_tonproof as tp
        except Exception as e:
            log.exception("azazel_tonproof unavailable: %s", e)
            self._json(500, {"error": "tonproof module unavailable"})
            return

        good, why, pub = tp.verify_proof(proof, raw_addr,
                                         expected_domain=tp.ALLOWED_DOMAINS)
        if not good:
            log.warning("ton_connect: proof rejected uid=%s: %s", uid, why)
            self._json(400, {"error": "proof rejected: " + str(why)[:160]})
            return
        nonce = proof.get("payload") or ""
        if nonce and not tp.consume_nonce(nonce):
            log.warning("ton_connect: nonce invalid/reused uid=%s", uid)
            self._json(400, {"error": "nonce invalid or already used"})
            return

        name = ""
        rows = _at_query_uid(AIRTABLE_USERS_TABLE, uid, 1)
        if rows:
            name = str((rows[0].get("fields") or {}).get("Name") or "")
        saved, msg = _ton_save_wallet(uid, addr, name)
        if not saved:
            self._json(500, {"error": "airtable: " + str(msg)})
            return
        # lokalnoe sokhrnenie: nuzhno dlya proverki "koshelek podklyuchen"
        # pri sozdanii zayavki na order
        if _apv is not None:
            _apv.save_wallet(uid, addr, pub or "", body.get("wallet_state_init") or "")
        log.info("ton_connect ok uid=%s addr=%s pub=%s", uid, addr, pub)
        self._json(200, {"ok": True, "address": addr, "public_key": pub})


    # ---------- TON Connect: podtverzhdenie orderov ----------

    def _auth_initdata(self, init_data):
        """Proverit' podpis initData. -> (uid|None, error|None)."""
        if not init_data:
            return None, "net init_data"
        if _idm is None or not BOT_TOKEN:
            return None, "modul initdata nedostupen"
        ok, uid, reason = _idm.verify(init_data, BOT_TOKEN, max_age=86400)
        if not ok:
            return None, "auth failed: " + str(reason)
        return uid, None

    def _post_body(self):
        """Prochitat' i razobrat' telo POST. -> (body|None, error|None)."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 512 * 1024:
                return None, "empty or too large body"
            return json.loads(self.rfile.read(n).decode("utf-8")), None
        except Exception as e:
            return None, "bad json: " + str(e)[:80]

    def _handle_ton_order_request(self):
        """Sozdat' zayavku na podtverzhdenie ordera podpisyu koshelya.

        Telo: {init_data, order:{symbol,side,margin_usd,leverage,
                                 entry,stop_price,take_price}}
        """
        if _apv is None:
            self._json(503, {"error": "модуль подтверждения недоступен"})
            return
        body, err = self._post_body()
        if body is None:
            self._json(400, {"error": err})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be an object"})
            return
        uid, err = self._auth_initdata(body.get("init_data") or "")
        if uid is None:
            self._json(401, {"error": err})
            return
        order = body.get("order") or {}
        if not isinstance(order, dict):
            self._json(400, {"error": "order must be an object"})
            return
        wal = _apv.get_wallet(uid)
        if not wal.get("address"):
            self._json(409, {"error": "кошелёк не подключён"})
            return
        rec, err = _apv.create_order_request(uid, order)
        if rec is None:
            self._json(400, {"error": err})
            return
        log.info("ton_order_request uid=%s %s %s margin=%.2f lev=%d",
                 uid, rec["order"]["symbol"], rec["order"]["side"],
                 rec["order"]["margin_usd"], rec["order"]["leverage"])
        self._json(200, {
            "ok": True,
            "approval_id": rec["id"],
            "nonce": rec["nonce"],
            "order_hash": rec["order_hash"],
            "order": rec["order"],
            "expires_in": int(_apv.APPROVAL_TTL),
        })

    def _handle_ton_order_approve(self):
        """Prinyat' podpis koshelya i ispolnit' order.

        Telo: {init_data, approval_id, address, public_key,
               wallet_state_init, ton_proof}
        """
        if _apv is None:
            self._json(503, {"error": "модуль подтверждения недоступен"})
            return
        body, err = self._post_body()
        if body is None:
            self._json(400, {"error": err})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be an object"})
            return
        uid, err = self._auth_initdata(body.get("init_data") or "")
        if uid is None:
            self._json(401, {"error": err})
            return
        aid = str(body.get("approval_id") or "").strip()
        rec = _apv.get_approval(uid, aid)
        if not rec:
            self._json(404, {"error": "заявка не найдена"})
            return
        if rec.get("status") == "executed":
            self._json(409, {"error": "заявка уже исполнена"})
            return
        if rec.get("status") not in ("pending", "approved", "failed"):
            self._json(409, {"error": "заявка не в статусе ожидания: %s"
                             % rec.get("status")})
            return

        wal = _apv.get_wallet(uid)
        want = str(wal.get("address") or "")
        got = str(body.get("address") or "").strip()
        if not want:
            self._json(409, {"error": "кошелёк не подключён"})
            return
        if got != want:
            self._json(400, {"error": "адрес не совпадает с подключённым"})
            return

        raw = body.get("ton_proof") or body.get("proof") or ""
        proof = raw if isinstance(raw, dict) else None
        if proof is None:
            try:
                proof = json.loads(raw)
            except Exception:
                self._json(400, {"error": "cannot parse ton_proof"})
                return
        if not isinstance(proof, dict):
            self._json(400, {"error": "ton_proof is not an object"})
            return
        pk = body.get("public_key") or body.get("publicKey")
        if pk:
            proof["public_key"] = pk
        wsi = (body.get("wallet_state_init") or body.get("walletStateInit")
               or body.get("state_init") or body.get("stateInit") or "")
        if wsi:
            proof["walletStateInit"] = wsi

        try:
            here = os.path.dirname(os.path.abspath(__file__))
            if here not in sys.path:
                sys.path.insert(0, here)
            import azazel_tonproof as tp
        except Exception:
            self._json(500, {"error": "tonproof module unavailable"})
            return

        raw_addr = _ton_addr_raw(got)
        good, why, pub = tp.verify_proof(proof, raw_addr,
                                         expected_domain=tp.ALLOWED_DOMAINS)
        if not good:
            log.warning("ton_approve: proof rejected uid=%s: %s", uid, why)
            self._json(400, {"error": "proof rejected: " + str(why)[:160]})
            return

        payload = proof.get("payload") or ""
        if payload != rec.get("nonce"):
            log.warning("ton_approve: payload mismatch uid=%s", uid)
            self._json(400, {"error": "подпись относится к другому запросу"})
            return
        if not tp.consume_nonce(payload):
            log.warning("ton_approve: nonce invalid/reused uid=%s", uid)
            self._json(400, {"error": "nonce invalid or already used"})
            return

        rec["status"] = "approved"
        rec["approved_at"] = time.time()
        rec["address"] = got
        rec["public_key"] = pub
        _apv.save_approval(uid, rec)
        try:
            res = _execute_approved_order(uid, rec)
        except Exception as e:
            log.exception("ton_approve: execution failed uid=%s", uid)
            rec["status"] = "pending"
            rec["result"] = {"ok": False, "error": str(e)[:200]}
            rec["failed_at"] = time.time()
            _apv.save_approval(uid, rec)
            self._json(500, {"error": "исполнение не удалось: " + str(e)[:160]})
            return
        if not res.get("ok"):
            # OrdER ne uwel na birzhu. Zayavku vozvrashchaem v pending i
            # vydaem novyy nonce, chtoby polzovatel' mog podpisat' zanovo.
            rec["status"] = "pending"
            rec["result"] = res
            rec["failed_at"] = time.time()
            rec.pop("approved_at", None)
            new_nonce = ""
            try:
                new_nonce = _apv._issue_nonce()
            except Exception:
                new_nonce = ""
            if new_nonce:
                rec["nonce"] = new_nonce
            _apv.save_approval(uid, rec)
            log.warning("ton_approve execution failed uid=%s %s: %s",
                        uid, rec["order"].get("symbol"), res.get("error"))
            self._json(200, {"ok": False, "approval_id": aid,
                             "error": str(res.get("error") or "исполнение не удалось")[:160],
                             "retryable": True, "result": res})
            return
        rec["status"] = "executed"
        rec["executed_at"] = time.time()
        rec["result"] = res
        _apv.save_approval(uid, rec)
        log.info("ton_approve executed uid=%s %s ok=%s",
                 uid, rec["order"]["symbol"], res.get("ok"))
        self._json(200, {"ok": True, "approval_id": aid, "result": res})


    def log_message(self, fmt, *a):
        try:
            with open("/var/log/azazel_api.log", "a") as f:
                f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % a))
        except Exception:
            pass


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Azazel API on 127.0.0.1:%d" % PORT, flush=True)
    srv.serve_forever()
