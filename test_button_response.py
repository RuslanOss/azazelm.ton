# -*- coding: utf-8 -*-
"""Живой harness отклика кнопок.

Импортирует bot.py оффлайн (сеть заглушена), затем кликает КАЖДУЮ
кнопку, которую бот реально отправляет, и проверяет:
  1) обработчик не бросил исключение,
  2) вернул не-None (то есть кнопка не "повисла"),
  3) мастер продвигается по шагам.

Кнопки собираются из реального кода: send(...) в bot.py + STEPS в steps.py.
"""
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("AZABOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("AIRTABLE_TOKEN", "patTEST")
os.environ.setdefault("AIRTABLE_BASE_ID", "appTEST")

import azazel_test_guard as _guard  # izolyaciya ot boevoy Airtable/Telegram
import bot
_guard.protect_bot(bot)
from steps import STEPS

UID = 8459508879
CHAT = UID

SENT = []
def fake_tg(method, payload=None, retries=3):
    SENT.append((method, (payload or {}).get("text", "")))
    return {"ok": True}
bot.tg = fake_tg
bot.db_create = lambda *a, **k: {"id": "rec1"}
bot.db_query = lambda *a, **k: []
bot.db_query_uid = lambda *a, **k: []
bot.page_update = lambda *a, **k: {"id": "rec1"}
bot.notify_admin = lambda *a, **k: None
bot.send = lambda chat_id, text, buttons=None: (SENT.append(("send", text)), {"ok": True})[1]

FAILS = []
PASSES = []
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if not cond else "%s :: %s" % (name, detail))
    print(("PASS: " if cond else "FAIL: ") + name + ((" :: " + str(detail)) if (detail and not cond) else ""))

def click(data, sess=None, label=None):
    """Клик по callback_data -> (ok, result_or_error)."""
    bot.SESS.clear()
    if sess:
        bot.SESS[UID] = sess
    try:
        r = bot._cb_inner(CHAT, UID, data)
        if r is None:
            return False, "вернул None (обработчик не найден)"
        return True, r
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)

# ------------------------------------------------------------------
# 1) все кнопки, которые бот реально шлёт (send(...) с callback_data)
# ------------------------------------------------------------------
BUTTONS = [
    ("settings", "⚙️ Настройки"),
    ("help", "🆘 Помощь"),
    ("menu", "меню"),
    ("view_params", "Мои параметры"),
    ("check_pay", "📊 Статус"),
    ("restart", "Настроить заново"),
    ("skip", "Пропустить"),
    ("walt_key", "Ключ Walt API"),
    ("wallet_new", "Подключить другой"),
    ("cycle", "/cycle"),
    ("metrics_page", "Метрики счёта"),
    ("metrics_data", "данные метрик"),
    ("settings_page", "настройки"),
    ("save_settings", "сохранить"),
    ("pay_usd", "$29/мес"),
    ("pay_ton", "9.5 TON/мес"),
    ("walt_open", "Открыть Walt"),
]

print("=== 1) прямые кнопки бота ===")
for cb, label in BUTTONS:
    sess = {"tg_id": UID, "step": 0, "data": {}, "page": None, "name": "T"}
    ok, det = click(cb, sess, label)
    check("кнопка %-15s отвечает" % cb, ok, det)

# ------------------------------------------------------------------
# 2) кнопки мастера: каждый шаг, каждый вариант
# ------------------------------------------------------------------
print()
print("=== 2) мастер настройки (каждый шаг x каждый вариант) ===")
for i, (key, q, why, variants, typ, dflt) in enumerate(STEPS):
    if not variants:
        continue
    for txt, val in variants:
        data = "ans:%s=%s" % (key, val)
        sess = {"tg_id": UID, "step": i, "data": {}, "page": None, "name": "T"}
        ok, det = click(data, sess)
        check("шаг %-12s вариант %-14s" % (key, val), ok, det)

# ------------------------------------------------------------------
# 3) полный проход мастера без ошибок (сценарий "средний/скальп/...")
# ------------------------------------------------------------------
print()
print("=== 3) сквозной проход мастера ===")
bot.SESS.clear()
sess = {"tg_id": UID, "step": 0, "data": {}, "page": None, "name": "T"}
bot.SESS[UID] = sess
step_i = 0
errors = []
while step_i < len(STEPS):
    key, q, why, variants, typ, dflt = STEPS[step_i]
    if not variants:
        step_i += 1
        continue
    data = "ans:%s=%s" % (key, variants[0][1])
    try:
        bot._cb_inner(CHAT, UID, data)
    except Exception as e:
        errors.append("шаг %s: %s" % (key, e))
        break
    if sess["step"] <= step_i and step_i + 1 < len(STEPS):
        errors.append("шаг %s не продвинул мастер (step=%s)" % (key, sess["step"]))
        break
    step_i += 1
check("сквозной проход мастера без исключений", not errors, errors)

# ------------------------------------------------------------------
# 4) кнопки, требующие мастера, но доступные БЕЗ него
#    (юзер мог не проходить настройку)
# ------------------------------------------------------------------
print()
print("=== 4) кнопки без запущенного мастера (SESS пуст) ===")
for cb in ("restart", "skip", "wallet_new", "view_params", "metrics_page",
           "settings_page", "cycle", "help", "menu", "check_pay"):
    bot.SESS.clear()
    try:
        r = bot._cb_inner(CHAT, UID, cb)
        check("без мастера: %-15s не падает" % cb, r is not None,
              "вернул None")
    except Exception as e:
        check("без мастера: %-15s не падает" % cb, False,
              "%s: %s" % (type(e).__name__, e))

print()
print("PASS: %d" % len(PASSES))
for f in FAILS:
    print("FAIL: " + f)
print("FAIL: %d" % len(FAILS))
sys.exit(1 if FAILS else 0)
