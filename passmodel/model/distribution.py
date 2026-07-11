import math
import numpy as np
from scipy.stats import nbinom, poisson


def p_over(mu, alpha, line):
    """P(passes > line) under NB(mean=mu, var=mu+alpha*mu^2)."""
    if mu <= 0:
        return 0.0
    k = math.floor(line)
    if alpha < 1e-9:
        return float(1 - poisson.cdf(k, mu))
    n = 1.0 / alpha
    p = n / (n + mu)
    return float(1 - nbinom.cdf(k, n, p))


def fit_alpha(mus, actuals):
    """Method of moments on pooled residuals: var = mu + alpha*mu^2."""
    mus = np.asarray(mus, dtype=float)
    acts = np.asarray(actuals, dtype=float)
    if len(mus) == 0:
        return 0.02
    resid_var = float(np.mean((acts - mus) ** 2))
    mean_mu = float(np.mean(mus))
    if mean_mu <= 0:
        return 1e-6
    return max((resid_var - mean_mu) / (mean_mu**2), 1e-6)
