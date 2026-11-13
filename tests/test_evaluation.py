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

def test_validation_split_detects_leakage_cost_and_bias():
    r=audit_validation(train_end='2023-12-31',validation_start='2024-01-01',validation_end='2024-06-30',test_start='2024-07-01',test_end='2024-12-31',trade_count=50,minimum_trades=30,parameter_search_used_test=True,costs_included=False,regime_coverage=False)
    assert not r['passed'] and 'test_set_contaminated_by_selection' in r['warnings']
    assert 'survivorship_bias_not_assessed' in r['warnings'] and 'transaction_costs_not_included' in r['warnings']
    assert audit_validation(train_end='2024-05-01',validation_start='2024-01-01',validation_end='2024-02-01',test_start='2024-03-01',test_end='2024-04-01',trade_count=50,minimum_trades=30,costs_included=True,regime_coverage=True)['chronological_split_valid'] is False

def test_pine_lookahead_detection_is_explicitly_heuristic():
    warnings=inspect_pine_source('request.security(syminfo.tickerid, "1D", close, lookahead=barmerge.lookahead_on)')
    assert any(w['code']=='possible_lookahead' for w in warnings)
