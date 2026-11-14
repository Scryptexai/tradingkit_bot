"""Deterministic Pine v6 research templates; generated text is not compiler validation."""
from __future__ import annotations
import json

# These names are selectable compatibility aliases, not independent algorithm families.
FAMILY_ALIASES = {
    "Mean reversion": "Bollinger Bands",
    "Multi-indicator confluence": "Hybrid",
    "Support/resistance": "Donchian breakout",
}
PARAMETER_SCHEMA = {
    "period": {"type": "integer", "min": 2, "max": 500, "default": 20},
    "stop_loss_pct": {"type": "number", "min": 0.1, "max": 50.0},
    "take_profit_pct": {"type": "number", "min": 0.1, "max": 100.0},
    "risk_per_trade_pct": {"type": "number", "min": 0.1, "max": 5.0},
}

SIGNALS = {
    "EMA crossover": ("fast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})", "ta.crossover(fast, slow)", "ta.crossunder(fast, slow)"),
    "SMA crossover": ("fast=ta.sma(close, {p})\nslow=ta.sma(close, {slow})", "ta.crossover(fast, slow)", "ta.crossunder(fast, slow)"),
    "RSI reversal": ("rsi=ta.rsi(close, {p})", "ta.crossover(rsi, 30)", "ta.crossunder(rsi, 70)"),
    "MACD momentum": ("[macdLine, signalLine, _]=ta.macd(close, {p}, {slow}, 9)", "ta.crossover(macdLine, signalLine)", "ta.crossunder(macdLine, signalLine)"),
    "Bollinger Bands": ("basis=ta.sma(close, {p})\nband=ta.stdev(close, {p})*2", "ta.crossover(close, basis-band)", "ta.crossunder(close, basis+band)"),
    "Donchian breakout": ("upper=ta.highest(high, {p})[1]\nlower=ta.lowest(low, {p})[1]", "ta.crossover(close, upper)", "ta.crossunder(close, lower)"),
    "Hybrid": ("fast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})\nrsi=ta.rsi(close, {p})", "ta.crossover(fast, slow) and rsi>50", "ta.crossunder(fast, slow) and rsi<50"),
    "VWAP": ("vwapLine=ta.vwap(hlc3)", "ta.crossover(close, vwapLine)", "ta.crossunder(close, vwapLine)"),
    "Supertrend": ("[superLine, superDir]=ta.supertrend(3, {p})", "ta.crossunder(superDir, 0)", "ta.crossover(superDir, 0)"),
    "ADX trend filter": ("[diPlus, diMinus, adx]=ta.dmi({p}, {p})", "ta.crossover(diPlus, diMinus) and adx>20", "ta.crossover(diMinus, diPlus) and adx>20"),
    "ATR breakout": ("atr=ta.atr({p})\nupper=ta.sma(close, {p})+atr\nlower=ta.sma(close, {p})-atr", "ta.crossover(close, upper)", "ta.crossunder(close, lower)"),
    "Ichimoku": ("conversion=(ta.highest(high, {p})+ta.lowest(low, {p}))/2\nbase=(ta.highest(high, {slow})+ta.lowest(low, {slow}))/2", "ta.crossover(conversion, base)", "ta.crossunder(conversion, base)"),
    "Stochastic": ("k=ta.stoch(close, high, low, {p})\nd=ta.sma(k, 3)", "ta.crossover(k, d) and k<30", "ta.crossunder(k, d) and k>70"),
    "Momentum continuation": ("roc=ta.roc(close, {p})", "ta.crossover(roc, 0)", "ta.crossunder(roc, 0)"),
    "Volume breakout": ("upper=ta.highest(high, {p})[1]\nlower=ta.lowest(low, {p})[1]\nvolumeOk=volume>ta.sma(volume, {p})", "ta.crossover(close, upper) and volumeOk", "ta.crossunder(close, lower) and volumeOk"),
    "Trend following": ("fast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})", "fast>slow and ta.rising(fast, 2)", "fast<slow and ta.falling(fast, 2)"),
    "Multi-timeframe confirmation": ("htfFast=request.security(syminfo.tickerid, '240', ta.ema(close, {p}), lookahead=barmerge.lookahead_off)\nhtfSlow=request.security(syminfo.tickerid, '240', ta.ema(close, {slow}), lookahead=barmerge.lookahead_off)\nfast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})", "ta.crossover(fast, slow) and htfFast>htfSlow", "ta.crossunder(fast, slow) and htfFast<htfSlow"),
}

def pine_source(*, name: str, family: str, direction: str, period: int, stop_loss_pct: float, take_profit_pct: float, risk_per_trade_pct: float, source_hash: str) -> str:
    if family not in SIGNALS and family not in FAMILY_ALIASES: raise ValueError(f"Unsupported strategy family: {family}")
    if direction not in {"Long", "Short", "Both"}: raise ValueError("direction must be Long, Short, or Both")
    if not PARAMETER_SCHEMA["period"]["min"] <= period <= PARAMETER_SCHEMA["period"]["max"]: raise ValueError("period outside supported range")
    if not PARAMETER_SCHEMA["stop_loss_pct"]["min"] <= stop_loss_pct <= PARAMETER_SCHEMA["stop_loss_pct"]["max"]: raise ValueError("stop_loss_pct outside supported range")
    if not PARAMETER_SCHEMA["take_profit_pct"]["min"] <= take_profit_pct <= PARAMETER_SCHEMA["take_profit_pct"]["max"]: raise ValueError("take_profit_pct outside supported range")
    if not PARAMETER_SCHEMA["risk_per_trade_pct"]["min"] <= risk_per_trade_pct <= PARAMETER_SCHEMA["risk_per_trade_pct"]["max"]: raise ValueError("risk_per_trade_pct outside supported range")
    canonical_family=FAMILY_ALIASES.get(family, family)
    logic, long_signal, short_signal = SIGNALS[canonical_family]
    if direction == "Long": short_signal = "false"
    elif direction == "Short": long_signal = "false"
    qty_pct = risk_per_trade_pct * 100 / stop_loss_pct
    title = json.dumps(f"{name} {source_hash[:8]}")
    return f'''//@version=6
strategy({title}, overlay=true, pyramiding=0, default_qty_type=strategy.percent_of_equity, default_qty_value={qty_pct:.4f}, process_orders_on_close=true)
// Generated research draft. Official compiler validation and instrument-specific execution assumptions remain required.
// Source hash: {source_hash}
{logic.format(p=period, slow=period * 3)}
if {long_signal}
    strategy.entry("L", strategy.long)
if {short_signal}
    strategy.entry("S", strategy.short)
longStop=strategy.position_avg_price*(1-{stop_loss_pct}/100)
longTarget=strategy.position_avg_price*(1+{take_profit_pct}/100)
shortStop=strategy.position_avg_price*(1+{stop_loss_pct}/100)
shortTarget=strategy.position_avg_price*(1-{take_profit_pct}/100)
strategy.exit("XL", from_entry="L", stop=longStop, limit=longTarget)
strategy.exit("XS", from_entry="S", stop=shortStop, limit=shortTarget)
'''
