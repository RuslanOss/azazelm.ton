# -*- coding: utf-8 -*-
"""Test izolyacii: testy NE dolzhny pisat v boyevuyu Airtable.

Detektiruem dыру: esli .env prochitan DO ustanovki testovogo okruzheniya,
os.environ soderzhit boevoy AIRTABLE_TOKEN, i testy ukladyvayut realnye
zapisi. Zdes my emuliruem oba scenariya i trebуem, chtoby guard ih otrekzal.
"""
import os, sys, subprocess, json
sys.path.insert(0, "/opt/azabot")

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS:", name)
    else:
        FAIL += 1
        print("FAIL:", name, "::", detail)


# --- 1. Guard zamenyaet boevoe okruzhenie na testovoe ---
import azazel_test_guard as g
check("guard: AIRTABLE_TOKEN testovyy", os.environ["AIRTABLE_TOKEN"] == g.TEST_AIRTABLE_TOKEN, os.environ.get("AIRTABLE_TOKEN"))
check("guard: AIRTABLE_BASE_ID testovyy", os.environ["AIRTABLE_BASE_ID"] == g.TEST_AIRTABLE_BASE, os.environ.get("AIRTABLE_BASE_ID"))
check("guard: enforce_no_boy_table pusto", g.enforce_no_boy_table() == [], g.enforce_no_boy_table())

# --- 2. Guard perekryvaet boevoy token, prochitannyi ranee ---
os.environ["AIRTABLE_TOKEN"] = "patREALBOEY"
os.environ["AIRTABLE_BASE_ID"] = "appREALBOEY"
check("enforce_no_boy_table lovit boevoy token", "AIRTABLE_TOKEN" in " ".join(g.enforce_no_boy_table()), g.enforce_no_boy_table())
check("enforce_no_boy_table lovit boevoy base", "AIRTABLE_BASE_ID" in " ".join(g.enforce_no_boy_table()), g.enforce_no_boy_table())
# vozvraщаem testovye
os.environ["AIRTABLE_TOKEN"] = g.TEST_AIRTABLE_TOKEN
os.environ["AIRTABLE_BASE_ID"] = g.TEST_AIRTABLE_BASE
check("enforce_no_boy_table snova pusto", g.enforce_no_boy_table() == [], g.enforce_no_boy_table())

# --- 3. protect_api ne daet pisat ---
import azazel_api as api
g.protect_api(api)  # otklyuchaem realnye zapisi v Airtable
st, d = api._airtable("POST", "/" + api.AIRTABLE_BASE_ID + "/" + api.AIRTABLE_EVENTS_TABLE, {"records": []})
check("protect_api: _airtable zablokirovan", st == 0 and d is None, (st, d))
check("protect_api: _at_query_uid pusto", api._at_query_uid("x", 1) == [], api._at_query_uid("x", 1))

# --- 4. Kazhdyy test v repo dolzhen imet guard ---
import glob, re
miss = []
for f in sorted(glob.glob("/opt/azabot/test_*.py")):
    src = open(f, encoding="utf-8").read()
    if "azazel_test_guard" not in src:
        miss.append(os.path.basename(f))
check("vse testy podklyuchili guard", not miss, miss)

print("PASS: %d" % PASS)
print("FAIL: %d" % FAIL)
sys.exit(1 if FAIL else 0)
