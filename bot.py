
# -*- coding: utf-8 -*-
# Azazel Trader - bot-nastavnik. Airtable API (2 tablicy) + Telegram Bot API (long polling).
# Tolko standartnaya biblioteka Python 3.9+. Bez zavisimostey.
import os, json, time, urllib.request, urllib.error, urllib.parse, datetime, sys, logging
import socket, ssl, http.client, signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("azabot")


def _load_env(path):
    """Chitaet KEY=VALUE iz .env v okruzhenie. Bez zavisimostey."""
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


_load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TOKEN  = os.environ.get("AZABOT_TOKEN", "").strip()
BASE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
CFG    = json.load(open(BASE, encoding="utf-8"))

USERS_DB  = os.environ.get("AIRTABLE_USERS_TABLE") or CFG["airtable_users_table"]
EVENTS_DB = os.environ.get("AIRTABLE_EVENTS_TABLE") or CFG["airtable_events_table"]
ADMIN_ID  = int(os.environ.get("ADMIN_TG_ID") or CFG.get("admin_tg_id") or 0)
TG_API    = "https://api.telegram.org/bot" + TOKEN


TG_HOST = "api.telegram.org"
# Pul IP DC Telegram: pervyye tri stabilno otvechayut, ostalnyye - rezerv.
TG_IPS = ["149.154.167.220", "149.154.166.110", "149.154.161.145",
           "149.154.167.222", "149.154.175.100", "149.154.167.51"]
_tg = {"idx": 0, "ip": TG_IPS[0], "bad": 0}

_orig_gai = socket.getaddrinfo


def _pinned_gai(host, port, *a, **k):
    # Обычный DNS работает стабильнее: жёсткое закрепление за IP Telegram
    # давало SSL RECORD_LAYER_FAILURE и таймауты.
    return _orig_gai(host, port, *a, **k)


def _tg_rotate():
    """Next IP from the pool."""
    n = len(TG_IPS)
    _tg["idx"] = (_tg["idx"] + 1) % n
    _tg["ip"] = TG_IPS[_tg["idx"]]
    return _tg["ip"]


_STOP = False


def _tg_call(method, path, payload=None, timeout=45):
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"Content-Type": "application/json"}
    err = None
    # 2 circles over the pool: 6 addrs x 2 = 12 attempts
    for attempt in range(len(TG_IPS) * 2):
        try:
            socket.getaddrinfo = _pinned_gai
            req = urllib.request.Request("https://" + TG_HOST + path, method="POST",
                                         data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as f:
                raw = f.read().decode()
            _tg["bad"] = 0
            try:
                return f.status, json.loads(raw)
            except Exception:
                return f.status, raw
        except urllib.error.HTTPError as e:
            # 409 = predydushchiy long-poll eshche ne osvobodil ochered Telegram.
            # Eto ne setevaya oshibka: rotatsiya IP zdesh ne pomogaet.
            if e.code == 409:
                try:
                    body = json.loads(e.read().decode())
                except Exception:
                    body = {"description": "conflict"}
                return 409, body
            err = e
            _tg["bad"] += 1
            nxt = _tg_rotate()
            log.warning("TG net %s (bad=%d), switch to %s: %s",
                        method, _tg["bad"], nxt, e)
            time.sleep(0.6)
        except Exception as e:
            if _STOP:
                log.info("Ostanovka vo vremya zaprosa - prekryvaem")
                return None, "stopping"
            err = e
            _tg["bad"] += 1
            nxt = _tg_rotate()
            log.warning("TG net %s (bad=%d), switch to %s: %s",
                        method, _tg["bad"], nxt, e)
            time.sleep(0.6)
        finally:
            socket.getaddrinfo = _orig_gai
    return None, str(err)

def _req(method, url, body, headers, retries=5, timeout=90):
    delay = 1.0
    last = None
    for attempt in range(retries):
        if body is None:
            payload = None
        elif isinstance(body, (bytes, bytearray)):
            payload = bytes(body)
        else:
            payload = json.dumps(body).encode()
        r = urllib.request.Request(url, method=method, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(r, timeout=30) as f:
                return f.status, json.loads(f.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            last = (e.code, raw)
            if e.code == 429:
                wait = delay
                try: wait = float(json.loads(raw).get("retry_after", delay))
                except Exception: pass
                log.warning("API 429, zhdym %.1f s", wait)
                time.sleep(min(wait, 30)); delay = min(delay*1.8, 15); continue
            if e.code in (500, 502, 503, 504):
                log.warning("API %s, povtor", e.code)
                time.sleep(delay); delay = min(delay*1.8, 15); continue
            return e.code, raw
        except Exception as e:
            last = (None, str(e))
            log.warning("Set obryv: %s", e)
            time.sleep(delay); delay = min(delay*1.8, 15)
    return last if last else (None, "unknown")

AT_TOKEN = os.environ.get("AIRTABLE_TOKEN", "").strip()
AT_BASE  = os.environ.get("AIRTABLE_BASE_ID") or CFG.get("airtable_base_id", "")
AT_API   = "https://api.airtable.com/v0"

def _at(method, path, body=None, retries=4):
    delay = 1.0
    last = None
    for _ in range(retries):
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        hdrs = {"Authorization": "Bearer " + AT_TOKEN, "Content-Type": "application/json"}
        r = urllib.request.Request(AT_API + path, method=method, data=payload, headers=hdrs)
        try:
            with urllib.request.urlopen(r, timeout=30) as f:
                return f.status, json.loads(f.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            last = (e.code, raw)
            if e.code == 429:
                wait = delay
                try: wait = float(json.loads(raw).get("retryAfter") or delay)
                except Exception: pass
                log.warning("Airtable 429, zhdym %.1f s", wait)
                time.sleep(min(wait, 30)); delay = min(delay*1.8, 15); continue
            if e.code in (500, 502, 503, 504):
                log.warning("Airtable %s, povtor", e.code)
                time.sleep(delay); delay = min(delay*1.8, 15); continue
            return e.code, raw
        except Exception as e:
            last = (None, str(e))
            log.warning("Airtable set: %s", e)
            time.sleep(delay); delay = min(delay*1.8, 15)
    return last if last else (None, "unknown")

def at(method, path, body=None):
    s, d = _at(method, path, body)
    if s not in (200, 201):
        log.error("Airtable %s %s -> %s %s", method, path, s, str(d)[:300])
        return None
    return d

def db_create(table, fields):
    """Sozdaet zapis. table - ID ili imya tablicy, fields - ploskij dict Airtable."""
    r = at("POST", "/" + AT_BASE + "/" + table, {"records": [{"fields": fields}]})
    if not r: return None
    recs = r.get("records") or []
    return recs[0] if recs else None

def db_query(table, formula=None, page_size=100, sort=None):
    params = []
    if formula: params.append("filterByFormula=" + urllib.parse.quote(formula))
    if sort: params.append("sort%5B0%5D%5Bfield%5D=" + urllib.parse.quote(sort[0]))
    if sort: params.append("sort%5B0%5D%5Bdirection%5D=" + urllib.parse.quote(sort[1]))
    params.append("maxRecords=" + str(page_size))
    path = "/" + AT_BASE + "/" + table + "?" + "&".join(params)
    return at("GET", path)

def db_query_uid(table, uid, page_size=1):
    return db_query(table, "{Telegram ID} = " + str(uid), page_size=page_size)

def page_update(table, rec_id, fields):
    return at("PATCH", "/" + AT_BASE + "/" + table + "/" + rec_id, {"fields": fields})

def tg(method, payload=None, retries=3):
    if method == "getUpdates":
        retries = max(retries, 12)
    path = "/bot" + TOKEN + "/" + method
    to = 40 if method == "getUpdates" else 30
    delay = 1.0
    for _ in range(retries):
        if _STOP:
            return None
        s, d = _tg_call("POST", path, payload, timeout=to)
        if s == 200: return d
        if s is None:
            log.warning("TG %s net: %s", method, str(d)[:150])
            time.sleep(delay); delay = min(delay*2, 8); continue
        log.warning("TG %s -> %s", method, s)
        if s == 429:
            try: time.sleep(float(d["parameters"]["retry_after"]))
            except Exception: time.sleep(3)
            continue
        if s == 409:
            log.warning("TG 409 - ochered zanyat predydushchim long-poll, zhdu 20 s")
            time.sleep(20); continue
        return {"ok": False, "description": str(d)[:200]}
    return None

APP_URL = CFG.get("app_url", "")
# Direct link na mini-app Walt: otkryvaet mini-prilozhenie s ekranom oplaty, a ne chat bota.
WALT_URL = "https://t.me/wallet/start?startapp="


def send_terminal_kb(chat_id):
    """Klaviatura s web_app-knopkoy: tolko iz nee sendData realno rabotaet."""
    if not APP_URL:
        return None
    payload = {
        "chat_id": chat_id,
        "text": "Terminal",
        "reply_markup": {"keyboard": [[{"text": "\U0001F680 Otkryt terminal", "web_app": {"url": APP_URL}}]]},
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "remove_keyboard": False,
    }
    return tg("sendMessage", payload)

def menu_buttons():
    """Glavnoe menu v stile Walt: mini app + razdely."""
    btns = []
    if APP_URL:
        btns.append(("🚀 Открыть терминал", APP_URL, "web_app"))
    btns.append(("⚙️ Настройки", "settings"))
    btns.append(("📊 Статус", "check_pay"))
    btns.append(("💎 Подписка", "pay_usd"))
    btns.append(("🆘 Помощь", "help"))
    return btns


def send(chat_id, text, buttons=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if buttons:
        rows, cur = [], []
        for b in buttons:
            if len(b) >= 3 and b[2] == "web_app":
                if cur:
                    rows.append(cur); cur = []
                rows.append([{"text": b[0], "web_app": {"url": b[1]}}])
                continue
            if len(b) >= 3 and b[2] == "url":
                if cur:
                    rows.append(cur); cur = []
                rows.append([{"text": b[0], "url": b[1]}])
                continue
            cur.append({"text": b[0], "callback_data": b[1]})
            if len(cur) == 2:
                rows.append(cur); cur = []
        if cur: rows.append(cur)
        payload["reply_markup"] = {"inline_keyboard": rows}
    return tg("sendMessage", payload)

def answer(cb_id, text=""):
    return tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

from steps import STEPS
from algo_config import algo_defaults, algo_drift_text, algo_status_line, ALGO_APPLY, ALGO_SRC

SESS = {}

def menu_text(uid, name, username, lang="ru"):
    return ("<b>🧠 Azazel Trader</b>\n"
        + "Пользователь: <b>" + (name or "Пользователь") + "</b>\n"
        + "Язык: " + lang + "\n\n"
        + "<b>Быстрый доступ</b>\n"
        "Параметры → /params\n"
        "Статус и подписка → /status\n"
        "Настройка с нуля → /start\n\n"
        + "<b>Терминал</b>\n"
        + "Мини-приложение: рынок, отбор точек входа, стопы и разбор сделок.")


def ask(chat_id, uid, i):
    key, q, why, btns, typ, dflt = STEPS[i]
    SESS[uid]["step"] = i
    txt = "<b>"+q+"</b>\n\n<i>"+why+"</i>"
    if typ == "text":
        return send(chat_id, txt, [("Пропустить", "skip")])
    return send(chat_id, txt, btns)

def log_event(kind, tg_id, name, source="bot", amount=None, tariff=None, details=""):
    fields = {
        "Событие": kind,
        "Тип": kind,
        "Дата": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "Пользователь": name or "",
        "Telegram ID": tg_id,
        "Источник": source,
        "Детали": (details or "")[:1900],
    }
    if amount is not None: fields["Сумма $"] = amount
    if tariff: fields["Тариф"] = tariff
    return db_create(EVENTS_DB, fields)


def notify_admin(text):
    if ADMIN_ID: send(ADMIN_ID, text)

def finish(chat_id, uid):
    s = SESS[uid]; d = s["data"]; rec = s.get("page")
    AD = algo_defaults()
    fields = {
        "Статус": "готов",
        "Тир депозита": d.get("tier", "средний"),
        "Режим": d.get("mode", "scalp_daily"),
        "Плечо альты": float(d.get("lev_alts", 5)),
        "Плечо BTC/ETH": float(d.get("lev_btc", 10)),
        "Стоп альты %": float(d.get("stop_alts", AD.get("Стоп альты %", 3))),
        "Стоп BTC/ETH %": float(d.get("stop_btc", AD.get("Стоп BTC/ETH %", 1.5))),
        "ATR-множитель": float(d.get("atr", AD.get("ATR-множитель", 1.0))),
        "Мин R:R": float(d.get("rr", AD.get("Мин R:R", 2))),
        "BTC-фильтр %": float(d.get("btc_filter", AD.get("BTC-фильтр %", 2))),
        "Блок лонга фандинг %": float(d.get("funding", AD.get("Блок лонга фандинг %", 0.05))),
        "Дневной лимит убытка $": float(d.get("loss_limit", AD.get("Дневной лимит убытка $", 15))),
        "Стопов в день": int(float(d.get("max_stops", AD.get("Стопов в день", 3)))),
        "Correlation cap": int(float(d.get("corr_cap", AD.get("Correlation cap", 2)))),
        "Сделок в день": int(float(d.get("max_trades", AD.get("Сделок в день", 5)))),
        "Таймфреймы": d.get("timeframes", "15m,1h,4h"),
        "Автоподтверждение": d.get("autoconfirm") == "True",
        "Прогресс настройки": 100,
        "Кошелёк Walt": d.get("wallet", ""),
    }
    if rec: page_update(USERS_DB, rec, fields)
    log_event("параметры", uid, s.get("name", ""), details=json.dumps(d, ensure_ascii=False))
    notify_admin("Настроен профиль: " + s.get("name", "") + " (id " + str(uid) + ") | "
                 + d.get("tier", "") + " | " + d.get("mode", ""))
    return send(chat_id,
        "<b>Готово — параметры сохранены.</b>\n\n"
        + "Тир: " + d.get("tier", "") + " · Режим: " + d.get("mode", "") + "\n"
        + "Плечо: альты " + d.get("lev_alts", "") + "x · BTC/ETH " + d.get("lev_btc", "") + "x\n"
        + "Стопы: альты " + d.get("stop_alts", "") + "% · BTC/ETH " + d.get("stop_btc", "") + "% · ATR×" + d.get("atr", "") + "\n"
        + "R:R 1:" + d.get("rr", "") + " · BTC-фильтр " + d.get("btc_filter", "") + "% · блок лонга " + d.get("funding", "") + "%/ч\n"
        + "Лимит: −$" + d.get("loss_limit", "") + "/день или " + d.get("max_stops", "") + " стопа · корреляция ≤" + d.get("corr_cap", "") + "\n"
        + "Сделок в день: до " + d.get("max_trades", "") + " · таймфреймы " + d.get("timeframes", "") + "\n"
        + "Автоподтверждение: " + ("включено" if d.get("autoconfirm") == "True" else "выключено") + "\n\n"
        + "Дальше — подписка. Нажми кнопку, списание через Walt.",
        [("$29/мес", "pay_usd"), ("9.5 TON/мес", "pay_ton")])


HELP = ("<b>Azazel Trader</b> — автономный торговый терминал.\n\n"
    "Я соберу твои параметры, объясню каждый и сохраню. Дальше использую их в каждом цикле.\n\n"
    "<b>Команды</b>\n/start — начать настройку\n/params — твои параметры\n/status — подписка и цикл\n"
    "/app — открыть терминал\n/skills — доступные скилы\n/menu — профиль и быстрые ссылки\n/help — справка\n\n"
    "Вопросы — просто пиши текстом, я пойму.")

SKILLS_TXT = ("<b>Доступные скилы</b>\n\n"
    "• <b>AI Slave</b> — оценка тебя по истории переписки: бирка с фото, ценником и описанием лота.\n\n"
    "Остальные модули работают внутри терминала и отдельного включения не требуют.")

def cmd_app(chat_id, uid):
    """Mini App: otkrytie termina v Telegram."""
    if not APP_URL:
        return send(chat_id, "Mini App poka nedostupen.")
    send_terminal_kb(chat_id)
    return send(chat_id,
        "<b>🚀 Azazel Trader</b>\n\n"
        + "Avtonomnyy torgovyy terminal v mini app: rynok, otbor tochek, vhody, stopy, razbor sdelok.\n\n"
        + "Nastroyki zdesz zhe — tyom zhe polzovatel, tot zhe Airtable.",
        [("Открыть терминал", APP_URL, "web_app")])


def cmd_params(chat_id, uid):
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    if not rows:
        return send(chat_id, "Параметров пока нет. Напиши /start чтобы настроить.")
    p = rows[0].get("fields") or {}
    def g(k, sel=False):
        v = p.get(k)
        if v is None or v == "": return "—"
        if sel: return str(v)
        if isinstance(v, bool): return "да" if v else "нет"
        return str(v)
    return send(chat_id,
        "<b>Твои параметры</b>\n\n"
        + "Тир: " + g("Тир депозита", 1) + " · Режим: " + g("Режим", 1) + "\n"
        + "Плечо: " + str(g("Плечо альты")) + "x альты / " + str(g("Плечо BTC/ETH")) + "x BTC-ETH\n"
        + "Стопы: " + str(g("Стоп альты %")) + "% / " + str(g("Стоп BTC/ETH %")) + "% · ATR×" + str(g("ATR-множитель")) + "\n"
        + "R:R 1:" + str(g("Мин R:R")) + " · фильтр " + str(g("BTC-фильтр %")) + "% · блок лонга " + str(g("Блок лонга фандинг %")) + "%/ч\n"
        + "Лимит −$" + str(g("Дневной лимит убытка $")) + "/день · стопов " + str(g("Стопов в день")) + " · корреляция ≤" + str(g("Correlation cap")) + "\n"
        + "Сделок: до " + str(g("Сделок в день")) + " · таймфреймы " + g("Таймфреймы") + "\n"
        + "Автоподтверждение: " + str(g("Автоподтверждение")) + "\n"
        + "Кошелёк: " + g("Кошелёк Walt")
        + chr(10) * 2 + algo_status_line()
        + algo_drift_text(p),
        [("Настроить заново", "restart"), ("Подписка", "check_pay")])


def cmd_status(chat_id, uid):
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    if not rows: return send(chat_id, "Сначала настройка — /start.")
    p = rows[0].get("fields") or {}
    st = p.get("Статус") or "—"
    sub = p.get("Подписка") or "нет"
    prog = p.get("Прогресс настройки")
    return send(chat_id,
        "<b>Статус</b>\n\n"
        + "Настройка: " + str(st) + " (" + str(prog if prog is not None else 0) + "%)\n"
        + "Подписка: " + str(sub) + "\n"
        + "Автономный цикл: " + ("включён" if sub == "активна" else "выключен — нужна подписка")
        + "\n" + ("Параметры заданы — цикл использует их."
                  if prog is not None and int(prog or 0) >= 100
                  else "Параметры ещё не заданы — /start."),
        [("Перейти в Walt", WALT_URL, "url")])


def cmd_algo(chat_id, uid):
    """Nastroyki algoritma torgovli: svodka + knopki."""
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    p = (rows[0].get("fields") or {}) if rows else {}
    def g(k, sel=False):
        v = p.get(k)
        if v is None or v == "": return "\u2014"
        if sel: return str(v)
        if isinstance(v, bool): return "\u0434\u0430" if v else "\u043d\u0435\u0442"
        return str(v)
    head = ("\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0430\u043b\u0433\u043e\u0440\u0438\u0442\u043c\u0430 \u0442\u043e\u0440\u0433\u043e\u0432\u043b\u0438"
            + ("" if rows else " \u2014 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 \u0435\u0449\u0451 \u043d\u0435 \u0441\u043e\u0431\u0440\u0430\u043d\u044b"))
    body = ("\u0422\u0438\u0440: " + g("\u0422\u0438\u0440 \u0434\u0435\u043f\u043e\u0437\u0438\u0442\u0430", 1)
            + " \u00b7 \u0420\u0435\u0436\u0438\u043c: " + g("\u0420\u0435\u0436\u0438\u043c", 1)
            + "\n\u041f\u043b\u0435\u0447\u043e: " + g("\u041f\u043b\u0435\u0447\u043e \u0430\u043b\u044c\u0442\u044b") + "x / " + g("\u041f\u043b\u0435\u0447\u043e BTC/ETH") + "x"
            + "\n\u0421\u0442\u043e\u043f\u044b: " + g("\u0421\u0442\u043e\u043f \u0430\u043b\u044c\u0442\u044b %") + "% / " + g("\u0421\u0442\u043e\u043f BTC/ETH %") + "%"
            + " \u00b7 R:R 1:" + g("\u041c\u0438\u043d R:R"))
    btns = [("\u2699\ufe0f \u041d\u0430\u0441\u0442\u0440\u043e\u0438\u0442\u044c \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b", "settings")]
    if APP_URL:
        btns.append(("\U0001f680 \u041e\u0442\u043a\u0440\u044b\u0442\u044c \u0442\u0435\u0440\u043c\u0438\u043d\u0430\u043b", APP_URL, "web_app"))
    btns.append("\U0001f4ca \u0421\u0442\u0430\u0442\u0443\u0441")
    btns.append("\U0001f4c6 \u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b")
    return send(chat_id, "<b>" + head + "</b>\n\n" + body, btns)

def cmd_report(chat_id, uid):
    if not ADMIN_ID or uid != ADMIN_ID:
        return send(chat_id, "Нет доступа.")
    res = db_query(EVENTS_DB, page_size=100, sort=("Дата", "desc"))
    rows = (res or {}).get("records", [])
    installs = pays = ready = 0
    revenue = 0.0
    for r in rows:
        pr = r.get("fields") or {}
        typ = pr.get("Тип") or ""
        amt = pr.get("Сумма $") or 0
        if typ == "установка": installs += 1
        if typ in ("оплата", "продление"): pays += 1; revenue += amt
        if typ == "параметры": ready += 1
    conv = ("%.0f%%" % (pays * 100.0 / installs)) if installs else "—"
    return send(chat_id,
        "<b>Статистика Azazel Trader</b>\n\n"
        + "Установок: " + str(installs) + "\n"
        + "Настроено до конца: " + str(ready) + "\n"
        + "Оплат: " + str(pays) + "\n"
        + "Выручка: $" + ("%.2f" % revenue) + "\n"
        + "Конверсия: " + conv)


def cb(chat_id, uid, data):
    """Vneshnij obrabotchik: sozdaet sessiyu pri neobhodimosti, zashchishchyot ot oshibok."""
    try:
        if uid not in SESS:
            pid, _created = ensure_user(uid, "", "")
            SESS[uid] = {"tg_id": uid, "step": 0, "data": {}, "page": pid, "name": ""}
            log.info("SESS vosstanovlen dlya uid %s (klika posle restarta)", uid)
        return _cb_inner(chat_id, uid, data)
    except Exception as e:
        log.exception("cb err %s: %s", data, e)
        return send(chat_id, "Что-то пошло не так, попробуй ещё раз. Настройки не потеряны.")


def _cb_inner(chat_id, uid, data):
    if data == "settings":
        return cmd_params(chat_id, uid)
    if data == "help":
        return send(chat_id, HELP)
    if data == "menu":
        return send(chat_id, menu_text(uid, "", ""), menu_buttons())
    if data.startswith("ans:"):
        key, val = data[4:].split("=", 1)
        s = SESS[uid]; s["data"][key] = val
        if s["step"] + 1 < len(STEPS): return ask(chat_id, uid, s["step"] + 1)
        return finish(chat_id, uid)
    if data == "skip":
        s = SESS[uid]
        key, _, _, _, _, dflt = STEPS[s["step"]]
        s["data"][key] = dflt
        if s["step"] + 1 < len(STEPS): return ask(chat_id, uid, s["step"] + 1)
        return finish(chat_id, uid)
    if data == "view_params": return cmd_params(chat_id, uid)
    if data == "wallet_new":
        s = SESS.setdefault(uid, {"tg_id": uid, "step": 0, "data": {}, "page": None, "name": ""})
        s["wallet_only"] = True
        s["step"] = WALLET_IDX
        s["data"] = {}
        return ask(chat_id, uid, WALLET_IDX)
    if data == "check_pay": return cmd_status(chat_id, uid)
    if data == "restart":
        SESS[uid]["step"] = 0; SESS[uid]["data"] = {}
        return ask(chat_id, uid, 0)
    if data in ("pay_usd", "pay_ton"):
        tariff = "$29/мес" if data == "pay_usd" else "9.5 TON/мес"
        return send(chat_id,
            "<b>Подписка " + tariff + "</b>\n\nСписание идёт через Walt — открой, подтверди, доступ откроется.\n\n"
            + "Кошелёк: <code>" + CFG.get("wallet", "") + "</code>",
            [("Открыть Walt", WALT_URL, "url")])
    if data == "walt_open":
        return send(chat_id,
            "Открой Walt → подключи бота как AI-агента → подтверди подписку.\n\n"
            + "Кошелёк для списания:\n<code>" + CFG.get("wallet", "") + "</code>\n\n"
            + "После подтверждения напиши «готово» — проверю статус и включу автономный цикл.",
            [("Открыть Walt", WALT_URL, "url")])
    return None

def text_handler(chat_id, uid, txt):
    s = SESS.get(uid)
    low = txt.strip().lower()
    # Rezhim podklyucheniya koshelyka: rabotaet vsegda, dazhe bez sessii nastroyki.
    if s and s.get("wallet_only"):
        if low in ("пропустить", "skip"):
            return send(chat_id, "Нужен адрес — без него терминал не увидит баланс и позиции.")
        if not _ton_addr_ok(txt):
            return send(chat_id, "Это не похоже на TON-адрес.\n\n"
                + "Пришли адрес кошелька целиком — например <code>UQAintXt7mpJqxnTXJF...</code>")
        return finish_wallet(chat_id, uid, txt.strip())
    if not s or s["step"] >= len(STEPS):
        if low in ("параметры", "мои параметры", "/params"): return cmd_params(chat_id, uid)
        if low in ("статус", "/status"): return cmd_status(chat_id, uid)
        if low in ("статистика", "/report", "отчёт", "отчет"): return cmd_report(chat_id, uid)
        if low in ("скилы", "/skills"): return send(chat_id, SKILLS_TXT)
        if low in ("меню", "/menu"): return send(chat_id, menu_text(uid, s.get("name","") if s else "", ""))
        if low in ("помощь", "/help"): return send(chat_id, HELP)
        if low in ("готово", "подключил", "оплатил"):
            res = db_query_uid(USERS_DB, uid)
            rows = (res or {}).get("records", [])
            if rows:
                page_update(USERS_DB, rows[0]["id"], {"Подписка": "активна", "Статус": "активен"})
                log_event("оплата", uid, s.get("name", "") if s else "", details="подтверждено клиентом")
                notify_admin("Оплата: " + (s.get("name", "") if s else "") + " (id " + str(uid) + ")")
                return send(chat_id, "Принято. Подписка активна, автономный цикл включён.\n\n"
                    + "Отчёты придут по расписанию: рынок, сделки, разбор.")
            return send(chat_id, "Сначала пройди настройку: /start")
        return send(chat_id, "Не понял. /help — все команды. Или «параметры», чтобы посмотреть настройки.")
    i = s["step"]
    key, q, why, btns, typ, dflt = STEPS[i]
    if typ == "text":
        s["data"][key] = txt.strip()
        if i + 1 < len(STEPS): return ask(chat_id, uid, i + 1)
        return finish(chat_id, uid)
    for label, val in btns:
        ll = label.lower()
        if low == ll or low == val.lower() or (val.lower() in low) or (ll in low):
            s["data"][key] = val
            if i + 1 < len(STEPS): return ask(chat_id, uid, i + 1)
            return finish(chat_id, uid)
    return send(chat_id, "Выбери вариант на кнопках — или напиши своими словами, я пойму.")

def ensure_user(uid, name, username):
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    if rows: return rows[0]["id"], False
    r = db_create(USERS_DB, {
        "Name": name or "Аноним",
        "Telegram ID": uid,
        "Username": username or "",
        "Статус": "в процессе",
        "Подписка": "нет",
        "Источник": "bot",
        "Прогресс настройки": 0,
        "Дата": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return (r.get("id") if r else None), True


def start(chat_id, uid, name, username):
    pid, created = ensure_user(uid, name, username)
    SESS[uid] = {"tg_id": uid, "step": 0, "data": {}, "page": pid, "name": name}
    send(chat_id, menu_text(uid, name, username), menu_buttons())
    send_terminal_kb(chat_id)
    if created:
        log_event("установка", uid, name, details="старт настройки через бота")
        notify_admin("Новая установка: " + name + " (id " + str(uid) + ")")
        send(chat_id, "<b>Привет. Я Azazel Trader.</b>\n\n"
            + "За 15 вопросов соберу твои параметры и настрою автономный цикл. Каждый параметр объясню — "
            + "чтобы ты понимал, почему такое значение, а не просто принял его.\n\nПогнали:")
    else:
        res = db_query_uid(USERS_DB, uid)
        st = (((res or {}).get("records") or [{}])[0].get("fields") or {}).get("Статус")
        if st in ("готов", "активен"):
            return send(chat_id, "С возвращением. Параметры сохранены — показать, поменять или подписка?",
                [("Мои параметры", "view_params"), ("Настроить заново", "restart"), ("Подписка", "check_pay")])
    return ask(chat_id, uid, 0)

def handle_webapp_data(chat_id, uid, data_str):
    """Obrabotka web_app_data iz Mini App: sverka podpisi initData + komanda."""
    import hmac, hashlib, urllib.parse
    try:
        raw = urllib.parse.parse_qs(data_str)
        if "hash" in raw:
            received = raw["hash"][0]
            check = raw.get("check_string", [""])[0]
            secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
            calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(calc, received):
                log.warning("web_app_data: bad signature, otklonen")
                return send(chat_id, "Не удалось проверить подпись запроса.")
        payload = json.loads(data_str)
    except Exception:
        payload = {"cmd": str(data_str or "").strip()}
    cmd = str(payload.get("cmd") or "").strip().lower().lstrip("/")
    log.info("web_app_data from uid %s: %s", uid, cmd)
    if cmd == "start":
        return start(chat_id, uid, "", "")
    if cmd == "params":
        return cmd_params(chat_id, uid)
    if cmd == "status":
        return cmd_status(chat_id, uid)
    if cmd == "report":
        return cmd_report(chat_id, uid)
    if cmd in ("menu", "home"):
        return send(chat_id, menu_text(uid, "", ""), menu_buttons())
    return send(chat_id, "Не понял команду: " + cmd)
# ── Кошелёк Walt: отдельный вход до оплаты ──
WALLET_IDX = next((i for i, s_ in enumerate(STEPS) if s_[0] == "wallet"), len(STEPS) - 1)

def _ton_addr_ok(a):
    """Prianyat' friendly (UQ../EQ..) i raw (0:.. / -1:..) adresa TON."""
    a = (a or "").strip()
    if not a: return False
    if a.startswith("0:") or a.startswith("-1:"):
        body = a.split(":", 1)[1]
        return len(body) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in body)
    if a.startswith(("UQ", "EQ")):
        return 46 <= len(a) <= 66 and all(ch.isalnum() or ch in "-_" for ch in a)
    return False

def cmd_wallet(chat_id, uid, name, username):
    """Podklyuchenie koshelyka — otdelno ot nastroyki i ot oplaty."""
    pid, _created = ensure_user(uid, name, username)
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    cur = ((rows[0].get("fields") or {}).get("Кошелёк Walt") or "") if rows else ""
    if cur:
        return send(chat_id,
            "<b>Кошелёк уже подключён</b>\n\n<code>" + cur + "</code>\n\n"
            + "Нужно поменять? Пришли новый адрес — заменю.",
            [("Подключить другой", "wallet_new"), ("Оплатить подписку", "pay_usd")])
    SESS[uid] = {"tg_id": uid, "step": WALLET_IDX, "data": {}, "page": pid,
                 "name": name, "wallet_only": True}
    return ask(chat_id, uid, WALLET_IDX)

def finish_wallet(chat_id, uid, addr):
    """Zapis koshelyka v Airtable i perekhod k oplate."""
    s = SESS.get(uid) or {}
    res = db_query_uid(USERS_DB, uid)
    rows = (res or {}).get("records", [])
    rec = rows[0]["id"] if rows else s.get("page")
    if rec:
        page_update(USERS_DB, rec, {"Кошелёк Walt": addr})
    log_event("кошелёк", uid, s.get("name", ""), details=addr)
    notify_admin("Кошелёк подключён: " + (s.get("name", "") or str(uid)) + " -> " + addr)
    s.pop("wallet_only", None)
    s["data"]["wallet"] = addr
    return send(chat_id,
        "<b>Кошелёк записан.</b>\n\n<code>" + addr + "</code>\n\n"
        + "Теперь подписка — после неё включается автономный цикл.",
        [("$29/мес", "pay_usd"), ("9.5 TON/мес", "pay_ton")])


def handle_start_payload(chat_id, uid, name, username, payload):
    """Razbor /start <payload> iz deep-link Mini App."""
    p = (payload or "").strip().lower().lstrip("/")
    log.info("start payload: %s (uid %s)", p, uid)
    if p == "algo":
        return cmd_algo(chat_id, uid)
    if p == "params":
        return cmd_params(chat_id, uid)
    if p == "status":
        return cmd_status(chat_id, uid)
    if p == "report":
        return cmd_report(chat_id, uid)
    if p == "menu":
        send_terminal_kb(chat_id)
        return send(chat_id, menu_text(uid, name, username), menu_buttons())
    if p == "setup":
        return start(chat_id, uid, name, username)
    if p == "wallet":
        return cmd_wallet(chat_id, uid, name, username)
    send_terminal_kb(chat_id)
    return start(chat_id, uid, name, username)

def _on_signal(signum, frame):
    global _STOP
    _STOP = True
    log.warning("Poluchen signal %s - zavershaem graceful", signum)


def main():
    for _sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(_sig, _on_signal)
        except Exception:
            pass
    me = None
    for attempt in range(120):
        me = tg("getMe")
        if me and me.get("ok"):
            break
        log.warning("getMe ne srabotal (popytka %d), zhdem 15 s", attempt + 1)
        time.sleep(15)
    if not me or not me.get("ok"):
        log.error("getMe ne srabotal - prover token ili set v .env"); return
    log.info("Bot zapushchen: @%s | admin=%s", me["result"].get("username"), ADMIN_ID)
    _aq = db_query(EVENTS_DB, page_size=1)
    if _aq:
        log.info("Airtable dostupen: tablica sobytiy otvechaet")
    else:
        log.warning("Airtable nedostupen - zapisi ne sohranayutsya, prover AIRTABLE_TOKEN i bazu v .env")
    offset = 0
    while not _STOP:
        res = tg("getUpdates", {"offset": offset, "timeout": 10,
                                 "allowed_updates": ["message", "callback_query", "web_app_data"]})
        if _STOP:
            break
        if res is None:
            time.sleep(2)
            continue
        if not (res or {}).get("result"):
            continue
        for u in (res or {}).get("result", []):
            offset = u["update_id"] + 1
            try:
                if "callback_query" in u:
                    cq = u["callback_query"]
                    answer(cq["id"])
                    cb(cq["message"]["chat"]["id"], cq["from"]["id"], cq["data"])
                elif "web_app_data" in u:
                    wd = u["web_app_data"]
                    wuid = wd.get("from", {}).get("id", 0)
                    handle_webapp_data(wuid, wuid, wd.get("data", ""))
                elif "message" in u:
                    m = u["message"]
                    chat_id = m["chat"]["id"]; uid = m["from"]["id"]
                    name = m["from"].get("first_name", "")
                    username = m["from"].get("username", "")
                    txt = (m.get("text") or "").strip()
                    if not txt: continue
                    if txt.startswith("/"):
                        cmd = txt.split()[0].lower()
                        if cmd == "/start":
                            parts = txt.split(None, 1)
                            payload = parts[1].strip() if len(parts) > 1 else ""
                            handle_start_payload(chat_id, uid, name, username, payload)
                        elif cmd == "/params": cmd_params(chat_id, uid)
                        elif cmd == "/status": cmd_status(chat_id, uid)
                        elif cmd == "/report": cmd_report(chat_id, uid)
                        elif cmd == "/skills": send(chat_id, SKILLS_TXT)
                        elif cmd == "/menu": send(chat_id, menu_text(uid, name, username), menu_buttons())
                        elif cmd in ("/app", "/terminal"): cmd_app(chat_id, uid)
                        elif cmd in ("/wallet", "/subscribe"): cmd_status(chat_id, uid)
                        elif cmd in ("/help", "/support"): send(chat_id, HELP)
                        continue
                    if uid not in SESS:
                        pid, created = ensure_user(uid, name, username)
                        SESS[uid] = {"tg_id": uid, "step": 0, "data": {}, "page": pid, "name": name}
                        if created:
                            log_event("установка", uid, name, details="вход без /start")
                            notify_admin("Новая установка: " + name + " (id " + str(uid) + ")")
                    text_handler(chat_id, uid, txt)
            except Exception as e:
                log.exception("handler err: %s", e)
        time.sleep(0.5)
    log.info("Bot ostanovlen")

if __name__ == "__main__":
    if not TOKEN or not AT_TOKEN or not AT_BASE:
        log.error("AZABOT_TOKEN, AIRTABLE_TOKEN i AIRTABLE_BASE_ID obazatelny"); sys.exit(1)
    main()
