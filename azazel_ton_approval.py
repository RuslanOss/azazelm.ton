# -*- coding: utf-8 -*-
"""
Azazel - podtverzhdenie torgovyh orderov podpisyu TON Connect.

Sxema:
  1. Mini App prosit server sozdat' zayavku na konkretnyy order
     (simvol, storona, marzha, plecho, stop, teyk). Server vydet
     approval_id i odnorazovyy nonce, privyazannyy k etomu orderu.
  2. Mini App prosit u koshelya podpis (ton_proof) imenno po etomu
     nonce - koshelyok pokazyvaet polzovatelyu, chto on podpisyvaet.
  3. Mini App otpravlyaet podpis na server. Server proveryaet podpis
     (ed25519), sveryaet adres s zaregistrirovannym pri podklyuchenii,
     sveryaet payload s nonce zayavki i zhzhet nonce.
  4. Tol'ko posle etogo server ispolnyaet order cherez Walt API.

Bezhiznes-lyogika: odin order ne uhodit na birzhu bez podpisi
koshelyka. Nonce odnorazovyy i s TTL, poetomu podpis neльзя
perеиспользовать dlya drugogo ordera.

Xranenie: /opt/azazel-data/ton_approvals_<uid>.json
"""
import json
import os
import time
import secrets
import hashlib

DATA_DIR = os.environ.get("AZAZEL_DATA_DIR") or "/opt/azazel-data"
APPROVAL_TTL = 900          # 15 minut na podtverzhdenie
MAX_APPROVALS = 50          # skolko zayavok derzhim na odin uid


# ------------------------------------------------------------------ utils

def _ap_path(uid):
    return os.path.join(DATA_DIR, "ton_approvals_%s.json" % uid)


def _wal_path(uid):
    return os.path.join(DATA_DIR, "ton_wallet_%s.json" % uid)


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def _write_json(path, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False



def _issue_nonce():
    """Nonce iz obshchego khranilisha modulya podpisi. -> str.

    Esli modul nedostupen - otkazivuem, a ne podmenyaem: podpis
    vse ravno ne proydet proverku, luchshe ponyat' eto srazu.
    """
    try:
        import azazel_tonproof as tp
    except Exception:
        return ""
    try:
        rec = tp.issue_nonce()
        return str((rec or {}).get("nonce") or "")
    except Exception:
        return ""


def order_hash(order):
    """Stabilnyy identifikator soderzhaniya ordera."""
    keys = ("symbol", "side", "margin_usd", "leverage",
            "stop_price", "take_price", "entry")
    parts = []
    for k in keys:
        v = order.get(k)
        try:
            v = round(float(v), 8)
        except (TypeError, ValueError):
            v = str(v)
        parts.append("%s=%s" % (k, v))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


# ------------------------------------------------------- koshelek / profil

def save_wallet(uid, address, public_key="", wallet_state_init=""):
    """Zapomnit koshelek polzovatelya (posle uspeshnogo podklyucheniya)."""
    rec = {"address": address, "public_key": public_key or "",
           "wallet_state_init": wallet_state_init or "",
           "updated": time.time()}
    return _write_json(_wal_path(uid), rec)


def get_wallet(uid):
    return _read_json(_wal_path(uid), {}) or {}


# ------------------------------------------------------------- zayavki

def _clean(uid):
    data = _read_json(_ap_path(uid), {}) or {}
    now = time.time()
    out = {}
    for aid, rec in data.items():
        if not isinstance(rec, dict):
            continue
        created = float(rec.get("created") or 0)
        if rec.get("status") == "pending" and now - created > APPROVAL_TTL:
            rec["status"] = "expired"
        out[aid] = rec
    return out


def create_order_request(uid, order):
    """ sozdat' zayavku na podtverzhdenie ordera.

    vozvrashchaet (approval|None, error|None)
    """
    sym = str(order.get("symbol") or "").upper().strip()
    side = str(order.get("side") or "").lower().strip()
    if not sym:
        return None, "net simvola"
    if side not in ("long", "short"):
        return None, "storona dolzhna byt long ili short"
    try:
        margin = float(order.get("margin_usd") or 0)
        lev = int(float(order.get("leverage") or 1))
    except (TypeError, ValueError):
        return None, "marzha ili plecho ne chislo"
    if margin <= 0:
        return None, "marzha dolzhna byt bolshe 0"
    if lev < 1 or lev > 20:
        return None, "plecho ot 1 do 20"

    o = dict(order)
    o["symbol"] = sym
    o["side"] = side
    o["margin_usd"] = margin
    o["leverage"] = lev
    for k in ("entry", "stop_price", "take_price"):
        try:
            o[k] = float(order.get(k) or 0)
        except (TypeError, ValueError):
            o[k] = 0.0

    aid = secrets.token_hex(8)
    # Nonse berem iz OBSHCHEGO khranilisha modulya podpisi (azazel_tonproof):
    # imenno tam proverka consume_nonce() ishet nonce. Svoy nonce zdes
    # by ne proshyol by proverku - podpis otklonili by kak "unknown nonce".
    nonce = _issue_nonce()
    data = _clean(uid)
    rec = {
        "id": aid,
        "uid": str(uid),
        "order": o,
        "order_hash": order_hash(o),
        "nonce": nonce,
        "status": "pending",
        "created": time.time(),
        "approved_at": None,
        "executed_at": None,
        "result": None,
        "address": None,
        "public_key": None,
    }
    if not nonce:
        return None, "не удалось получить nonce для подписи"
    data[aid] = rec
    # chistim starye
    pend = [k for k, v in data.items()
            if isinstance(v, dict) and v.get("status") == "pending"]
    pend.sort(key=lambda k: data[k].get("created") or 0)
    while len(pend) > MAX_APPROVALS:
        old = pend.pop(0)
        data[old]["status"] = "expired"
    if not _write_json(_ap_path(uid), data):
        return None, "ne udalos' zapist' zayavku"
    return rec, None


def list_approvals(uid, only_pending=False):
    data = _clean(uid)
    out = []
    for aid, rec in data.items():
        if only_pending and rec.get("status") != "pending":
            continue
        out.append({
            "id": aid,
            "status": rec.get("status"),
            "order": rec.get("order"),
            "order_hash": rec.get("order_hash"),
            "created": rec.get("created"),
            "approved_at": rec.get("approved_at"),
            "executed_at": rec.get("executed_at"),
            "result": rec.get("result"),
            "address": rec.get("address"),
        })
    out.sort(key=lambda r: r.get("created") or 0, reverse=True)
    return out


def get_approval(uid, aid):
    data = _clean(uid)
    rec = data.get(aid)
    return rec if isinstance(rec, dict) else None


def save_approval(uid, rec):
    data = _clean(uid)
    data[rec["id"]] = rec
    return _write_json(_ap_path(uid), data)
