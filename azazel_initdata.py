"""Proverka podpisi Telegram initData dlya Mini App.

Telegram podpisyvaet tol'ko initData. Sam metod sendData nichego ne
podpisyvaet, poetomu dannie iz nego nelzya schitat' dochernimi. Etot modul:

1. schitaet HMAC-SHA256 signaturu initData algoritmom Telegram;
2. izvlekayet user.id IZ PODPISI (a ne iz query-stroki ot klienta);
3. proveryaet srok (auth_date);
4. reshaet, kakie komandy voobshche dostupny bez podpisi.

Chistyy modul bez zavisimostey ot bot.py, chtoby testirovat' izolirovanno.
"""

import hashlib
import hmac
import json
import time

DEFAULT_MAX_AGE = 3600

# Komandy, kotorye menyayut dostup ili tiliut den'gi.
SENSITIVE_COMMANDS = frozenset({
    "walt_key",
    "settings_save",
    "ton_nonce",
    "ton_connect",
})


def build_check_string(params, exclude=("hash",)):
    """Sbornaya stroka Telegram: k=v, otsortirovanno po klyuchu, cherez \n.

    VAZHNO: iz stroki isklyuchaetsya TOL'KO "hash".
    Pole "signature" (podpis Telegram) v check-string VKHODIT i dolzhno
    ostatsya na svoem meste. Esli isklyuchit' ego - HMAC ne sojdetetsya
    i lyuboy initData budet otklonyatsya s 401.
    """
    parts = []
    for key, value in sorted(params):
        if key in exclude:
            continue
        parts.append("%s=%s" % (key, value))
    return "\n".join(parts)


def secret_key(bot_token):
    """Klyuch HMAC: HMAC-SHA256(klyuch="WebAppData", msg=bot_token)."""
    return hmac.new(b"WebAppData", (bot_token or "").encode("utf-8"), hashlib.sha256).digest()


def verify(init_data, bot_token, max_age=DEFAULT_MAX_AGE, now=None):
    """Proveryaet podpis. Vozvrashchaet (ok, uid, reason)."""
    if not init_data:
        return False, None, "init_data pust"
    if not bot_token:
        return False, None, "net bot_token"

    from urllib.parse import parse_qsl
    try:
        params = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return False, None, "init_data ne parsitsya"

    if not params:
        return False, None, "init_data pust ili bez parametrov"

    received = None
    auth_date = None
    user_raw = None
    for key, value in params:
        if key == "hash" and received is None:
            received = value
        elif key == "auth_date" and auth_date is None:
            auth_date = value
        elif key == "user" and user_raw is None:
            user_raw = value

    if not received:
        return False, None, "net hash v init_data"

    check = build_check_string(params)
    calc = hmac.new(secret_key(bot_token), check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return False, None, "podpis ne sovпадаet"

    if auth_date:
        try:
            age = (now if now is not None else time.time()) - int(auth_date)
        except Exception:
            return False, None, "auth_date ne chislo"
        if max_age and age > max_age:
            return False, None, "init_data ustarel (%.0f s)" % age
        if age < -300:
            return False, None, "auth_date iz budushchego"

    uid = None
    if user_raw:
        try:
            user = json.loads(user_raw)
            uid = int(user["id"])
        except Exception:
            return False, None, "user v init_data ne razobran"

    return True, uid, "ok"


def authorize(cmd, init_data, bot_token, event_uid=None, max_age=DEFAULT_MAX_AGE, now=None):
    """Reshaet, mozhno li vypolnit komandu. Vozvrashchaet (allowed, uid, reason)."""
    cmd = str(cmd or "").strip().lower().lstrip("/")
    event_uid = int(event_uid) if event_uid else None

    if not init_data:
        if cmd in SENSITIVE_COMMANDS:
            return False, None, "komanda '%s' trebuet podpisannyy init_data" % cmd
        return True, event_uid, "net init_data, publichnaya komanda"

    ok, uid, reason = verify(init_data, bot_token, max_age=max_age, now=now)
    if not ok:
        return False, None, reason
    if event_uid and uid and uid != event_uid:
        return False, None, "uid iz podpisi (%s) ne sovpal s otpravitelem (%s)" % (uid, event_uid)
    return True, uid, "podpis ok"
