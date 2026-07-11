from passmodel.model import distribution


def test_p_over_monotonic_in_mu():
    lo = distribution.p_over(mu=55, alpha=0.01, line=64.5)
    hi = distribution.p_over(mu=75, alpha=0.01, line=64.5)
    assert 0 < lo < hi < 1


def test_higher_alpha_widens_distribution():
    tight = distribution.p_over(mu=60, alpha=0.001, line=80.5)
    wide = distribution.p_over(mu=60, alpha=0.05, line=80.5)
    assert wide > tight


def test_fit_alpha_positive_floor():
    assert distribution.fit_alpha([50, 60], [50, 60]) >= 1e-6


def test_fit_alpha_recovers_overdispersion():
    mus = [60.0] * 200
    acts = [40, 80] * 100
    alpha = distribution.fit_alpha(mus, acts)
    assert alpha > 0.05
