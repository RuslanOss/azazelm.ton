# -*- coding: utf-8 -*-
"""Тесты проброса extra и sizing в CE.

extra - плоские перекрытия профиля пользователя. Должен доезжать от
конфига (секция algo) до КАЖДОГО решения движка, иначе пользовательские
настройки риска молча игнорируются.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import continuation_engine as ce
import azazel_config_loader as L

FAILS=[]; PASSES=[]
def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name if cond else "%s :: %s"%(name,detail))

CFG = {"stops":{"alts_pct":3.0,"btc_eth_pct":1.5,"atr_mult":1.0},
       "leverage":{"alts_max":5,"btc_eth_max":10},
       "rr_min":2.0,"btc_filter_pct":2.0,"funding_long_block_pct":0.05,
       "daily_loss_limit_usd":15.0,"max_stops_per_day":3,"correlation_cap":2,
       "max_trades_per_day":5}

# ---------- загрузчик: build_extra ----------
check("build_extra читает algo.stop_alts",
      L.build_extra({"stop_alts":4.5})["stop_alts"]==4.5, L.build_extra({"stop_alts":4.5}))
check("build_extra читает algo.profile",
      L.build_extra({"profile":{"corr_cap":3}})["corr_cap"]==3,
      L.build_extra({"profile":{"corr_cap":3}}))
check("build_extra игнорирует None",
      "stop_alts" not in L.build_extra({"stop_alts":None}), L.build_extra({"stop_alts":None}))
check("profile имеет приоритет над algo",
      L.build_extra({"stop_alts":4.5,"profile":{"stop_alts":6.0}})["stop_alts"]==6.0,
      L.build_extra({"stop_alts":4.5,"profile":{"stop_alts":6.0}}))
check("build_extra от пустого -> пустой dict", L.build_extra({})=={}, L.build_extra({}))
check("build_extra_from_config берёт algo",
      L.build_extra_from_config({"algo":{"stop_alts":2.0}})["stop_alts"]==2.0,
      L.build_extra_from_config({"algo":{"stop_alts":2.0}}))

# ---------- _resolve_extra ----------
e = ce._resolve_extra(CFG, {"stop_alts":5.0})
check("_resolve_extra: из algo", e.get("stop_alts")==5.0 or e.get("stop_alts") is None, e)
e = ce._resolve_extra(CFG, {"stop_alts":5.0})
check("_resolve_extra: явный extra", e["stop_alts"]==5.0, e)
e = ce._resolve_extra(CFG, {"stop_alts":None})
check("_resolve_extra: None не затирает", "stop_alts" not in e or e["stop_alts"] is not None, e)

# ---------- extra реально меняет решения ----------
# 1) стоп: extra.stop_alts = 6% -> стоп 6%, а не 3%
cfg6 = json.loads(json.dumps(CFG))
cfg6["algo"] = {"stop_alts":6.0}
ex = ce._resolve_extra(cfg6)
check("algo попадает в extra", ex.get("stop_alts")==6.0, ex)

# 2) corr_cap: extra уменьшает потолок
cfg_c = json.loads(json.dumps(CFG)); cfg_c["algo"]={"corr_cap":1}
ex_c = ce._resolve_extra(cfg_c)
ok,r = ce.correlation_cap_check("LIT",[{"symbol":"ZEC"}], cfg_c, ex_c)
check("extra corr_cap=1 блокирует 2-ю позицию", not ok, r)

# 3) loss_limit: extra уменьшает дневной лимит
cfg_l = json.loads(json.dumps(CFG)); cfg_l["algo"]={"loss_limit":5.0}
ex_l = ce._resolve_extra(cfg_l)
ok,r = ce.daily_limit_check(0,-6.0, cfg_l, ex_l)
check("extra loss_limit=5 блокирует -$6", not ok, r)

# 4) max_trades
cfg_t = json.loads(json.dumps(CFG)); cfg_t["algo"]={"max_trades":2}
ex_t = ce._resolve_extra(cfg_t)
ok,r = ce.daily_limit_check(3,0.0, cfg_t, ex_t)
check("extra max_trades=2 блокирует 3-ю сделку", not ok, r)

# 5) btc_filter: extra меняет порог фильтра.
# ВНИМАНИЕ: бОЛЬШИЙ порог = БОЛЕЕ ШИРОКАЯ зона запрета, а не более узкая.
# При 10% и расстоянии 1.24% шорт альта запрещён; при 0.5% - разрешён.
cfg_b = json.loads(json.dumps(CFG)); cfg_b["algo"]={"btc_filter":10.0}
ex_b = ce._resolve_extra(cfg_b)
ok,r = ce.btc_filter_check("SNDK","short",{"price":77900,"resistance":78880}, cfg_b, ex_b)
check("extra btc_filter=10% -> зона запрета шире, шорт заблокирован", not ok, r)
cfg_b2 = json.loads(json.dumps(CFG)); cfg_b2["algo"]={"btc_filter":0.5}
ex_b2 = ce._resolve_extra(cfg_b2)
ok,r = ce.btc_filter_check("SNDK","short",{"price":77900,"resistance":78880}, cfg_b2, ex_b2)
check("extra btc_filter=0.5% -> шорт разрешён", ok, r)
ok,r = ce.btc_filter_check("SNDK","short",{"price":77900,"resistance":78880}, CFG)
check("базовый фильтр 2% -> шорт заблокирован", not ok, r)

# 6) leverage: extra меняет потолок альтов
cfg_lv = json.loads(json.dumps(CFG)); cfg_lv["algo"]={"lev_alts":3}
ex_lv = ce._resolve_extra(cfg_lv)
lev,r = ce.leverage_for("SNDK",0.0, cfg_lv, ex_lv)
check("extra lev_alts=3 -> плечо 3x", lev==3, (lev,r))

# 7) stop_for: extra меняет стоп
cfg_st = json.loads(json.dumps(CFG)); cfg_st["algo"]={"stop_alts":7.0}
ex_st = ce._resolve_extra(cfg_st)
sp,pct,r = ce.stop_for("SNDK",100.0,[{"o":100,"h":101,"l":99,"c":100,"v":1}]*60, cfg_st, ex_st)
check("extra stop_alts=7 -> стоп 7%", abs(pct-7.0)<1e-9, (pct,r))

# ---------- sizing в open_position ----------
def synth_up(n=120, start=100.0, step=0.5, vol=1000.0):
    """Рост с шумом - тот же генератор, что в test_cont_v2."""
    out=[]; p=start
    for i in range(n):
        o=p
        c=p+step+(0.3 if i%7==0 else -0.1)
        h=max(o,c)+0.2; l=min(o,c)-0.2
        out.append({"o":o,"h":h,"l":l,"c":c,"v":vol*(1+(i%5)*0.1)})
        p=c
    return out
up = [ce.norm(c) for c in synth_up()]
op = ce.open_position("LIT","long",100.0,up,CFG,funding_pct=0.001,margin_usd=50)
check("margin_usd остаётся переданным", op["margin_usd"]==50, op)
check("sizing: margin_used посчитан", op.get("margin_used",0)>0, op)
check("sizing: notional посчитан", op.get("notional_usd",0)>0, op)
check("sizing: units посчитаны", op.get("units",0)>0, op)
check("sizing: номинал <= маржа*плечо",
      op["notional_usd"] <= 50.0*op["leverage"]+1e-6, op)
check("sizing: риск = notional * stop_pct/100",
      abs(op["risk_usd"] - op["notional_usd"]*op["stop_pct"]/100.0) < 0.02, op)
check("sizing: риск <= 33% маржи", op["risk_usd"] <= 50*0.33+0.02, op)

op0 = ce.open_position("LIT","long",100.0,up,CFG,funding_pct=0.001,margin_usd=0)
check("без маржи sizing пустой", op0.get("notional_usd")==0 and op0.get("units")==0, op0)

# extra.rr меняет цель
cfg_rr = json.loads(json.dumps(CFG)); cfg_rr["algo"]={"rr":3.0}
ex_rr = ce._resolve_extra(cfg_rr)
op2 = ce.open_position("LIT","long",100.0,up,cfg_rr,funding_pct=0.001,
                       margin_usd=50, extra=ex_rr)
check("extra rr=3 -> цель дальше", op2["rr"]==3.0, op2)
check("extra rr меняет take_profit", op2["take_profit"]>op["take_profit"], (op2,op))

# ---------- сквозной поток через find_entries ----------
cfg_e = json.loads(json.dumps(CFG)); cfg_e["algo"]={"stop_alts":6.0,"rr":3.0}
cands = [{"symbol":"LIT","side":"long","candles":up,"price":up[-1]["c"],
          "funding_pct":0.001,"btc_ctx":{"price":77900,"resistance":78880}}]
check("свечи дают достаточно сигналов (для find_entries)",
      len(up)==120, len(up))
res = ce.find_entries(cands, cfg_e, {"positions":[],"trades_today":0,
                                     "pnl_today":0,"stops_today":0})
if res and res[0].get("action")=="enter":
    check("find_entries: extra rr доехал", res[0]["rr"]==3.0, res[0])
    check("find_entries: extra stop_alts доехал",
          res[0]["stop_pct"]>=6.0, res[0])
else:
    check("find_entries: вход разрешён с extra", False, res[0].get("reason") if res else "нет")

# ---------- engine_cycle ----------
cyc = ce.engine_cycle(candidates={"LIT":up}, positions=[], cfg=cfg_e,
                       state={"positions":[],"trades_today":0,"pnl_today":0,"stops_today":0})
check("engine_cycle отработал", isinstance(cyc, dict) and "entries" in cyc, cyc)

# ---------- ключи плеча в PROFILE_KEYS ----------
check("PROFILE_KEYS содержит lev_alts", "lev_alts" in L.PROFILE_KEYS, L.PROFILE_KEYS)
check("PROFILE_KEYS содержит lev_btc", "lev_btc" in L.PROFILE_KEYS, L.PROFILE_KEYS)
check("build_extra читает lev_alts",
      L.build_extra({"lev_alts":3})["lev_alts"]==3, L.build_extra({"lev_alts":3}))

cfg_lv = json.loads(json.dumps(CFG)); cfg_lv["algo"]={"lev_alts":3}
ex_lv = ce._resolve_extra(cfg_lv)
check("extra lev_alts доехал до _resolve_extra", ex_lv.get("lev_alts")==3, ex_lv)
lev,r = ce.leverage_for("SNDK",0.0, cfg_lv, ex_lv)
check("extra lev_alts=3 -> плечо 3x", lev==3, (lev,r))
lev,r = ce.leverage_for("SNDK",0.0, CFG, ce._resolve_extra(CFG))
check("без extra плечо альта = 5x", lev==5, (lev,r))

cfg_lvb = json.loads(json.dumps(CFG)); cfg_lvb["algo"]={"lev_btc":4}
ex_lvb = ce._resolve_extra(cfg_lvb)
lev,r = ce.leverage_for("BTC",0.005, cfg_lvb, ex_lvb)
check("extra lev_btc=4 ограничивает плечо BTC", lev==4, (lev,r))

# ---------- rr из extra в find_entries ----------
cfg_rr2 = json.loads(json.dumps(CFG)); cfg_rr2["algo"]={"rr":3.0}
ex_rr2 = ce._resolve_extra(cfg_rr2)
up2 = [ce.norm(c) for c in synth_up()]
cands_rr = [{"symbol":"LIT","side":"long","candles":up2,"price":up2[-1]["c"],
             "funding_pct":0.001,"btc_ctx":{"price":77900,"resistance":78880}}]
res_rr = ce.find_entries(cands_rr, cfg_rr2, {"positions":[],"trades_today":0,
                                            "pnl_today":0,"stops_today":0})
if res_rr and res_rr[0].get("action")=="enter":
    check("find_entries: rr из extra = 3", res_rr[0]["rr"]==3.0, res_rr[0])
    ent = res_rr[0]
    risk = abs(ent["price"] - ent["stop_loss"])
    exp_target = ent["price"] + risk * 3.0
    check("find_entries: цель соответствует R:R 1:3",
          abs(ent["take_profit"] - exp_target) < 0.02, (ent, exp_target))
else:
    check("find_entries: вход с extra rr разрешён", False,
          res_rr[0].get("reason") if res_rr else "нет")

# без extra rr остаётся из cfg
res_base = ce.find_entries(cands_rr, CFG, {"positions":[],"trades_today":0,
                                           "pnl_today":0,"stops_today":0})
if res_base and res_base[0].get("action")=="enter":
    check("find_entries: без extra rr = 2 (из cfg)", res_base[0]["rr"]==2.0, res_base[0])
else:
    check("find_entries: базовый вход разрешён", False,
          res_base[0].get("reason") if res_base else "нет")

# open_position и find_entries не противоречат друг другу
op_rr = ce.open_position("LIT","long",100.0,up2,cfg_rr2,funding_pct=0.001,
                         margin_usd=50, extra=ex_rr2)
check("open_position rr совпадает с find_entries", op_rr["rr"]==3.0, op_rr)

print("PASS: %d"%len(PASSES))

for f in FAILS: print("FAIL: "+f)
print("FAIL: %d"%len(FAILS))
sys.exit(1 if FAILS else 0)
