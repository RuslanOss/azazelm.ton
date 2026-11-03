# -*- coding: utf-8 -*-
"""Планировщик автономного торгового цикла.

Вынесен из bot.py, чтобы правки в боте были минимальными: бот только
передаёт сюда функции доступа к Airtable и JSON-профилю.

Кто запускается:
  * у пользователя есть профиль с ключом Walt;
  * параметры настроены (прогресс 100);
  * в профиле включено автоподтверждение - иначе цикл всё равно
    отработал бы вхолостую, но мы и не будем его гонять зря.

Ключевое правило: автоподтверждение выключено по умолчанию. Цикл
готовит планы и пишет их, но ордера не отправляет, пока пользователь
явно не включил "Автоподтверждение" в профиле.
"""
import os
import sys
import json
import glob
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import azazel_trading_cycle as TC
except Exception:
    TC = None

try:
    from walt_client import WaltClient
except Exception:
    WaltClient = None

DEFAULT_INTERVAL_MIN = 15


# ---------------------------------------------------------------- профили

def user_json_path(data_dir, uid):
    return os.path.join(data_dir, str(uid) + ".json")


def list_users(data_dir):
    """Все uid, у которых есть JSON-профиль. -> список int."""
    out = []
    try:
        for p in glob.glob(os.path.join(data_dir, "*.json")):
            base = os.path.basename(p)[:-5]
            if base.isdigit():
                out.append(int(base))
    except Exception:
        pass
    return sorted(out)


def read_user_json(data_dir, uid):
    p = user_json_path(data_dir, uid)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def eligible(profile, uj):
    """Пользователь готов к циклу. -> (bool, причина)."""
    if uj is None:
        return False, "нет профиля"
    key = (uj.get("walt_key") or "").strip()
    secret = (uj.get("walt_secret") or "").strip()
    if not key or not secret:
        return False, "не задан ключ Walt"
    # Параметры риска обязательны: без них движок работал бы на дефолтах,
    # а это не то, что пользователь выбрал в настройках. Не пускаем.
    prog = profile.get("Прогресс настройки")
    try:
        if int(prog or 0) < 100:
            return False, "параметры не заданы"
    except (TypeError, ValueError):
        return False, "параметры не заданы"
    sub = profile.get("Подписка")
    if sub and sub != "активна":
        return False, "нет активной подписки"
    return True, "готов"


def walt_credentials(uj):
    return ((uj or {}).get("walt_key") or "").strip(), \
           ((uj or {}).get("walt_secret") or "").strip()


# ---------------------------------------------------------------- состояние

def load_state(data_dir, uid):
    """Состояние цикла из JSON: позиции, счётчики дня, маржа."""
    st = {"positions": [], "trades_today": 0, "stops_today": 0,
          "pnl_today": 0.0, "free_margin": 0.0, "day": None}
    j = read_user_json(data_dir, uid) or {}
    for k in ("positions", "trades_today", "stops_today", "pnl_today",
              "free_margin"):
        if k in j:
            st[k] = j[k]
    st["day"] = j.get("day")
    return st


def save_state(data_dir, uid, state):
    """Записать состояние, сохранив остальные поля JSON."""
    j = read_user_json(data_dir, uid) or {}
    for k in ("positions", "trades_today", "stops_today", "pnl_today",
              "free_margin", "day"):
        if k in (state or {}):
            j[k] = state[k]
    j["updated"] = _now_iso()
    p = user_json_path(data_dir, uid)
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        os.chmod(p, 0o644)
        return True
    except Exception:
        return False


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def today_str():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def roll_day(state):
    """Сбросить дневные счётчики, если сменился день."""
    today = today_str()
    if state.get("day") != today:
        state["day"] = today
        state["trades_today"] = 0
        state["stops_today"] = 0
        state["pnl_today"] = 0.0
        return True
    return False


# ---------------------------------------------------------------- аккаунт

def fetch_account_state(client):
    """Баланс и позиции с Walt. -> dict (пустой при ошибке)."""
    out = {"free_margin": 0.0, "positions": [], "error": None}
    if client is None:
        out["error"] = "нет клиента"
        return out
    try:
        acc = client.account()
        bal = (acc or {}).get("availableBalance")
        if bal is None:
            bal = (acc or {}).get("availableMarginBalance")
        if bal is None:
            bal = (acc or {}).get("totalAvailableBalance")
        out["free_margin"] = float(bal or 0)
    except Exception as e:
        out["error"] = "баланс: %s" % str(e)[:150]
    try:
        ps = client.positions()
        out["positions"] = ps or []
    except Exception as e:
        out["error"] = (out["error"] or "") + " позиции: %s" % str(e)[:150]
    return out


def positions_to_state(positions):
    """Позиции Walt -> формат, который понимает движок."""
    out = []
    for p in positions or []:
        sym = p.get("symbol") or ""
        side = (p.get("side") or p.get("positionSide") or "").lower()
        if side in ("both", "both_side", ""):
            amt = float(p.get("positionAmt") or 0)
            side = "long" if amt > 0 else "short"
        out.append({
            "symbol": sym,
            "side": side,
            "entry": float(p.get("entryPrice") or 0),
            "size": abs(float(p.get("positionAmt") or 0)),
            "stop_loss": p.get("stopLossPrice"),
            "take_profit": p.get("takeProfitPrice"),
            "unrealized_pnl": float(p.get("unRealizedProfit") or 0),
        })
    return out


# ---------------------------------------------------------------- цикл

def make_walt_client(key, secret):
    """Клиент Walt по ключу пользователя. -> клиент или None."""
    if WaltClient is None:
        return None
    try:
        return WaltClient(key, secret,
                          base_url=(os.environ.get("WALT_BASE_URL")
                                    or "https://bot.mywellat.com"))
    except Exception:
        return None


def make_executor(key, secret, dry_run=None, min_notional=None):
    """Исполнитель под конкретный per-user ключ. -> (executor, info).

    Ключи передаются явно: у каждого пользователя свой агентский ключ,
    в окружении их быть не может. Без ключей фабрика отдаёт dry_run -
    планы считаются, ордера не уходят.
    """
    try:
        import azazel_executor_factory as F
    except Exception as e:
        return None, {"error": "фабрика недоступна: %s" % str(e)[:200],
                      "dry_run": True}
    try:
        return F.make_executor(dry_run=dry_run, min_notional=min_notional,
                                key=key, secret=secret)
    except Exception as e:
        return None, {"error": "фабрика: %s" % str(e)[:200], "dry_run": True}


def run_user(uid, profile, uj, data_dir=None, symbols=None, executor=None,
             dry_run=None, log=None, client=None):
    """Один прогон цикла для одного пользователя. -> отчёт."""
    rep = {"uid": uid, "ok": False, "skipped": False, "reason": "",
           "traded": False, "plans": 0, "executed": 0, "errors": []}
    if TC is None:
        rep["reason"] = "модуль цикла не импортируется"
        return rep
    ok, why = eligible(profile, uj)
    if not ok:
        rep["skipped"] = True
        rep["reason"] = why
        return rep
    key, secret = walt_credentials(uj)
    state = load_state(data_dir, uid) if data_dir else {}
    roll_day(state)

    if client is None:
        client = make_walt_client(key, secret)
        if client is None:
            rep["errors"].append("клиент Walt не создан")

    # Исполнитель: если не подставлен снаружи - создаём под ключ этого
    # пользователя, а не из окружения. Иначе ордер ушёл бы с чужими
    # (или пустыми) кредами.
    own_executor = False
    if executor is None:
        ex, ex_info = make_executor(key, secret, dry_run=dry_run)
        if ex is None:
            rep["errors"].append("исполнитель: %s" % (ex_info or {}).get("error"))
            if ex_info and ex_info.get("dry_run") is False:
                rep["reason"] = "исполнитель не создан: %s" % (ex_info or {}).get("error")
                return rep
        else:
            executor = ex
            own_executor = True
            rep["executor_info"] = ex_info

    acct = fetch_account_state(client)
    if acct.get("error"):
        rep["errors"].append(acct["error"])
    state["free_margin"] = acct.get("free_margin") or 0.0
    state["positions"] = positions_to_state(acct.get("positions"))

    try:
        r = TC.run_cycle(profile=profile, state=state, symbols=symbols,
                          key=key, secret=secret, dry_run=dry_run,
                          executor=executor, client=client)
    except Exception as e:
        rep["reason"] = "цикл упал: %s" % str(e)[:200]
        rep["errors"].append(traceback.format_exc(limit=3)[-400:])
        return rep

    rep["ok"] = bool(r.get("ok"))
    rep["traded"] = bool(r.get("traded"))
    rep["reason"] = r.get("reason") or ""
    rep["plans"] = len(r.get("plans") or [])
    rep["executed"] = len(r.get("executed") or [])
    rep["errors"].extend(r.get("errors") or [])
    rep["report"] = r

    if data_dir:
        if rep["plans"]:
            state["trades_today"] = int(state.get("trades_today") or 0) + rep["executed"]
        save_state(data_dir, uid, state)
    if log is not None:
        log.info("cycle uid=%s plans=%d executed=%d traded=%s reason=%s",
                 uid, rep["plans"], rep["executed"], rep["traded"], rep["reason"][:80])
    return rep


def run_all(data_dir, get_profile, symbols=None, executor=None,
            dry_run=None, log=None, only_uid=None, client=None):
    """Прогнать цикл по всем подходящим пользователям.

    get_profile(uid) -> dict полей профиля Airtable.
    """
    out = {"ran": 0, "skipped": 0, "traded": 0, "reports": []}
    if TC is None:
        out["reason"] = "модуль цикла не импортируется"
        return out
    for uid in list_users(data_dir):
        if only_uid is not None and uid != only_uid:
            continue
        try:
            uj = read_user_json(data_dir, uid)
            try:
                profile = get_profile(uid) or {}
            except Exception:
                profile = {}
            rep = run_user(uid, profile, uj, data_dir=data_dir,
                           symbols=symbols, executor=executor,
                           dry_run=dry_run, log=log, client=client)
            if rep.get("skipped"):
                out["skipped"] += 1
            else:
                out["ran"] += 1
                if rep.get("traded"):
                    out["traded"] += 1
            out["reports"].append(rep)
        except Exception:
            if log is not None:
                log.exception("cycle uid=%s crashed", uid)
            out["reports"].append({"uid": uid, "ok": False, "reason": "сбой"})
    return out
