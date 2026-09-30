"""Three independent research paths: small-cap pre-explosion, large-cap contract selection, and contract-first radar."""
from __future__ import annotations
import json, math
from pathlib import Path
from typing import Any

def _n(v, d=0.0):
    try:
        x=float(v)
        return x if math.isfinite(x) else d
    except (TypeError, ValueError):
        return d

def _rows(p, keys):
    out=[]
    if not isinstance(p,dict): return out
    for k in keys:
        v=p.get(k)
        if isinstance(v,list): out += [x for x in v if isinstance(x,dict)]
        elif isinstance(v,dict): out += [x for x in v.values() if isinstance(x,dict)]
    return out

def _sym(r):
    return str(r.get("symbol") or r.get("ticker") or r.get("underlying") or "").upper().strip()

def _dir(r):
    x=str(r.get("direction") or r.get("preferred_side") or r.get("side") or r.get("bias") or "").upper()
    return "BULLISH" if x in {"CALL","BULLISH","LONG","BUY","UP"} else "BEARISH" if x in {"PUT","BEARISH","SHORT","SELL","DOWN"} else "NEUTRAL"

def _score(r):
    return max(0,min(100,_n(r.get("score",r.get("signal_score",r.get("explosion_score",r.get("confidence",0)))))))

def _quality(r):
    if r.get("valid") is False or r.get("is_valid") is False or r.get("stale") is True or r.get("is_stale") is True: return False
    s=str(r.get("freshness_status") or r.get("data_status") or "").lower()
    return s not in {"stale","expired","invalid","rejected","failed","error"}

def small_cap_path(explosion):
    rows=[r for r in _rows(explosion,("candidates","actionable","signals","rows")) if _quality(r) and 0<_n(r.get("price"),999)>0 and _n(r.get("price"),999)<=10]
    out=[]
    for r in rows:
        early=_n(r.get("institutional_earlyness",r.get("earlyness")))
        anomaly=_n(r.get("institutional_anomaly",r.get("anomaly")))
        accel=_n(r.get("institutional_acceleration",r.get("acceleration")))
        catalyst=_n(r.get("catalyst_score",r.get("news_score",r.get("catalyst_quality"))))
        stage=str(r.get("stage") or "WATCH")
        s=_score(r)
        cq=r.get("chart_quality") or r.get("data_fabric_validation",{}).get("chart_quality") or {}
        compression=_n(cq.get("compression_ratio"),1.0)
        resistance=_n(cq.get("resistance_distance_pct"),99.0)
        volume_accel=_n(cq.get("volume_acceleration_ratio"),1.0)
        chart_early=(25 if compression <= 0.72 else 0)+(25 if resistance <= 3.0 else 0)+(25 if volume_accel >= 1.8 else 0)
        pre_score=_n(r.get("pre_explosion_score"))
        readiness=min(100,0.25*early+0.20*anomaly+0.15*accel+0.10*catalyst+0.10*s+0.10*chart_early+0.10*pre_score)
        if readiness < 45: continue
        out.append({"path":"SMALL_CAP_PRE_EXPLOSION","symbol":_sym(r),"price":_n(r.get("price")),
                    "stage":stage,"readiness":round(readiness,2),"earlyness":early,"anomaly":anomaly,
                    "acceleration":accel,"catalyst_score":catalyst,"score":s,"pre_explosion_score":pre_score,
                    "chart_quality":{"compression_ratio":compression,"resistance_distance_pct":resistance,"volume_acceleration_ratio":volume_accel,"early_breakout_flags":chart_early},
                    "direction":_dir(r),"reasons":r.get("reasons",[])[:6],"research_only":True})
    return sorted(out,key=lambda x:(x["readiness"],x["earlyness"]),reverse=True)[:25]

def _small_cap_option_bridge(small_rows, options):
    """Attach same-cycle option evidence to small-cap pre-explosion candidates."""
    contracts=_rows(options,("contract_recommendations","contracts","top_calls","top_puts","directional_signals","research_contracts"))
    by_symbol={}
    for row in contracts:
        if not _quality(row):
            continue
        s=_sym(row)
        if not s:
            continue
        by_symbol.setdefault(s,[]).append(row)
    out=[]
    for item in small_rows:
        matches=by_symbol.get(item["symbol"],[])
        scored=[]
        for c in matches:
            direction=_dir(c)
            if direction != "NEUTRAL" and item.get("direction") != "NEUTRAL" and direction != item.get("direction"):
                continue
            vol=_n(c.get("volume")); oi=_n(c.get("open_interest",c.get("oi")))
            voi=vol/oi if oi>0 else _n(c.get("volume_oi",c.get("vol_oi")))
            spread=_n(c.get("spread_pct",c.get("bid_ask_spread_pct")),99)
            quality_score=_score(c)
            liquidity=min(100, min(100,voi*20)*0.45 + min(100,vol/1000)*0.25 + quality_score*0.20 + max(0,100-spread)*0.10)
            scored.append((liquidity,c,voi))
        if scored:
            _, best, voi=max(scored,key=lambda x:x[0])
            item=dict(item)
            item["option_bridge"]={
                "available":True,
                "contract":best.get("contract") or best.get("occ_symbol") or best.get("symbol"),
                "direction":_dir(best),
                "expiration":best.get("expiration") or best.get("expiry"),
                "dte":best.get("dte",best.get("days_to_expiration")),
                "strike":best.get("strike"),
                "delta":best.get("delta"),
                "gamma":best.get("gamma"),
                "volume":best.get("volume"),
                "open_interest":best.get("open_interest",best.get("oi")),
                "volume_oi":round(voi,3),
                "iv":best.get("iv",best.get("implied_volatility")),
                "spread_pct":best.get("spread_pct",best.get("bid_ask_spread_pct")),
                "contract_score":quality_score,
                "source":best.get("source") or best.get("provider"),
                "provenance_present":bool(best.get("provenance") or best.get("source") or best.get("provider")),
            }
        else:
            item=dict(item)
            item["option_bridge"]={"available":False,"reason":"no_same_cycle_quality_checked_contract"}
        out.append(item)
    return out

def _horizon(dte):
    if dte<=2: return "DAILY"
    if dte<=14: return "WEEKLY"
    return "MONTHLY"

def large_cap_path(latest, options):
    stock_rows=_rows(latest,("stock_recommendations","stocks","chart_signals"))
    contracts=_rows(options,("contract_recommendations","contracts","top_calls","top_puts","directional_signals"))
    stock={}
    for r in stock_rows:
        s=_sym(r)
        if s: stock[s]=r
    out=[]
    for c in contracts:
        s=_sym(c); st=stock.get(s)
        if not st: continue
        cap=_n(st.get("market_cap",st.get("marketCap",0)))
        # If cap is explicitly supplied, require >= $10B. If absent, keep only a curated mega/large list.
        large=cap>=10_000_000_000 or s in {"AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","TSLA","AVGO","AMD","NFLX","JPM","V","MA","WMT","ORCL","COST","MU","QCOM","INTC"}
        if not large or not _quality(c): continue
        dte=int(_n(c.get("dte",c.get("days_to_expiration",30)),30))
        contract_score=_score(c); stock_score=_score(st)
        combined=min(100,0.55*contract_score+0.45*stock_score)
        out.append({"path":"LARGE_CAP_CONTRACT_SELECTION","symbol":s,"direction":_dir(c) if _dir(c)!="NEUTRAL" else _dir(st),
                    "contract":c.get("contract") or c.get("occ_symbol") or c.get("symbol"),
                    "expiration":c.get("expiration") or c.get("expiry"),"dte":dte,"horizon":_horizon(dte),
                    "delta":c.get("delta"),"gamma":c.get("gamma"),"volume":c.get("volume"),
                    "open_interest":c.get("open_interest",c.get("oi")),"iv":c.get("iv"),
                    "spread_pct":c.get("spread_pct"),"score":round(combined,2),
                    "stock_evidence":st,"contract_evidence":c,"research_only":True})
    return sorted(out,key=lambda x:x["score"],reverse=True)[:25]

def contract_first_path(options):
    rows=[r for r in _rows(options,("contract_recommendations","contracts","top_calls","top_puts","directional_signals","research_contracts","research_top_calls","research_top_puts")) if _quality(r)]
    out=[]
    for r in rows:
        vol=_n(r.get("volume")); oi=_n(r.get("open_interest",r.get("oi")))
        voi=vol/oi if oi>0 else _n(r.get("volume_oi",r.get("vol_oi")))
        iv=_n(r.get("iv",r.get("implied_volatility")))
        spread=_n(r.get("spread_pct",r.get("bid_ask_spread_pct")))
        score=_score(r)
        baseline_vol=_n(r.get("baseline_volume"))
        baseline_oi=_n(r.get("baseline_open_interest",r.get("baseline_oi")))
        volume_multiple=(vol/baseline_vol) if baseline_vol>0 else None
        oi_multiple=(oi/baseline_oi) if baseline_oi>0 else None
        historical_support=0
        if volume_multiple is not None: historical_support += 15 if volume_multiple>=1.5 else 0
        if oi_multiple is not None: historical_support += 10 if oi_multiple>=1.2 else 0
        anomaly=min(100,0.40*min(100,voi*20)+0.20*min(100,vol/1000)+0.20*score+0.10*max(0,100-spread)+0.10*historical_support)
        if anomaly<50: continue
        out.append({"path":"CONTRACT_FIRST_RADAR","symbol":_sym(r),
                    "direction":_dir(r),"contract":r.get("contract") or r.get("occ_symbol") or r.get("symbol"),
                    "expiration":r.get("expiration") or r.get("expiry"),"dte":r.get("dte"),
                    "volume":vol,"open_interest":oi,"volume_oi":round(voi,3),"iv":iv,
                    "spread_pct":spread,"anomaly_score":round(anomaly,2),
                    "historical_comparison":{"available":volume_multiple is not None or oi_multiple is not None,"volume_multiple":volume_multiple,"oi_multiple":oi_multiple},
                    "underlying_evidence_required":True,"research_only":True})
    return sorted(out,key=lambda x:x["anomaly_score"],reverse=True)[:30]

def build_three_paths(*, explosion, latest, options):
    small_caps=_small_cap_option_bridge(small_cap_path(explosion), options)
    return {"schema":"three-path-intelligence-v3",
            "small_cap_pre_explosion":small_caps,
            "large_cap_contract_selection":large_cap_path(latest,options),
            "contract_first_radar":contract_first_path(options),
            "policy":{"independent_paths":True,"automatic_execution":False,"score_is_probability":False,
                      "missing_data_is_not_invented":True,"research_only":True}}

def run(*, explosion_path, latest_path, options_path, output_path):
    def load(p):
        try:
            x=json.loads(Path(p).read_text(encoding="utf-8"))
            return x if isinstance(x,dict) else {}
        except (OSError,ValueError): return {}
    result=build_three_paths(explosion=load(explosion_path),latest=load(latest_path),options=load(options_path))
    dest=Path(output_path); dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix(dest.suffix+".tmp"); tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8"); tmp.replace(dest)
    return result
