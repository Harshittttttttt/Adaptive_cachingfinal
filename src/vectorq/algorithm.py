"""Three regions and localized exponential posterior from arXiv v1.

Algorithm 2 normalizes a density by its integral. This follows that equation,
not the conflicting prose claim that its values are always bounded by one.
A density above the sampling upper bound simply forces a check in Algorithm 1.
The continuous density is represented on an explicit, convergence-tested grid.
"""
from dataclasses import dataclass, field
import math

ALGORITHM_VERSION = 'vectorq-arxiv-2502.03771v1-algorithms1-2-grid-v1'


def similarity_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Similarity must be finite in [0,1]')
    return value


@dataclass
class RegionState:
    correct: list[float] = field(default_factory=list)
    incorrect: list[float] = field(default_factory=list)
    log_posterior: list[float] = field(default_factory=lambda: [0.0] * 1001)
    decay: float = 10.0
    validations: int = 0

    def validate(self):
        if len(self.log_posterior) < 3 or not all(math.isfinite(x) for x in self.log_posterior):
            raise ValueError('Corrupt correctness posterior')
        if not math.isfinite(self.decay) or self.decay <= 0 or self.validations < 0:
            raise ValueError('Corrupt VectorQ settings')
        for value in self.correct + self.incorrect:
            similarity_value(value)
        if self.correct and self.incorrect and min(self.correct) <= max(self.incorrect):
            raise ValueError('Overlapping VectorQ regions')
        try:
            ys = [math.exp(y) for y in self.log_posterior]
        except OverflowError as exc:
            raise ValueError('Corrupt posterior density') from exc
        integral = (sum(ys) - .5 * (ys[0] + ys[-1])) / (len(ys) - 1)
        if not math.isclose(integral, 1, abs_tol=1e-6):
            raise ValueError('Unnormalized posterior density')

    def region(self, score):
        similarity_value(score)
        if self.incorrect and score <= max(self.incorrect):
            return 'R1'
        if self.correct and score >= min(self.correct):
            return 'R3'
        return 'R2'

    def posterior(self, score):
        similarity_value(score)
        position = score * (len(self.log_posterior) - 1)
        left = int(position)
        right = min(left + 1, len(self.log_posterior) - 1)
        fraction = position - left
        return (1 - fraction) * math.exp(self.log_posterior[left]) + fraction * math.exp(self.log_posterior[right])

    def sample_check(self, score, rng, uncertainty_gate=1.0):
        if not isinstance(uncertainty_gate, (float, int)) or not math.isfinite(uncertainty_gate) or not 0 <= uncertainty_gate <= 1:
            raise ValueError('Uncertainty gate must be in [0,1]')
        return rng.uniform(0, uncertainty_gate) < self.posterior(score)

    def reject(self, score):
        """Algorithm 1 R1: retain rejection and insert current LLM output."""
        similarity_value(score)
        self.incorrect.append(score)

    def observe(self, score, correct):
        similarity_value(score)
        if not isinstance(correct, bool):
            raise ValueError('Correctness must be boolean')
        if correct:
            if self.incorrect and score <= max(self.incorrect):
                raise ValueError('Cannot promote an R1 candidate')
            self.correct.append(score)
        else:
            self.incorrect.append(score)
            # Algorithm 1 line 24: never leave known-correct samples overlapping R1.
            self.incorrect.extend(x for x in self.correct if x <= score)
            self.correct = [x for x in self.correct if x > score]
        count = len(self.log_posterior)
        sign = -.5 if correct else .5
        updated = [y + math.log1p(sign * math.exp(-self.decay * abs(i / (count - 1) - score)))
                   for i, y in enumerate(self.log_posterior)]
        maximum = max(updated)
        weights = [math.exp(y - maximum) for y in updated]
        integral = (sum(weights) - .5 * (weights[0] + weights[-1])) / (count - 1)
        log_normalizer = maximum + math.log(integral)
        self.log_posterior = [y - log_normalizer for y in updated]
        self.validations += 1
