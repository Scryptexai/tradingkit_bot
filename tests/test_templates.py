import hashlib
import pytest
from app.main import FAMILIES
from app.templates import pine_source, SIGNALS, FAMILY_ALIASES

@pytest.mark.parametrize('family', FAMILIES)
def test_every_factory_family_has_distinct_explicit_signal_template(family):
    assert family in SIGNALS or family in FAMILY_ALIASES, f'{family} must not silently fall back to another strategy'
    digest=hashlib.sha256(family.encode()).hexdigest()
    source=pine_source(name='test',family=family,direction='Both',period=15,stop_loss_pct=1.5,take_profit_pct=3,risk_per_trade_pct=1,source_hash=digest)
    assert source.startswith('//@version=6')
    assert 'strategy.entry("L"' in source and 'strategy.entry("S"' in source
    assert 'strategy.exit("XL"' in source and 'strategy.exit("XS"' in source
    assert 'strategy.entry("S", strategy.short)\n\nlongStop' not in source

def test_aliases_are_explicit_and_unsupported_families_are_rejected():
    for alias,canonical in FAMILY_ALIASES.items():
        alias_source=pine_source(name=alias,family=alias,direction='Both',period=15,stop_loss_pct=1.5,take_profit_pct=3,risk_per_trade_pct=1,source_hash='abc123456')
        canonical_source=pine_source(name=canonical,family=canonical,direction='Both',period=15,stop_loss_pct=1.5,take_profit_pct=3,risk_per_trade_pct=1,source_hash='abc123456')
        assert alias_source.split('// Source hash:')[1].splitlines()[1:] == canonical_source.split('// Source hash:')[1].splitlines()[1:]
    with pytest.raises(ValueError,match='Unsupported strategy family'):
        pine_source(name='x',family='invented',direction='Both',period=15,stop_loss_pct=1,take_profit_pct=2,risk_per_trade_pct=1,source_hash='h')

@pytest.mark.parametrize('kwargs', [{'period':1},{'period':501},{'stop_loss_pct':0},{'take_profit_pct':101},{'risk_per_trade_pct':8}])
def test_template_parameter_ranges_are_enforced(kwargs):
    params={'period':15,'stop_loss_pct':1,'take_profit_pct':2,'risk_per_trade_pct':1};params.update(kwargs)
    with pytest.raises(ValueError): pine_source(name='x',family='EMA crossover',direction='Both',source_hash='h',**params)

@pytest.mark.parametrize(('direction','should_long','should_short'), [('Long',True,False),('Short',False,True),('Both',True,True)])
def test_template_direction_gates_are_respected(direction,should_long,should_short):
    src=pine_source(name='test',family='EMA crossover',direction=direction,period=10,stop_loss_pct=1,take_profit_pct=2,risk_per_trade_pct=1,source_hash='abc123456')
    assert ('if ta.crossover(fast, slow)' in src)==should_long
    assert ('if ta.crossunder(fast, slow)' in src)==should_short
    assert ('if false' in src)==(direction!='Both')
