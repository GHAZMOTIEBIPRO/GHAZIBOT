from __future__ import annotations
import argparse, html, json, os
from datetime import datetime, timezone
from pathlib import Path
import requests
STATE=Path("data/live/three_path_alert_state.json")
def now(): return datetime.now(timezone.utc).isoformat()
def n(v,d=0):
    try: return float(v)
    except (TypeError,ValueError): return d
def safe(v): return html.escape(str(v or "").strip()[:700])
def send(token,chat,text):
    r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",data={"chat_id":chat,"text":text,"parse_mode":"HTML","disable_web_page_preview":"true"},timeout=18)
    r.raise_for_status()
    if not r.json().get("ok"): raise RuntimeError("Telegram send failed")
def load_state():
    try:
        x=json.loads(STATE.read_text(encoding="utf-8")); return x if isinstance(x,dict) else {"sent":{}}
    except (OSError,ValueError): return {"sent":{}}
def key(path,row): return "|".join(str(row.get(k) or "") for k in ("symbol","contract","expiration","direction"))+"|"+path
def _omega_guard(path, row, omega):
    """Require a same-symbol Omega research case with no active conflict before alerting."""
    symbol = str(row.get("symbol") or "").upper().strip()
    direction = str(row.get("direction") or "NEUTRAL").upper().strip()
    if not symbol or not isinstance(omega, dict):
        return False, "omega_missing"
    candidates = omega.get("candidates") if isinstance(omega.get("candidates"), list) else []
    from options_radar.black_box_fusion import investigate_candidate
    for candidate in candidates:
        if str(candidate.get("symbol") or "").upper().strip() != symbol:
            continue
        if candidate.get("research_state") != "RESEARCH_CANDIDATE":
            continue
        omega_direction = str(candidate.get("direction") or "NEUTRAL").upper().strip()
        if direction != "NEUTRAL" and omega_direction != "NEUTRAL" and direction != omega_direction:
            continue
        case = investigate_candidate(candidate)
        if case.get("thesis_status") != "ACTIVE_RESEARCH":
            return False, case.get("conflict_state") or "omega_invalidation"
        return True, case.get("case_id")
    return False, "no_matching_omega_case"

def message(path,row):
    if path=="SMALL_CAP_PRE_EXPLOSION":
        bridge=row.get("option_bridge") if isinstance(row.get("option_bridge"),dict) else {}
        contract_line=""
        if bridge.get("available"):
            contract_line="\\n\\n🎯 Contract bridge: <b>"+safe(bridge.get("contract"))+"</b> | "+safe(bridge.get("direction"))+" | DTE "+safe(bridge.get("dte"))+" | Δ "+safe(bridge.get("delta"))+" | OI "+safe(bridge.get("open_interest"))+" | Vol/OI "+safe(bridge.get("volume_oi"))
        return ("🔥 <b>BLACK BOX Ω — SMALL CAP PRE-EXPLOSION</b>\\n\\n<b>"+safe(row.get("symbol"))+"</b> — $"+f"{n(row.get("price")):,.2f}"+"\\nReadiness: <b>"+f"{n(row.get("readiness")):.0f}"+"/100</b>\\nStage: <b>"+safe(row.get("stage"))+"</b>\\nEarlyness: "+f"{n(row.get("earlyness")):.0f}"+" | Anomaly: "+f"{n(row.get("anomaly")):.0f}"+" | Acceleration: "+f"{n(row.get("acceleration")):.0f}"+"\\nCatalyst: "+f"{n(row.get("catalyst_score")):.0f}"+contract_line+"\\n\\n⚠️ بحث فقط — وجود عقد لا يعني سيولة أو تنفيذ مؤكد.")
    if path=="LARGE_CAP_CONTRACT_SELECTION":
        return ("🏢 <b>BLACK BOX Ω — LARGE CAP CONTRACT</b>\n\n<b>"+safe(row.get("symbol"))+"</b> — <b>"+safe(row.get("direction"))+"</b>\nContract: <b>"+safe(row.get("contract"))+"</b>\nExpiration: "+safe(row.get("expiration"))+" | Horizon: <b>"+safe(row.get("horizon"))+"</b>\nDelta: "+safe(row.get("delta"))+" | Gamma: "+safe(row.get("gamma"))+"\nVolume: "+safe(row.get("volume"))+" | OI: "+safe(row.get("open_interest"))+" | IV: "+safe(row.get("iv"))+"\nScore: <b>"+f"{n(row.get("score")):.0f}"+"/100</b>\n\n⚠️ العقد بحثي؛ جودة البيانات تحدد إمكانية الاعتماد عليه.")
    return ("🎯 <b>BLACK BOX Ω — CONTRACT FIRST</b>\n\n<b>"+safe(row.get("symbol"))+"</b> — <b>"+safe(row.get("direction"))+"</b>\nContract: <b>"+safe(row.get("contract"))+"</b>\nVolume: "+safe(row.get("volume"))+" | OI: "+safe(row.get("open_interest"))+" | Vol/OI: <b>"+f"{n(row.get("volume_oi")):.2f}</b>\nIV: "+safe(row.get("iv"))+" | Spread: "+safe(row.get("spread_pct"))+"\nAnomaly: <b>"+f"{n(row.get("anomaly_score")):.0f}"+"/100</b>\n\n⚠️ العقد ملفت بحثياً؛ يجب التحقق من السهم والمحفز ومصدر البيانات قبل أي قرار.")
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--payload",default="data/live/three_path_intelligence.json"); ap.add_argument("--no-telegram",action="store_true"); a=ap.parse_args()
    payload=json.loads(Path(a.payload).read_text(encoding="utf-8"))
    omega_path=Path("data/live/black_box_omega.json")
    try:
        omega=json.loads(omega_path.read_text(encoding="utf-8")) if omega_path.exists() else {}
    except (OSError, ValueError):
        omega={}
    thresholds={"SMALL_CAP_PRE_EXPLOSION":float(os.getenv("THREE_PATH_SMALL_MIN","70")),"LARGE_CAP_CONTRACT_SELECTION":float(os.getenv("THREE_PATH_LARGE_MIN","78")),"CONTRACT_FIRST_RADAR":float(os.getenv("THREE_PATH_CONTRACT_MIN","75"))}
    state=load_state(); sent=state.setdefault("sent",{}); selected=[]; blocked=[]
    for path,rows in payload.items():
        if path not in thresholds or not isinstance(rows,list): continue
        for row in rows:
            metric=n(row.get("readiness",row.get("score",row.get("anomaly_score"))))
            if metric < thresholds[path] or not row.get("symbol"): continue
            if path=="SMALL_CAP_PRE_EXPLOSION" and str(row.get("stage")) in {"EXPLOSION","EXTENDED"}: continue
            guarded, reason = _omega_guard(path, row, omega)
            if not guarded:
                blocked.append({"path":path,"symbol":row.get("symbol"),"reason":reason})
                continue
            selected.append((path,row))
    token=os.getenv("TELEGRAM_BOT_TOKEN","").strip(); chat=os.getenv("TELEGRAM_CHAT_ID","").strip(); sent_count=0
    if not a.no_telegram and token and chat:
        for path,row in selected[:5]:
            k=key(path,row)
            if k in sent: continue
            send(token,chat,message(path,row)); sent[k]={"sent_at":now(),"metric":n(row.get("readiness",row.get("score",row.get("anomaly_score"))))}; sent_count+=1
    state["last_run_at"]=now(); state["last_selected"]=len(selected); state["last_blocked"]=blocked; state["last_sent"]=sent_count
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Three-path alerts: selected={len(selected)} sent={sent_count}")
if __name__=="__main__": main()
