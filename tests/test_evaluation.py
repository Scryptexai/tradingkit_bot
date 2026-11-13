from app.evaluation import audit_validation, multiobjective_score, inspect_pine_source, parameter_stability, walk_forward_consistency
from app.execution_gate import GateState, check

def test_gate_requires_every_single_precondition():
    assert not check(GateState(user_pressed_start=True))['allowed']
    assert check(GateState(True,True,True,True,True,True))['allowed']
    assert not check(GateState(True,True,True,True,True,False))['allowed']

def test_ranking_requires_sample_and_uses_multiple_objectives():
    metrics={'trade_count':100,'net_profit':500,'gross_loss':200,'profit_factor':1.7,'max_drawdown_close_to_close':.2,'expectancy':5}
    result=multiobjective_score(metrics,stability=.7,walk_forward=.65,out_of_sample=.6)
    assert result['eligible'] and 0<=result['score']<=1
    assert set(result['components']) >= {'profit_factor','drawdown','sample_size','out_of_sample'}
    assert not multiobjective_score({**metrics,'trade_count':4},stability=.9,walk_forward=.9,out_of_sample=.9)['eligible']
    assert parameter_stability([.9,.9])==1
    assert walk_forward_consistency([1,-1,2]) is not None

def test_multiobjective_score_does_not_treat_missing_metrics_as_zero_performance():
    result=multiobjective_score({'trade_count':60,'net_profit':100},stability=None,walk_forward=None,out_of_sample=None)
    assert result['eligible']
    assert set(result['components'])=={'net_profit','sample_size'}
    assert 'profit_factor' not in result['components'] and 'drawdown' not in result['components']

def test_validation_split_detects_leakage_cost_and_bias():
    r=audit_validation(train_end='2023-12-31',validation_start='2024-01-01',validation_end='2024-06-30',test_start='2024-07-01',test_end='2024-12-31',train_trade_count=50,validation_trade_count=35,test_trade_count=32,minimum_trades=30,parameter_search_used_test=True,fees_included=False,slippage_included=False,funding_included=False,regime_coverage=False)
    assert not r['passed'] and 'test_set_contaminated_by_selection' in r['warnings']
    assert 'survivorship_bias_not_assessed' in r['warnings'] and 'fees_not_confirmed_included' in r['warnings'] and 'slippage_not_confirmed_included' in r['warnings']
    assert audit_validation(train_end='2024-05-01',validation_start='2024-01-01',validation_end='2024-02-01',test_start='2024-03-01',test_end='2024-04-01',train_trade_count=50,validation_trade_count=40,test_trade_count=35,minimum_trades=30,fees_included=True,slippage_included=True,funding_included=True,regime_coverage=True)['chronological_split_valid'] is False

def test_validation_fails_if_any_partition_lacks_minimum_actual_trades_or_cost_coverage():
    result=audit_validation(train_end='2023-12-31',validation_start='2024-01-01',validation_end='2024-03-31',test_start='2024-04-01',test_end='2024-06-30',train_trade_count=100,validation_trade_count=29,test_trade_count=50,minimum_trades=30,fees_included=True,slippage_included=True,funding_applicable=False,funding_included=None,regime_coverage=True)
    assert not result['passed']
    assert result['minimum_trade_counts_met']=={'train':True,'validation':False,'test':True}
    assert 'minimum_trade_count_not_met_in_each_partition' in result['warnings']

def test_pine_lookahead_detection_is_explicitly_heuristic():
    warnings=inspect_pine_source('request.security(syminfo.tickerid, "1D", close, lookahead=barmerge.lookahead_on)')
    assert any(w['code']=='possible_lookahead' for w in warnings)
