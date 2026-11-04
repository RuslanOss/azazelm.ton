#!/usr/bin/env python3
"""
Proverka TON Connect (ton_proof) dlya Azazel.

Specifikaciya (ton-connect/spec/connect.md, "Address proof signature"):

    message = utf8("ton-proof-item-v2/")
           ++ workchain (int32, big-endian)
           ++ address hash (32 bytes)
           ++ domain length (uint32, little-endian)
           ++ domain (utf-8)
           ++ timestamp (uint64, little-endian)
           ++ payload (utf-8)

    digest = sha256( 0xffff ++ utf8("ton-connect") ++ sha256(message) )
    signature = Ed25519Sign(privkey, digest)

Proverka: podpis Ed25519 po pubkey + sverka polya (domain, timestamp, payload).
Rabotaet s lyubym TON Connect wallet: pubkey beretsya iz walletStateInit
(rasparxiv data cell) ili s on-chain get_public_key.
"""
import base64
import hashlib
import json
import os
import struct
import time
import urllib.request

TON_PROOF_PREFIX = b"ton-proof-item-v2/"
TON_CONNECT_PREFIX = b"ton-connect"

DEFAULT_MAX_AGE = 600          # 10 минут
DEFAULT_DOMAIN = "azazelm.com"

# nonce: odnozagочное, zhivyot ogranicheno
NONCE_TTL = 300


# ---------------- nonce store ----------------

def _nonce_path():
    d = os.environ.get("AZAZEL_DATA_DIR") or "/opt/azabot"
    return os.path.join(d, "tonconnect_nonces.json")


def issue_nonce(domain=DEFAULT_DOMAIN):
    """Vydet odnozagочный nonce dlya payload."""
    import secrets
    nonce = secrets.token_hex(16)
    rec = {"nonce": nonce, "domain": domain, "created": time.time()}
    data = load_nonces()
    now = time.time()
    data = {k: v for k, v in data.items() if now - v.get("created", 0) < NONCE_TTL}
    data[nonce] = rec
    try:
        with open(_nonce_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(_nonce_path(), 0o600)
    except Exception:
        pass
    return rec


def load_nonces():
    try:
        with open(_nonce_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def consume_nonce(nonce, payload=None):
    """Atomicheski potrebyaet nonce. True, esli nonce byl realny i ne ispolzovalsya."""
    data = load_nonces()
    rec = data.get(nonce)
    if not rec:
        return False
    if time.time() - rec.get("created", 0) > NONCE_TTL:
        return False
    if payload is not None and rec.get("payload") and payload != rec.get("payload"):
        return False
    data.pop(nonce, None)
    try:
        with open(_nonce_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.chmod(_nonce_path(), 0o600)
    except Exception:
        pass
    return True


# ---------------- pubkey ----------------

def pubkey_from_state_init(b64_state_init):
    """Izvlekaet pubkey iz walletStateInit (data cell) standartnyh walletov.

    vozvrashchaet hex-pubkey (64 hex) ili None.
    """
    try:
        from ton_core import Cell
        raw = base64.b64decode(b64_state_init)
        cell = Cell.from_boc(raw)[0]
        # StateInit: code, data
        sl = cell.begin_parse()
        code = sl.load_ref()
        data = sl.load_ref()
        dsl = data.begin_parse()
        dsl.load_uint(32)          # seqno
        dsl.load_uint(32)          # wallet_id
        pub = dsl.load_bytes(32)   # public key
        return pub.hex()
    except Exception:
        return None


def pubkey_onchain(address_raw, timeout=12):
    """Fallback: get_public_key na鏈. vozvrashchaet hex ili None."""
    try:
        url = "https://toncenter.com/api/v3/runGetMethod?address=%s&method=pubkey" % address_raw
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                  "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
        stack = j.get("stack") or []
        if not stack:
            return None
        item = stack[0]
        hexv = item.get("hex") or ""
        if len(hexv) >= 64:
            return hexv[-64:]
        return None
    except Exception:
        return None


# ---------------- proof verification ----------------

def build_message(address_raw, domain, timestamp, payload):
    """Sboro(message) po spetsifikatsii."""
    # address_raw: "0:<hex>" ili "<hex>"
    a = address_raw.strip()
    if ":" in a:
        wc_s, hash_hex = a.split(":", 1)
        wc = int(wc_s)
    else:
        wc = 0
        hash_hex = a
    hash_bytes = bytes.fromhex(hash_hex)

    dom = domain.encode("utf-8")
    ts = int(timestamp)
    pay = payload.encode("utf-8")

    return (
        TON_PROOF_PREFIX
        + struct.pack(">i", wc)
        + hash_bytes
        + struct.pack("<I", len(dom))
        + dom
        + struct.pack("<Q", ts)
        + pay
    )


def verify_proof(proof, address_raw, expected_domain=None,
                 max_age=DEFAULT_MAX_AGE, now=None):
    """Proveryaet ton_proof.

    proof: dict {timestamp, domain:{value,lengthBytes}, signature, payload}
    vozvrashchaet (ok, reason, public_key)
    """
    now = now or time.time()

    if not isinstance(proof, dict):
        return False, "proof ne obekt", None

    # domain
    dom = proof.get("domain") or {}
    domain = dom.get("value") or ""
    length_bytes = dom.get("lengthBytes")
    if expected_domain:
        if domain != expected_domain:
            return False, "domain ne sovpal: %r != %r" % (domain, expected_domain), None
    if "." not in domain:
        return False, "domain dolzhen soderzhat tochku", None
    if length_bytes is not None and int(length_bytes) != len(domain.encode("utf-8")):
        return False, "lengthBytes ne sovpal s dlinoyu domaina", None

    # timestamp
    try:
        ts = int(proof.get("timestamp"))
    except Exception:
        return False, "net korrektnogo timestamp", None
    if ts > now + 60:
        return False, "timestamp iz budushchego", None
    if now - ts > max_age:
        return False, "timestamp slishkom staryy (%.0fs)" % (now - ts), None

    # signature
    sig_b64 = proof.get("signature") or ""
    try:
        sig = base64.b64decode(sig_b64)
    except Exception:
        return False, "signature ne base64", None
    if len(sig) != 64:
        return False, "signature ne 64 baita", None

    payload = proof.get("payload") or ""
    message = build_message(address_raw, domain, ts, payload)
    msg_hash = hashlib.sha256(message).digest()
    full = b"\xff\xff" + TON_CONNECT_PREFIX + msg_hash
    digest = hashlib.sha256(full).digest()

    # pubkey: iz walletStateInit, iz klienta (TonAddressItemReply.publicKey) ili on-chain
    pub_hex = None
    ws = (proof.get("walletStateInit") or proof.get("wallet_state_init")
          or proof.get("stateInit") or proof.get("state_init"))
    client_hex = (proof.get("public_key") or proof.get("publicKey")
                  or proof.get("publicKeyHex") or proof.get("public_key_hex"))
    if client_hex is not None:
        client_hex = str(client_hex).strip().lower()
        if len(client_hex) != 64 or not all(c in "0123456789abcdef" for c in client_hex):
            return False, "public_key ne validnyy hex(64 simvola)", None
    ws_hex = pubkey_from_state_init(ws) if ws else None
    # Esli klient prislal publicKey i walletStateInit est -- oni OBYAZANY sovpadat.
    if ws_hex and client_hex and ws_hex.lower() != client_hex:
        return False, "public_key ne sovpal s pubkey iz walletStateInit", None
    pub_hex = ws_hex or client_hex
    if not pub_hex:
        pub_hex = pubkey_onchain(address_raw)
    if not pub_hex:
        return False, ("pubkey ne poluchen: net walletStateInit, net public_key "
                       "ot klienta, net on-chain getter"), None

    # proverka adresa i walletStateInit hash
    if ws:
        try:
            from ton_core import Cell
            cell = Cell.from_boc(base64.b64decode(ws))[0]
            a = address_raw.strip()
            if ":" in a:
                wc_s, hash_hex = a.split(":", 1)
            else:
                wc_s, hash_hex = "0", a
            _h = cell.hash
            _h = _h() if callable(_h) else _h
            if _h.hex() != hash_hex.lower():
                return False, "walletStateInit hash ne sovpal s adresom", None
        except Exception as e:
            return False, "walletStateInit ne razobralsya: %s" % (str(e)[:60]), None

    # ed25519 verify
    try:
        from nacl.signing import VerifyKey
        vk = VerifyKey(bytes.fromhex(pub_hex))
        vk.verify(digest, sig)
    except ImportError:
        return False, "net pynacl", None
    except Exception as e:
        return False, "podpis ne prosherilsya: %s" % (str(e)[:80]), None

    return True, "ok", pub_hex
