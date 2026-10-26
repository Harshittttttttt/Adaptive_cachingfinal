from dataclasses import dataclass
import math


def valid_selectivity(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Selectivity must be supplied as a finite value in [0,1]')
    return value


@dataclass(frozen=True)
class SelectivityController:
    tau_min: float = .72
    tau_max: float = .92
    gamma: float = 1.0
    audit_min: float = .05
    audit_max: float = .5

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.tau_min,self.tau_max,self.gamma,self.audit_min,self.audit_max)):
            raise ValueError('Nonfinite controller setting')
        if not 0 <= self.tau_min <= self.tau_max <= 1 or self.gamma <= 0:
            raise ValueError('Invalid threshold settings')
        if not 0 <= self.audit_min <= self.audit_max <= 1:
            raise ValueError('Invalid audit settings')

    def threshold(self, selectivity, reverse=False):
        s = valid_selectivity(selectivity)
        return self.tau_min + (self.tau_max - self.tau_min) * (s if reverse else 1-s) ** self.gamma

    def audit_probability(self, selectivity):
        s = valid_selectivity(selectivity)
        return self.audit_min + (self.audit_max - self.audit_min) * (1-s) ** self.gamma

    def force_check(self, region, similarity, selectivity, policy, rng):
        if region != 'R3':
            return False
        if policy in {'P3','P4'}:
            return similarity < self.threshold(selectivity, reverse=policy == 'P4')
        if policy == 'P5':
            return rng.random() < self.audit_probability(selectivity)
        return False
