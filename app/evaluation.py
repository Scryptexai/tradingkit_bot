"""Transparent configurable ranking and research leakage checks."""
from dataclasses import dataclass
from typing import Any
import re

@dataclass
class ScoreWeights:
    net_profit: float=.22
    profit_factor: float=.16
    drawdown: float=.16
    expectancy: float=.12
    sample_size: float=.10
    stability: float=.08
    walk_forward: float=.08
    out_of_sample: float=.08

def _clamp(x): return max(0.0,min(1.0,float(x)))
def multiobjective_score(metrics:dict[str,Any], *, stability:float|None, walk_forward:float|None, out_of_sample:float|None, weights:ScoreWeights=ScoreWeights(), minimum_trades:int=30) -> dict:
    """Score only explicitly supplied evidence; missing evidence is not silently imputed."""
    if metrics.get('trade_count',0)<minimum_trades:
        return {'score':None,'eligible':False,'reason':f"minimum trade count {minimum_trades} not met",'components':{}}
    net=float(metrics.get('net_profit',0)); gross_loss=float(metrics.get('gross_loss',0))
    exp=float(metrics.get('expectancy') or 0); avg_loss=float(metrics.get('average_loss') or 0)
    components={
      'net_profit':_clamp(.5+net/(2*max(1,abs(net)+gross_loss))),
      'profit_factor':_clamp(float(metrics['profit_factor'])/(1+float(metrics['profit_factor']))) if isinstance(metrics.get('profit_factor'),(int,float)) else 0,
      'drawdown':1-_clamp(float(metrics.get('max_drawdown_close_to_close') or 1)),
      'expectancy':_clamp(.5+exp/(2*max(1,abs(exp)+abs(avg_loss)))),
      'sample_size':_clamp(metrics['trade_count']/(minimum_trades*5))}
    for key,val in [('stability',stability),('walk_forward',walk_forward),('out_of_sample',out_of_sample)]:
        if val is not None: components[key]=_clamp(val)
    raw={k:getattr(weights,k) for k in components}; total=sum(raw.values())
    return {'score':sum(components[k]*raw[k] for k in components)/total if total else None,'eligible':True,'reason':None,'components':components,'weights_used':raw,'weights_renormalized_over_available_evidence':True}

def parameter_stability(scores:list[float])->float|None:
    """Population coefficient-of-variation stability; higher means tighter normalized scores."""
    if len(scores)<2:return None
    mean=sum(scores)/len(scores)
    if mean==0:return 1.0 if all(x==0 for x in scores) else 0.0
    variance=sum((x-mean)**2 for x in scores)/len(scores)
    return _clamp(1-(variance**.5)/abs(mean))
def walk_forward_consistency(fold_returns:list[float])->float|None:
    """Fraction profitable folds, weighted with dispersion penalty; requires at least two folds."""
    if len(fold_returns)<2:return None
    mean=sum(fold_returns)/len(fold_returns); positive=sum(x>0 for x in fold_returns)/len(fold_returns)
    variance=sum((x-mean)**2 for x in fold_returns)/len(fold_returns); cv=(variance**.5)/max(abs(mean),1e-12)
    return _clamp(positive/(1+cv))
def inspect_pine_source(source:str)->list[dict]:
    """Heuristic static warnings only; TradingView/TradingKit compiler remains authoritative."""
    patterns=[(r'barmerge\.lookahead_on','possible_lookahead','request.security lookahead_on can leak future values'),(r'lookahead\s*=\s*barmerge\.lookahead_on','possible_lookahead','lookahead_on specified in a request'),(r'barstate\.isrealtime','realtime_dependency','realtime-only logic can differ historically'),(r'\bstrategy\.(?:position_avg_price|opentrades)\b','stateful_execution','state-dependent strategy behavior requires review')]
    return [{'code':code,'message':msg} for pattern,code,msg in patterns if re.search(pattern,source,re.I)]
def audit_validation(*, train_end:str, validation_start:str, validation_end:str, test_start:str, test_end:str, trade_count:int, minimum_trades:int, lookahead_flag:bool=False, parameter_search_used_test:bool=False, costs_included:bool, regime_coverage:bool, parameter_stability:float|None=None) -> dict:
    chronological=train_end < validation_start <= validation_end < test_start <= test_end
    warnings=[]
    if not chronological: warnings.append('temporal_partition_overlap_or_reversal')
    if trade_count<minimum_trades: warnings.append('insufficient_trade_sample')
    if lookahead_flag: warnings.append('possible_lookahead_bias')
    if parameter_search_used_test: warnings.append('test_set_contaminated_by_selection')
    if not costs_included: warnings.append('transaction_costs_not_included')
    if not regime_coverage: warnings.append('market_regime_coverage_unknown')
    warnings.extend(['survivorship_bias_not_assessed','multiple_testing_and_selection_bias_warning'])
    if parameter_stability is None: warnings.append('parameter_stability_unavailable')
    return {'chronological_split_valid':chronological,'minimum_trade_count_met':trade_count>=minimum_trades,'passed':chronological and trade_count>=minimum_trades and not lookahead_flag and not parameter_search_used_test and costs_included,'warnings':warnings,'train_end':train_end,'validation_window':[validation_start,validation_end],'test_window':[test_start,test_end],'parameter_stability':parameter_stability}
