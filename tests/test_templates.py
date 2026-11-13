import hashlib
import pytest
from app.main import FAMILIES
from app.templates import pine_source, SIGNALS

@pytest.mark.parametrize('family', FAMILIES)
def test_every_factory_family_has_distinct_explicit_signal_template(family):
    assert family in SIGNALS, f'{family} must not silently fall back to another strategy'
    digest=hashlib.sha256(family.encode()).hexdigest()
    source=pine_source(name='test',family=family,direction='Both',period=15,stop_loss_pct=1.5,take_profit_pct=3,risk_per_trade_pct=1,source_hash=digest)
    assert source.startswith('//@version=6')
    assert 'strategy.entry("L"' in source and 'strategy.entry("S"' in source
    assert 'strategy.exit("XL"' in source and 'strategy.exit("XS"' in source
    assert 'strategy.entry("S", strategy.short)\n\nlongStop' not in source

@pytest.mark.parametrize(('direction','should_long','should_short'), [('Long',True,False),('Short',False,True),('Both',True,True)])
def test_template_direction_gates_are_respected(direction,should_long,should_short):
    src=pine_source(name='test',family='EMA crossover',direction=direction,period=10,stop_loss_pct=1,take_profit_pct=2,risk_per_trade_pct=1,source_hash='abc123456')
    assert ('if ta.crossover(fast, slow)' in src)==should_long
    assert ('if ta.crossunder(fast, slow)' in src)==should_short
    assert ('if false' in src)==(direction!='Both')
