"""Transparent configurable ranking and research leakage checks."""
from dataclasses import dataclass
from math import isfinite
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
    """Score explicitly supplied evidence only; unknown metrics are excluded, never imputed."""
    count=int(metrics.get('trade_count') or 0)
    if count<minimum_trades:
        return {'score':None,'eligible':False,'reason':f"minimum trade count {minimum_trades} not met",'components':{}}
    components={}
    def numeric(key):
        try: value=float(metrics[key])
        except (KeyError,TypeError,ValueError): return None
        return value if isfinite(value) else None
    net=numeric('net_profit'); gross_loss=numeric('gross_loss')
    if net is not None: components['net_profit']=_clamp(.5+net/(2*max(1,abs(net)+abs(gross_loss or 0))))
    pf=metrics.get('profit_factor')
    if pf=='infinite': components['profit_factor']=1.0
    else:
        pf=numeric('profit_factor')
        if pf is not None and pf>=0: components['profit_factor']=_clamp(pf/(1+pf))
    drawdown=numeric('max_drawdown_close_to_close')
    if drawdown is not None: components['drawdown']=1-_clamp(drawdown)
    expectancy=numeric('expectancy'); avg_loss=numeric('average_loss')
    if expectancy is not None: components['expectancy']=_clamp(.5+expectancy/(2*max(1,abs(expectancy)+abs(avg_loss or 0))))
    components['sample_size']=_clamp(count/(minimum_trades*5))
    for key,val in [('stability',stability),('walk_forward',walk_forward),('out_of_sample',out_of_sample)]:
        if val is not None:
            try:
                value=float(val)
                if isfinite(value): components[key]=_clamp(value)
            except (TypeError,ValueError): pass
    raw={k:max(0.0,float(getattr(weights,k))) for k in components}; total=sum(raw.values())
    score=sum(components[k]*raw[k] for k in components)/total if total else None
    return {'score':score,'eligible':score is not None,'reason':None if score is not None else 'no configured weight for available evidence','components':components,'weights_used':raw,'weights_renormalized_over_available_evidence':True}

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
def audit_validation(*, train_end:str, validation_start:str, validation_end:str, test_start:str, test_end:str, train_trade_count:int, validation_trade_count:int, test_trade_count:int, minimum_trades:int, lookahead_flag:bool=False, parameter_search_used_test:bool=False, fees_included:bool|None=None, slippage_included:bool|None=None, funding_included:bool|None=None, funding_applicable:bool=True, regime_coverage:bool, parameter_stability:float|None=None) -> dict:
    """Fail-closed audit: callers must provide separate actual trade counts per partition."""
    chronological=train_end < validation_start <= validation_end < test_start <= test_end
    counts={'train':int(train_trade_count),'validation':int(validation_trade_count),'test':int(test_trade_count)}
    enough={key:value>=minimum_trades for key,value in counts.items()}
    warnings=[]
    if not chronological: warnings.append('temporal_partition_overlap_or_reversal')
    if not all(enough.values()): warnings.append('minimum_trade_count_not_met_in_each_partition')
    if lookahead_flag: warnings.append('possible_lookahead_bias')
    if parameter_search_used_test: warnings.append('test_set_contaminated_by_selection')
    if fees_included is not True: warnings.append('fees_not_confirmed_included')
    if slippage_included is not True: warnings.append('slippage_not_confirmed_included')
    if funding_applicable and funding_included is not True: warnings.append('funding_not_confirmed_included')
    if not regime_coverage: warnings.append('market_regime_coverage_unknown')
    warnings.extend(['survivorship_bias_not_assessed','multiple_testing_and_selection_bias_warning'])
    if parameter_stability is None: warnings.append('parameter_stability_unavailable')
    passed=(chronological and all(enough.values()) and not lookahead_flag and not parameter_search_used_test and fees_included is True and slippage_included is True and (not funding_applicable or funding_included is True))
    return {'chronological_split_valid':chronological,'partition_trade_counts':counts,'minimum_trade_counts_met':enough,'minimum_trade_count_met':all(enough.values()),'passed':passed,'warnings':warnings,'train_end':train_end,'validation_window':[validation_start,validation_end],'test_window':[test_start,test_end],'parameter_stability':parameter_stability,'cost_coverage':{'fees':fees_included,'slippage':slippage_included,'funding_applicable':funding_applicable,'funding':funding_included}}
