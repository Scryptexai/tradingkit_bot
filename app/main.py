"""AI QUANT LAB local research foundation. Backtests are never simulated."""
from __future__ import annotations
import hashlib, json, os, sqlite3, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()
from .report_store import init_report_tables
from .migrations import apply as apply_migrations
from .execution_gate import GateState, check as check_execution_gate
from .evaluation import multiobjective_score, ScoreWeights, inspect_pine_source
from .templates import pine_source

DB = Path(os.getenv("QUANTLAB_DB", "data/quantlab.sqlite3"))
FAMILIES = ["EMA crossover", "SMA crossover", "RSI reversal", "MACD momentum", "Bollinger Bands", "VWAP", "Supertrend", "ADX trend filter", "ATR breakout", "Donchian breakout", "Ichimoku", "Stochastic", "Mean reversion", "Momentum continuation", "Volume breakout", "Trend following", "Support/resistance", "Multi-indicator confluence", "Multi-timeframe confirmation", "Hybrid"]
def now(): return datetime.now(timezone.utc).isoformat()
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,name TEXT,family TEXT,version INTEGER,market TEXT,timeframe TEXT,direction TEXT,parameters TEXT,rules TEXT,source TEXT,source_hash TEXT UNIQUE,created_at TEXT,status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,name TEXT,market TEXT,status TEXT,total INTEGER,created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,campaign_id TEXT,type TEXT,status TEXT,description TEXT,created_at TEXT)''')
    init_report_tables(c)
    apply_migrations(c)
    return c
def emit(c, typ, status, description, campaign_id=None):
    c.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",(str(uuid.uuid4()),campaign_id,typ,status,description,now()))
def audit(c,action,entity_type,entity_id,details):
    c.execute("INSERT INTO audit_logs VALUES(?,?,?,?,?,?,?)",(str(uuid.uuid4()),None,action,entity_type,entity_id,json.dumps(details,sort_keys=True),now()))
class Generate(BaseModel):
    families:list[str]=Field(default_factory=lambda:FAMILIES[:3]); count:int=Field(ge=1,le=200); market:str=Field(default="BTCUSDT",min_length=1,max_length=40); timeframe:str="1h"; direction:Literal["Long","Short","Both"]="Both"
app=FastAPI(title="AI QUANT LAB",version="0.2.0",description="Local strategy research control plane; real TradingKit execution requires later authenticated host integration.")
app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/api/health")
def health(): return {"status":"ok","database":"sqlite","execution":"unavailable","reason":"No authenticated TradingKit MCP worker is configured."}
@app.get("/api/summary")
def summary():
    c=db(); s=c.execute("SELECT count(*) n FROM strategies").fetchone()["n"]; k=c.execute("SELECT count(*) n FROM campaigns").fetchone()["n"]; e=c.execute("SELECT count(*) n FROM events").fetchone()["n"]; r=c.execute("SELECT count(*) n FROM reports").fetchone()["n"]; active=c.execute("SELECT count(*) n FROM backtest_jobs WHERE status IN ('accepted','running','report_retrieval_started')").fetchone()["n"]; validated=c.execute("SELECT count(*) n FROM validations WHERE status IN ('validated','passed')").fetchone()["n"]; c.close()
    return {"strategies":s,"campaigns":k,"backtests_completed":r,"active_jobs":active,"validated":validated,"activity_events":e,"results_source":"persisted records","execution":"unavailable"}
@app.get("/api/connections")
def connections():
    c=db(); row=c.execute("SELECT worker_id,status,capabilities_json,seen_at FROM worker_heartbeats ORDER BY seen_at DESC LIMIT 1").fetchone(); c.close()
    worker={"status":"offline","worker_id":None,"last_seen":None,"capabilities":None}
    if row:
        try: live=(datetime.now(timezone.utc)-datetime.fromisoformat(row['seen_at'])).total_seconds() <= 30
        except ValueError: live=False
        worker={"status":row['status'] if live else "stale/offline","worker_id":row['worker_id'],"last_seen":row['seen_at'],"capabilities":json.loads(row['capabilities_json'])}
    return {"tradingkit":{"status":"not_connected","authentication":"not_verified","capabilities":None,"last_checked":None,"reason":"This local starter has no host-managed MCP OAuth bridge."},"worker":worker}
@app.get("/api/execution/readiness")
def execution_readiness(): return check_execution_gate(GateState())
@app.get("/api/strategies")
def strategies():
    c=db(); rows=c.execute("SELECT * FROM strategies ORDER BY created_at DESC").fetchall(); c.close()
    return [dict(r,parameters=json.loads(r["parameters"]),rules=json.loads(r["rules"])) for r in rows]
@app.get("/api/strategies/{sid}")
def strategy_detail(sid:str):
    c=db(); r=c.execute("SELECT * FROM strategies WHERE id=?",(sid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,"Strategy not found")
    result=dict(r,parameters=json.loads(r["parameters"]),rules=json.loads(r["rules"]))
    c=db(); reps=c.execute("SELECT id,external_job_id,external_report_id,market,timeframe,returned_at,metrics FROM reports WHERE strategy_id=? ORDER BY returned_at DESC",(sid,)).fetchall()
    result['reports']=[dict(x,metrics=json.loads(x['metrics'])) for x in reps]
    result['trades']=[]
    if reps:
        for rep in reps:
            trades=c.execute("SELECT trade_index,pnl,fees,funding,side,slippage,entry_time,exit_time,notional,risk_amount FROM report_trades WHERE report_id=? ORDER BY trade_index",(rep['id'],)).fetchall()
            result['trades'].extend([dict(x,report_id=rep['id']) for x in trades])
    result['validation_history']=[dict(x,plan=json.loads(x['plan_json']),result=json.loads(x['result_json']) if x['result_json'] else None) for x in c.execute("SELECT * FROM validations WHERE strategy_id=? ORDER BY created_at DESC",(sid,)).fetchall()]
    c.close(); result['source_warnings']=inspect_pine_source(result['source']); result['execution_assumptions']={'available':'Only assumptions returned in persisted actual reports; unavailable until an authenticated adapter exists.'}
    return result
@app.post("/api/strategies/generate")
def generate(req:Generate):
    unknown=set(req.families)-set(FAMILIES)
    if unknown: raise HTTPException(400,f"Unsupported families: {sorted(unknown)}")
    c=db(); made=[]
    families=req.families or FAMILIES
    for i in range(req.count):
        family=families[i%len(families)]; period=10+(i%5)*5
        rules={"family":family,"market":req.market,"timeframe":req.timeframe,"direction":req.direction,"entry":"family signal; close-confirmed evaluation","exit":"opposite signal or risk exit"}
        params={"period":period,"stop_loss_pct":1.0+(i%3)*0.5,"take_profit_pct":2.0+(i%4),"risk_per_trade_pct":1.0,"risk_reward":(2.0+(i%4))/(1.0+(i%3)*0.5)}
        normalized=json.dumps({"rules":rules,"parameters":params},sort_keys=True,separators=(",",":")); digest=hashlib.sha256(normalized.encode()).hexdigest()
        if c.execute("SELECT 1 FROM strategies WHERE source_hash=?",(digest,)).fetchone(): continue
        sid=str(uuid.uuid4()); name=f"{family} · {req.timeframe} · {digest[:6]}"
        source=pine_source(name=name,family=family,direction=req.direction,period=period,stop_loss_pct=params['stop_loss_pct'],take_profit_pct=params['take_profit_pct'],risk_per_trade_pct=1.0,source_hash=digest)
        c.execute("INSERT INTO strategies VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(sid,name,family,1,req.market,req.timeframe,req.direction,json.dumps(params),json.dumps(rules),source,digest,now(),"generated"))
        c.execute("INSERT INTO strategy_versions VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),sid,1,source,digest,json.dumps(params,sort_keys=True),json.dumps(rules,sort_keys=True),now()))
        made.append({"id":sid,"name":name,"family":family,"version":1,"market":req.market,"timeframe":req.timeframe,"parameters":params,"status":"generated","source_hash":digest})
    if made:
        emit(c,"strategy_candidates_generated","success",f"Created {len(made)} structured candidates; no backtests submitted.")
        audit(c,"strategy_candidates_generated","strategy_batch",None,{"created":len(made),"market":req.market,"timeframe":req.timeframe,"families":families})
    c.commit(); c.close()
    return {"requested":req.count,"created":len(made),"duplicates_skipped":req.count-len(made),"items":made,"execution":"not_started"}
@app.get("/api/leaderboard")
def leaderboard(sort:str="multiobjective",minimum_trades:int=Query(default=30,ge=1,le=100000),min_net_profit:float|None=None,max_drawdown:float|None=Query(default=None,ge=0,le=1),min_stability:float|None=Query(default=None,ge=0,le=1),profit_weight:float=Query(default=.22,ge=0,le=1),profit_factor_weight:float=Query(default=.16,ge=0,le=1),drawdown_weight:float=Query(default=.16,ge=0,le=1),expectancy_weight:float=Query(default=.12,ge=0,le=1),sample_weight:float=Query(default=.10,ge=0,le=1),stability_weight:float=Query(default=.08,ge=0,le=1),walk_forward_weight:float=Query(default=.08,ge=0,le=1),out_of_sample_weight:float=Query(default=.08,ge=0,le=1)):
    allowed={"multiobjective","best_wr","best_pf","lowest_dd","best_expectancy","most_stable","best_oos"}
    if sort not in allowed: raise HTTPException(400,"Unsupported leaderboard sort")
    weights=ScoreWeights(net_profit=profit_weight,profit_factor=profit_factor_weight,drawdown=drawdown_weight,expectancy=expectancy_weight,sample_size=sample_weight,stability=stability_weight,walk_forward=walk_forward_weight,out_of_sample=out_of_sample_weight)
    c=db(); rows=c.execute("SELECT r.*,s.name,s.family FROM reports r LEFT JOIN strategies s ON s.id=r.strategy_id ORDER BY r.returned_at DESC").fetchall()
    validation_rows=c.execute("SELECT strategy_id,status,result_json,created_at FROM validations ORDER BY created_at DESC").fetchall(); c.close()
    evidence={}
    for v in validation_rows:
        if v['strategy_id'] in evidence: continue
        try: result=json.loads(v['result_json']) if v['result_json'] else {}
        except (TypeError,ValueError): result={}
        evidence[v['strategy_id']]={"status":v['status'],"stability":result.get('stability_score',result.get('parameter_stability')),"walk_forward":result.get('walk_forward_score',result.get('walk_forward_consistency')),"out_of_sample":result.get('out_of_sample_score',result.get('out_of_sample_result'))}
    items=[]
    for row in rows:
        r=dict(row); m=json.loads(r['metrics']); ev=evidence.get(r['strategy_id'],{})
        if int(m.get('trade_count') or 0)<minimum_trades: continue
        net=m.get('net_profit'); dd=m.get('max_drawdown_close_to_close'); stability=ev.get('stability')
        if min_net_profit is not None and (net is None or float(net)<min_net_profit): continue
        if max_drawdown is not None and (dd is None or float(dd)>max_drawdown): continue
        if min_stability is not None and (stability is None or float(stability)<min_stability): continue
        score=multiobjective_score(m,stability=stability,walk_forward=ev.get('walk_forward'),out_of_sample=ev.get('out_of_sample'),weights=weights,minimum_trades=minimum_trades)
        items.append({"strategy_id":r['strategy_id'],"name":r['name'] or r['strategy_id'],"family":r['family'],"report_id":r['id'],"market":r['market'],"timeframe":r['timeframe'],"win_rate":m.get('win_rate'),"net_profit":net,"profit_factor":m.get('profit_factor'),"max_drawdown":dd,"expectancy":m.get('expectancy'),"trade_count":m.get('trade_count'),"walk_forward_score":ev.get('walk_forward'),"out_of_sample_result":ev.get('out_of_sample'),"stability_score":stability,"validation_status":ev.get('status','unvalidated'),"score":score['score'],"eligible":score['eligible'],"score_components":score['components'],"metrics":m})
    key={"multiobjective":lambda x:x['score'] if x['score'] is not None else -1,"best_wr":lambda x:x['win_rate'] if x['win_rate'] is not None else -1,"best_pf":lambda x:x['profit_factor'] if isinstance(x['profit_factor'],(int,float)) else -1,"lowest_dd":lambda x:-x['max_drawdown'] if x['max_drawdown'] is not None else -1,"best_expectancy":lambda x:x['expectancy'] if x['expectancy'] is not None else -1,"most_stable":lambda x:x['stability_score'] if x['stability_score'] is not None else -1,"best_oos":lambda x:x['out_of_sample_result'] if isinstance(x['out_of_sample_result'],(int,float)) else -1}[sort]
    items.sort(key=key,reverse=True)
    for i,item in enumerate(items,1):item['rank']=i
    return {"sort":sort,"minimum_trades":minimum_trades,"results":items,"note":"Only persisted report/validation evidence is ranked. Unavailable validation dimensions remain null and are excluded from objective weights."}
@app.get("/api/reports")
def reports():
    c=db(); rows=c.execute("SELECT id,strategy_id,adapter,external_job_id,external_report_id,source_hash,market,timeframe,returned_at,metrics FROM reports ORDER BY returned_at DESC").fetchall(); c.close()
    return [dict(r,metrics=json.loads(r["metrics"])) for r in rows]
@app.get("/api/campaigns")
def campaigns():
    c=db(); rows=c.execute("SELECT * FROM campaigns ORDER BY created_at DESC").fetchall(); c.close(); return [dict(r) for r in rows]
@app.post("/api/campaigns")
def create_campaign(payload:dict):
    try: total=int(payload.get("total",0))
    except (TypeError,ValueError): raise HTTPException(400,"total must be an integer")
    if total<0 or total>10000: raise HTTPException(400,"total must be between 0 and 10000")
    name=str(payload.get("name","Research campaign"))[:120]; market=str(payload.get("market","BTCUSDT"))[:40]
    cid=str(uuid.uuid4()); c=db(); c.execute("INSERT INTO campaigns VALUES(?,?,?,?,?,?)",(cid,name,market,"draft",total,now())); emit(c,"campaign_created","draft",f"Draft campaign {name} created; execution has not started.",cid); audit(c,"campaign_created","campaign",cid,{"market":market,"total":total}); c.commit(); c.close()
    return {"id":cid,"name":name,"market":market,"status":"draft","total":total}
@app.post("/api/campaigns/{campaign_id}/start")
def start_campaign(campaign_id:str):
    c=db(); row=c.execute("SELECT * FROM campaigns WHERE id=?",(campaign_id,)).fetchone(); c.close()
    if not row: raise HTTPException(404,"Campaign not found")
    gate=check_execution_gate(GateState(user_pressed_start=True))
    raise HTTPException(409,{"message":"No jobs submitted.","execution_gate":gate})
@app.get("/api/events")
def events():
    c=db(); rows=c.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 100").fetchall(); c.close(); return [dict(r) for r in rows]
@app.get("/",include_in_schema=False)
def home(): return FileResponse("static/index.html")
