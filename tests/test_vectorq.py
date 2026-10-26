import math
import random

import pytest

from src.vectorq.algorithm import RegionState


def test_initial_regions_and_prior():
    state=RegionState()
    state.validate()
    assert all(state.region(s)=='R2' for s in [0,.5,1])
    assert all(state.posterior(s)==1 for s in [0,.5,1])
    assert state.sample_check(.8,random.Random(17))


def test_region_membership_boundary_and_updates():
    state=RegionState()
    state.observe(.8,True)
    state.observe(.3,False)
    assert [state.region(x) for x in [.3,.31,.79,.8,1]]==['R1','R2','R2','R3','R3']
    state.observe(.9,False)
    assert state.correct==[] and .8 in state.incorrect
    assert state.region(.9)=='R1' and state.region(.91)=='R2'
    state.observe(.95,True)
    assert state.region(.96)=='R3'
    state.reject(.5)
    state.validate()
    with pytest.raises(ValueError,match='R1'):
        state.observe(.1,True)


@pytest.mark.parametrize('correct',[True,False])
def test_posterior_matches_one_observation_analytic_integral(correct):
    state=RegionState()
    point=.8
    state.observe(point,correct)
    kernel_integral=(2-math.exp(-10*point)-math.exp(-10*(1-point)))/10
    sign=-.5 if correct else .5
    expected=(1+sign)/(1+sign*kernel_integral)
    assert state.posterior(point)==pytest.approx(expected,abs=2e-6)
    assert (state.posterior(point)<1) == correct
    state.validate()


def test_grid_convergence_and_stable_repeated_updates():
    coarse=RegionState(log_posterior=[0.0]*1001)
    fine=RegionState(log_posterior=[0.0]*10001)
    for score,correct in [(.73,True),(.81,True),(.5,False),(.87,True)]:
        coarse.observe(score,correct)
        fine.observe(score,correct)
    assert coarse.posterior(.83)==pytest.approx(fine.posterior(.83),abs=3e-5)
    for _ in range(300):
        coarse.observe(.9,True)
    coarse.validate()


def test_sampling_rule_and_uncertainty_gate():
    class RNG:
        def __init__(self,value):self.value=value
        def uniform(self,a,b):return self.value*b
    state=RegionState()
    state.observe(.8,True)
    assert state.sample_check(.8,RNG(0)) is True
    assert state.sample_check(.8,RNG(.99)) is False
    assert state.sample_check(.8,RNG(.99),.2) is True
    assert state.sample_check(.8,RNG(.99),0) is True


@pytest.mark.parametrize('state',[RegionState(log_posterior=[float('nan')]*3),
                                RegionState(correct=[.7],incorrect=[.8]),
                                RegionState(log_posterior=[1,1,1])])
def test_corrupt_metadata_rejected(state):
    with pytest.raises(ValueError):state.validate()
