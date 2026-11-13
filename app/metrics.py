"""Quant metrics over closed trade records only; does not fabricate equity or trade data."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Iterable

@dataclass(frozen=True)
class ClosedTrade:
    pnl: float
    fees: float = 0.0
    funding: float = 0.0
    side: str = "long"
    entry_time: str | None = None
    exit_time: str | None = None
    notional: float | None = None
    risk_amount: float | None = None
    slippage: float = 0.0

    @property
    def net(self) -> float:
        return self.pnl - self.fees - self.funding - self.slippage

def evaluate(trades: Iterable[ClosedTrade], *, initial_capital: float = 1.0) -> dict:
    """Calculate deterministic closed-trade metrics; drawdown is trade-close equity drawdown.

    Equity timing/intratrade drawdown cannot be recovered from trade PnL alone; callers must
    label this as close-to-close and use a full equity series for canonical report drawdown.
    """
    ts=list(trades)
    if initial_capital <= 0: raise ValueError("initial_capital must be positive")
    if any(t.side not in ("long","short") for t in ts): raise ValueError("side must be long or short")
    nets=[float(t.net) for t in ts]
    # Gross P/L excludes fees/funding; profit factor uses net winning/losing trades.
    gp=sum(t.pnl for t in ts if t.pnl>0); gl=-sum(t.pnl for t in ts if t.pnl<0)
    wins=[x for x in nets if x>0]; losses=[x for x in nets if x<0]
    net_wins=sum(wins); net_losses=-sum(losses)
    equity=float(initial_capital); peak=equity; max_dd=0.0; streak=0; max_win=max_loss=0; current_kind=None
    for pnl in nets:
        equity += pnl; peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak>0 else 0)
        kind="win" if pnl>0 else "loss" if pnl<0 else None
        if kind and kind==current_kind: streak+=1
        elif kind: streak=1; current_kind=kind
        else: streak=0; current_kind=None
        if kind=="win": max_win=max(max_win,streak)
        if kind=="loss": max_loss=max(max_loss,streak)
    longs=[t for t in ts if t.side=="long"]; shorts=[t for t in ts if t.side=="short"]
    cost=sum(t.fees+t.funding+t.slippage for t in ts)
    avgwin=sum(wins)/len(wins) if wins else None; avgloss=sum(losses)/len(losses) if losses else None
    returns=[t.net/t.notional for t in ts if t.notional and t.notional>0]
    mean=sum(returns)/len(returns) if returns else None
    variance=sum((x-mean)**2 for x in returns)/len(returns) if returns else None
    downside=[min(0,x) for x in returns]; downside_dev=sqrt(sum(x*x for x in downside)/len(downside)) if returns else None
    std=sqrt(variance) if variance is not None else None
    valid_times=[]
    for t in ts:
        if t.entry_time and t.exit_time:
            try: valid_times.append((datetime.fromisoformat(t.entry_time.replace('Z','+00:00')),datetime.fromisoformat(t.exit_time.replace('Z','+00:00'))))
            except ValueError: pass
    durations=[(b-a).total_seconds() for a,b in valid_times if b>=a]
    total_period=(max((b for _,b in valid_times),default=None)-min((a for a,_ in valid_times),default=None)).total_seconds() if valid_times else None
    exp_seconds=sum(durations)
    return {"trade_count":len(ts),"win_rate":len(wins)/len(ts) if ts else None,"net_profit":sum(nets),"gross_profit":gp,"gross_loss":gl,"profit_factor":net_wins/net_losses if net_losses else (None if net_wins==0 else "infinite"),"average_win":avgwin,"average_loss":avgloss,"expectancy":sum(nets)/len(nets) if nets else None,"risk_reward":(avgwin/abs(avgloss)) if avgwin is not None and avgloss else None,"max_drawdown_close_to_close":max_dd if ts else None,"max_consecutive_wins":max_win,"max_consecutive_losses":max_loss,"long_win_rate":sum(t.net>0 for t in longs)/len(longs) if longs else None,"short_win_rate":sum(t.net>0 for t in shorts)/len(shorts) if shorts else None,"average_holding_seconds":sum(durations)/len(durations) if durations else None,"exposure_time_ratio":min(1.0,exp_seconds/total_period) if total_period and total_period>0 else None,"average_notional_exposure":sum(t.notional or 0 for t in ts)/len(ts) if any(t.notional is not None for t in ts) else None,"sharpe_per_trade":(mean/std*sqrt(len(returns))) if returns and std else None,"sortino_per_trade":(mean/downside_dev*sqrt(len(returns))) if returns and downside_dev else None,"calmar_close_to_close":(sum(nets)/initial_capital/max_dd) if max_dd>0 else None,"transaction_costs":cost,"fees":sum(t.fees for t in ts),"funding_costs":sum(t.funding for t in ts),"slippage_costs":sum(t.slippage for t in ts),"drawdown_definition":"close-to-close trade PnL; excludes intratrade excursions","sharpe_sortino_definition":"per-trade returns based on notional; sqrt(N) scaling, not calendar annualized","costs_assumptions":"Trade-provided fees, funding and slippage; missing values are treated as zero"}
