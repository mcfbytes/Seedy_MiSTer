"""Exact and resampling statistics, standard library only. Seeds are unpaired samples."""
import math
import random
import statistics

RNG_SEED = 20261002   # fixed so reported p-values are reproducible
PERMUTATIONS = 20000
BOOTSTRAPS = 10000


def describe(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0, "mean": None, "median": None, "min": None, "max": None, "stdev": None}
    return {"n": len(xs), "mean": statistics.fmean(xs), "median": statistics.median(xs),
            "min": min(xs), "max": max(xs), "stdev": statistics.stdev(xs) if len(xs) > 1 else 0.0}


def _log_comb(n, k):
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def fisher_exact(a, b, c, d):
    """Two-sided Fisher exact p for [[a, b], [c, d]] (sum of tables no more likely than observed)."""
    r1, c1, n = a + b, a + c, a + b + c + d
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)

    def logp(x):
        return _log_comb(r1, x) + _log_comb(n - r1, c1 - x) - _log_comb(n, c1)
    p_obs = logp(a)
    total = sum(math.exp(logp(x)) for x in range(lo, hi + 1) if logp(x) <= p_obs + 1e-9)
    return min(1.0, total)


def permutation_test(x, y, n=PERMUTATIONS, seed=RNG_SEED):
    """Two-sided permutation test on the difference of means (y - x). Returns (diff, p)."""
    x = [v for v in x if v is not None]
    y = [v for v in y if v is not None]
    if len(x) < 2 or len(y) < 2:
        return None, None
    obs = statistics.fmean(y) - statistics.fmean(x)
    pool = x + y
    nx = len(x)
    rng = random.Random(seed)
    hits = 0
    total = sum(pool)
    for _ in range(n):
        rng.shuffle(pool)
        sx = sum(pool[:nx])
        d = (total - sx) / len(y) - sx / nx
        if abs(d) >= abs(obs) - 1e-12:
            hits += 1
    return obs, (hits + 1) / (n + 1)


def bootstrap_median_diff(x, y, n=BOOTSTRAPS, seed=RNG_SEED, level=0.95):
    """Percentile bootstrap CI of median(y) - median(x), resampling each group independently."""
    x = [v for v in x if v is not None]
    y = [v for v in y if v is not None]
    if not x or not y:
        return None, None, None
    rng = random.Random(seed + 1)
    diffs = sorted(statistics.median(rng.choices(y, k=len(y))) - statistics.median(rng.choices(x, k=len(x)))
                   for _ in range(n))
    a = (1 - level) / 2
    return (statistics.median(y) - statistics.median(x),
            diffs[int(a * n)], diffs[min(n - 1, int((1 - a) * n))])
