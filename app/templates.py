"""Deterministic Pine v6 research templates; generated text is not compiler validation."""
from __future__ import annotations
import json

SIGNALS = {
    "EMA crossover": ("fast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})", "ta.crossover(fast, slow)", "ta.crossunder(fast, slow)"),
    "SMA crossover": ("fast=ta.sma(close, {p})\nslow=ta.sma(close, {slow})", "ta.crossover(fast, slow)", "ta.crossunder(fast, slow)"),
    "RSI reversal": ("rsi=ta.rsi(close, {p})", "ta.crossover(rsi, 30)", "ta.crossunder(rsi, 70)"),
    "MACD momentum": ("[macdLine, signalLine, _]=ta.macd(close, {p}, {slow}, 9)", "ta.crossover(macdLine, signalLine)", "ta.crossunder(macdLine, signalLine)"),
    "Bollinger Bands": ("basis=ta.sma(close, {p})\nband=ta.stdev(close, {p})*2", "ta.crossover(close, basis-band)", "ta.crossunder(close, basis+band)"),
    "Donchian breakout": ("upper=ta.highest(high, {p})[1]\nlower=ta.lowest(low, {p})[1]", "ta.crossover(close, upper)", "ta.crossunder(close, lower)"),
    "Hybrid": ("fast=ta.ema(close, {p})\nslow=ta.ema(close, {slow})\nrsi=ta.rsi(close, {p})", "ta.crossover(fast, slow) and rsi>50", "ta.crossunder(fast, slow) and rsi<50"),
}

def pine_source(*, name: str, family: str, direction: str, period: int, stop_loss_pct: float, take_profit_pct: float, risk_per_trade_pct: float, source_hash: str) -> str:
    logic, long_signal, short_signal = SIGNALS.get(family, SIGNALS["EMA crossover"])
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
