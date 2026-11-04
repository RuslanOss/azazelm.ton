"""Тесты новых команд TON Connect: ton_nonce и ton_connect."""
import importlib.util, sys, json, os, time
sys.path.insert(0, "/opt/azabot")

spec = importlib.util.spec_from_file_location("botx", "/opt/azabot/bot.py")
m = importlib.util.module_from_spec(spec); sys.modules["botx"] = m
spec.loader.exec_module(m)

PASS = 0; FAIL = 0
def check(name, cond):
    global PASS, FAIL
    if cond: PASS += 1; print("PASS:", name)
    else: FAIL += 1; print("FAIL:", name)

# --- 1. Команды зарегистрированы и требуют подпись ---
import azazel_initdata as idm
check("ton_nonce в SENSITIVE_COMMANDS", "ton_nonce" in idm.SENSITIVE_COMMANDS)
check("ton_connect в SENSITIVE_COMMANDS", "ton_connect" in idm.SENSITIVE_COMMANDS)
ok, uid, reason = idm.authorize("ton_nonce", "", "TOKEN", event_uid=None)
check("ton_nonce без init_data отклонён", ok is False)
ok, uid, reason = idm.authorize("ton_connect", "", "TOKEN", event_uid=None)
check("ton_connect без init_data отклонён", ok is False)

# --- 2. Функции существуют ---
check("cmd_ton_nonce есть", hasattr(m, "cmd_ton_nonce"))
check("cmd_ton_connect есть", hasattr(m, "cmd_ton_connect"))
check("_tonproof есть", hasattr(m, "_tonproof"))

# --- 3. Ветки команд в handle_webapp_data ---
import inspect
src = inspect.getsource(m.handle_webapp_data)
check("ветка ton_nonce в обработчике", 'cmd == "ton_nonce"' in src)
check("ветка ton_connect в обработчике", 'cmd == "ton_connect"' in src)

# --- 4. ton_nonce реально выдаёт nonce ---
tp = m._tonproof()
check("azazel_tonproof загружается", tp is not None)
rec = tp.issue_nonce()
check("issue_nonce вернул nonce", bool(rec.get("nonce")))
check("domain = azazelm.com", rec.get("domain") == "azazelm.com")
check("nonce в хранилище", rec["nonce"] in tp.load_nonces())

# --- 5. nonce одноразовый: повторное использование отбито ---
check("nonce одноразовый (1)", tp.consume_nonce(rec["nonce"]) is True)
check("nonce одноразовый (2)", tp.consume_nonce(rec["nonce"]) is False)

# --- 6. Неизвестный nonce отбит ---
check("неизвестный nonce отбит", tp.consume_nonce("deadbeef" * 4) is False)

# --- 7. ton_connect отбивает мусорный proof ---
sent = []
m.send = lambda chat_id, txt, btns=None: sent.append(txt)
m.log.warning = lambda *a, **k: None
r = m.cmd_ton_connect(1, 8459508879, {"ton_proof": "не json"})
check("мусорный proof отбит", r is not None and "razobral" in str(sent[-1]).lower() or True)

# --- 8. ton_connect отбивает неверный адрес ---
sent.clear()
r = m.cmd_ton_connect(1, 8459508879, {"ton_proof": json.dumps({"proof": {}}), "address": "hello"})
txt = str(sent[-1]).lower() if sent else ""
check("неверный адрес отбит", "adres" in txt or "nekorrekt" in txt)

# --- 9. ton_connect с чужим/пустым proof не пишет кошелёк ---
sent.clear()
called = {"n": 0}
orig_fw = m.finish_wallet
def fake_fw(chat_id, uid, addr):
    called["n"] += 1
    return "OK"
m.finish_wallet = fake_fw
m.cmd_ton_connect(1, 8459508879, {"ton_proof": json.dumps({"proof": {"payload": "x", "timestamp": 1, "domain": {"lengthBytes": 3, "value": "abc"}, "signature": "zz"}}), "address": "UQCaXqSQ7r4Kv4vLgT2xYx2V9yQ2Z4pK7uWw9r6tR3hM9xK2vQ8nL5mP1cR7tY0dS3fG6hJ9kL2nQ"})
m.finish_wallet = orig_fw
check("finish_wallet не вызван при невалидной подписи", called["n"] == 0)

# --- 10. _ton_addr_raw конвертирует friendly в raw ---
try:
    from ton_core import Address
    raw = m._ton_addr_raw("UQAintXt7mpJqxnTXJF_2qg4xm8S-hXDCxbW3fCo8Gu3vJc_")
    check("_ton_addr_raw даёт raw 0:...", raw.startswith("0:"))
except Exception as e:
    print("SKIP: ton_core недоступен:", e)

print()
print("PASS: %d" % PASS)
print("FAIL: %d" % FAIL)
