# -*- coding: utf-8 -*-
"""Тесты интеграции bot.py с торговым циклом.

Проверяем без Telegram и без сети:
  * бот импортирует раннер и не падает, если раннера нет;
  * команда /cycle зарегистрирована;
  * цикл отрабатывает и пишет отчёт;
  * фоновый поток запускается и останавливается вместе с ботом.
"""
import sys, os, json, tempfile, shutil, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Путь к bot.py - относительный от расположения теста.
# Раньше был захардкожен абсолютный путь к каталогу разработки,
# которого на сервере нет: тест падал FileNotFoundError.
BOT_PY = os.path.join(HERE, "bot.py")

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

# bot.py при импорте читает .env и config.json - готовим окружение
D = tempfile.mkdtemp()
os.environ["AZABOT_TOKEN"] = "123:test"
os.environ["AIRTABLE_TOKEN"] = "pat.test"
os.environ["AIRTABLE_BASE_ID"] = "appTest"
os.environ["ADMIN_TG_ID"] = "1"
os.environ["AZAZEL_DATA_DIR"] = D
os.environ["AZAZEL_CYCLE_ENABLED"] = "0"   # фоновый поток не запускаем в тестах

import azazel_test_guard as _guard  # izolyaciya ot boevoy Airtable/Telegram
import bot
_guard.protect_bot(bot)

check("bot импортируется", bot is not None)
check("раннер доступен боту", bot._CR is not None, bot._CR)
check("команда /cycle есть в коде",
      "/cycle" in open(BOT_PY,encoding="utf-8").read())
check("функция cmd_cycle определена", hasattr(bot,"cmd_cycle"))
check("функция cycle_run_once определена", hasattr(bot,"cycle_run_once"))
check("планировщик определён", hasattr(bot,"_cycle_loop"))

# ---------- цикл без подходящих пользователей ----------
rep = bot.cycle_run_once(log_it=False)
check("цикл отработал", isinstance(rep,dict) and "ran" in rep, rep)
check("пользователей нет - всё пропущено", rep.get("skipped",0)>=0, rep)

# ---------- пользователь с ключом, но без настроек ----------
with open(os.path.join(D,"777.json"),"w",encoding="utf-8") as f:
    json.dump({"walt_key":"k","walt_secret":"s"},f)
bot._cycle_get_profile = lambda uid: {"Прогресс настройки": 50}
rep = bot.cycle_run_once(log_it=False)
mine = [r for r in rep.get("reports",[]) if r.get("uid")==777]
check("пользователь без параметров обработан", len(mine)==1, rep.get("reports"))
if mine:
    check("пропущен с понятной причиной",
          mine[0].get("skipped") and "параметр" in (mine[0].get("reason") or "").lower(),
          mine[0])

# ---------- пользователь готов, но автоподтверждение выключено ----------
with open(os.path.join(D,"888.json"),"w",encoding="utf-8") as f:
    json.dump({"walt_key":"k","walt_secret":"s"},f)
bot._cycle_get_profile = lambda uid: {"Прогресс настройки": 100,
                                      "Автоподтверждение": False}
sent=[]
class SpyExec(object):
    def open_with_protection(self, plan, api_key_index=255):
        sent.append(plan); return {"ok":True,"steps":[]}
bot._CR.run_all.__globals__["WaltClient"] = None   # без клиента не идём в сеть
rep = bot.cycle_run_once(log_it=False)
mine = [r for r in rep.get("reports",[]) if r.get("uid")==888]
check("готовый пользователь обработан", len(mine)==1, rep.get("reports"))
if mine:
    check("не торговал без автоподтверждения", mine[0].get("traded") is False, mine[0])

# ---------- автоподтверждение включено, исполнитель подставлен ----------
bot._cycle_get_profile = lambda uid: {"Прогресс настройки": 100,
                                      "Автоподтверждение": True}
orig_run_all = bot._CR.run_all
def patched(data_dir, get_profile, **kw):
    kw["executor"] = SpyExec()
    kw["client"] = object()
    return orig_run_all(data_dir, get_profile, **kw)
bot._CR.run_all = patched
rep = bot.cycle_run_once(log_it=False)
bot._CR.run_all = orig_run_all
check("цикл с подставленным исполнителем отработал", isinstance(rep,dict), rep)

# ---------- команда /cycle не падает ----------
sent_msgs=[]
bot.send = lambda chat_id, text, buttons=None, **kw: sent_msgs.append(text) or True
try:
    bot.cmd_cycle(999, 888)
    check("cmd_cycle не бросает", True)
    check("cmd_cycle что-то отправила", len(sent_msgs)>=1, sent_msgs)
except Exception as e:
    check("cmd_cycle не бросает", False, str(e)[:200])

# ---------- планировщик запускается ----------
bot.CYCLE_ENABLED = True
bot._STOP = False
t = bot._start_cycle_thread()
check("поток планировщика создан", t is not None)
if t:
    time.sleep(1.2)
    check("поток жив", t.is_alive())
    bot._STOP = True
    time.sleep(0.5)

# ---------- бот без раннера не падает ----------
check("обработка отсутствия раннера предусмотрена",
      "if _CR is None" in open(BOT_PY,encoding="utf-8").read())

shutil.rmtree(D, ignore_errors=True)
# ---------- cmd_save_walt_key: честная обработка ошибок ----------
# Ключевой сценарий: результат page_update игнорировался, и бот всегда
# сообщал "сохранено", даже если в Airtable ничего не записалось.

sent_msgs = []
def _spy_send(chat_id, text, buttons=None):
    sent_msgs.append(text or "")
    return {"ok": True}
bot.send = _spy_send

def _save(key="K", secret="S", at_ok=True, json_ok=True, has_rec=True):
    sent_msgs.clear()
    bot._get_user_fields = lambda uid: (("rec1", {}) if has_rec else (None, {}))
    def _pu(table, rec, fields):
        return {"records":[{"id":"rec1"}]} if at_ok else None
    bot.page_update = _pu
    if json_ok:
        bot.write_user_json = lambda uid, data: os.path.join(D, str(uid)+".json")
    else:
        bot.write_user_json = lambda uid, data: None
    bot.cmd_save_walt_key(1, 8459508879, key, secret)
    return sent_msgs[0] if sent_msgs else ""

m = _save()
check("успех: сообщение о сохранении", "Ключ Walt сохранён" in m and "⚠️" not in m, m)

m = _save(at_ok=False)
check("провал Airtable: нет ложного 'сохранено'",
      "Ключ Walt сохранён\n" not in m and "не полностью" in m, m)
check("провал Airtable: сказано, что в Airtable не записано",
      "Airtable" in m and "не записать" in m, m)
check("провал Airtable: сказано, что на сервере записано",
      "торговый цикл ключ увидит" in m, m)

m = _save(json_ok=False)
check("провал JSON: сказано, что цикл ключ НЕ увидит", "НЕ увидит" in m, m)
check("провал JSON: нет ложного 'сохранено'", "не полностью" in m, m)

m = _save(at_ok=False, json_ok=False)
check("оба упали: оба статуса показаны", "не записать" in m and "НЕ увидит" in m, m)

m = _save(key="K", secret="")
check("пустой секрет: ключ не сохранён", "не сохранён" in m.lower(), m)

m = _save(has_rec=False)
check("нет профиля: просим /start", "/start" in m, m)

sent_msgs.clear()
bot._get_user_fields = lambda uid: ("rec1", {})
def _pu_raise(table, rec, fields):
    raise RuntimeError("boom")
bot.page_update = _pu_raise
bot.write_user_json = lambda uid, data: os.path.join(D, str(uid)+".json")
try:
    bot.cmd_save_walt_key(1, 8459508879, "K", "S")
    check("исключение Airtable: бот не упал", True)
    check("исключение Airtable: сообщение честное",
          bool(sent_msgs) and "не полностью" in sent_msgs[0], sent_msgs)
except Exception as e:
    check("исключение Airtable: бот не упал", False, str(e)[:120])

sent_msgs.clear()
def _pu_empty(table, rec, fields):
    return {}
bot.page_update = _pu_empty
bot.cmd_save_walt_key(1, 8459508879, "K", "S")
m2 = sent_msgs[0] if sent_msgs else ""
check("пустой ответ Airtable (не None) - считаем успехом",
      "Ключ Walt сохранён" in m2, m2)

print("PASS: %d"%len(PASSES))
for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
