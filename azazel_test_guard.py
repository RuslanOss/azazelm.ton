# -*- coding: utf-8 -*-
"""Izolyaciya testov ot boevoy Airtable i Telegram.

Importiruy ETSI PERED importom bot / azazel_api / testov. Inache::_load_env()
v bot.py prochitaet /opt/azabot/.env i zapolnit os.environ boevym
AIRTABLE_TOKEN. Testy zhe stavili svoi znacheniya cherez
os.environ.setdefault(), kotoryj NE pereZAPISYVAET uzhe prisutstvuyushchie kluchi
-> test shol by v boyevuyu bazu.

Moduli:
  * zadast testovoe okruzhenie pryamym prisvoeniem (ne setdefault);
  * stubbet zapis v Airtable v oboih sloyah (bot.py i azazel_api.py);
  * stubbet otpravku v Telegram;
  * enforce_no_boy_table() - proverka, chto izolyaciya derzhitsya.
"""
import os

TEST_AIRTABLE_TOKEN = "patTEST"
TEST_AIRTABLE_BASE = "appTEST"
TEST_BOT_TOKEN = "123456:TESTTOKEN"

os.environ["AZABOT_TOKEN"] = TEST_BOT_TOKEN
os.environ["AIRTABLE_TOKEN"] = TEST_AIRTABLE_TOKEN
os.environ["AIRTABLE_BASE_ID"] = TEST_AIRTABLE_BASE
os.environ.setdefault("AIRTABLE_USERS_TABLE", "tblTESTusers")
os.environ.setdefault("AIRTABLE_EVENTS_TABLE", "tblTESTevents")
os.environ.setdefault("ADMIN_TG_ID", "1")


def _no_write(*a, **k):
    """Zaglushka zapisi: ne pishet niuda i ne padaet."""
    return None


def _no_write_true(*a, **k):
    return True


def protect_bot(bot):
    """Otklyuchaet realnye zapisi v Airtable i otpravku v Telegram."""
    bot.db_create = _no_write
    bot.db_query = _no_write
    bot.page_update = _no_write
    bot.at = _no_write
    bot.log_event = _no_write_true
    bot.send = lambda *a, **k: {"ok": True}
    bot.tg = _no_write
    bot.notify_admin = lambda *a, **k: None
    return bot


def protect_api(api):
    """Otklyuchaet realnye zapisi v Airtable v sloye API (Mini App)."""
    api._airtable = lambda *a, **k: (0, None)
    api._at_query_uid = lambda *a, **k: []
    api._ton_log_event = lambda *a, **k: True
    api._tg_send = lambda *a, **k: True
    return api


def enforce_no_boy_table():
    """Proverka: v okruzhenii NE boevoy Airtable token/base.

    Pustoy spisok = izolyaciya derzhitsya. Ne-pusto = testy slomalis izolyaciyu.
    """
    bad = []
    tok = os.environ.get("AIRTABLE_TOKEN", "")
    base = os.environ.get("AIRTABLE_BASE_ID", "")
    if tok and tok != TEST_AIRTABLE_TOKEN:
        bad.append("AIRTABLE_TOKEN ne testovyy: %r" % tok[:6])
    if base and base != TEST_AIRTABLE_BASE:
        bad.append("AIRTABLE_BASE_ID ne testovyy: %r" % base)
    return bad
