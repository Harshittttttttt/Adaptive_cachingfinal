import random
import pytest
from src.controller.selectivity import SelectivityController


def test_threshold_bounds_monotonicity_and_reverse():
    controller=SelectivityController()
    values=[controller.threshold(i/100) for i in range(101)]
    assert values==sorted(values,reverse=True)
    assert values[0]==.92 and values[-1]==.72
    assert all(.72<=v<=.92 for v in values)
    assert controller.threshold(0,True)==.72
    assert controller.threshold(1,True)==.92
    assert controller.audit_probability(0)==.5
    assert controller.audit_probability(1)==.05


@pytest.mark.parametrize('value',[None,'0.5',float('nan'),float('inf'),-.1,1.1,True])
def test_invalid_selectivity(value):
    with pytest.raises(ValueError):SelectivityController().threshold(value)


def test_controller_only_affects_r3_and_boundary():
    c=SelectivityController()
    for policy in ['P3','P4','P5']:
        for region in ['R1','R2']:
            assert not c.force_check(region,0,0,policy,random.Random(17))
    assert not c.force_check('R3',.92,0,'P3',random.Random(17))
    assert c.force_check('R3',.919,0,'P3',random.Random(17))
    assert not c.force_check('R3',.5,0,'P2',random.Random(17))
