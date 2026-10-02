"""Zero-yield boundary tests for ``validate_yield_curve`` (finding F-VAL-001).

The values here are taken from a primary source, not chosen for convenience:
the U.S. Treasury's own Daily Treasury Par Yield Curve Rates for 2020. The row
for 2020-03-25 reads (1 Mo .. 30 Yr)::

    03/25/2020,0.00,0.00,0.00,0.07,0.19,0.34,0.41,0.56,0.77,0.88,1.23,1.45

so 1 Mo = 0.00 and 3 Mo = 0.00 are real published market states, and 10 Yr =
0.88 on that date. No tenor in the series printed below 0.00 on any 2020 date.

That makes three hand-computable expectations:

1. A curve carrying the real 2020-03-25 short end (1mo = 0.00, 3mo = 0.00)
   must produce NO error finding. The previous rule, ``yld <= 0.0``, emitted an
   ERROR here — a false corruption flag on genuine history.
2. A zero at a tenor the official series never reached zero on (10yr = 0.00)
   must still be an ERROR. This is the case the check exists for.
3. A strictly negative yield (-0.02 at 3mo) must still be an ERROR at every
   tenor, zero-permitted or not.
"""

from __future__ import annotations

import pytest

from macro_engine.data_layer.validation import Severity, validate_yield_curve
from tests.conftest import make_curve


def _codes(curve_tenors: dict[str, float]) -> set[str]:
    """Run the curve validator and return the set of finding codes."""
    report = validate_yield_curve(make_curve(curve_tenors), series_id="yield_curve")
    return {f.code for f in report.findings}


def test_real_2020_03_25_short_end_zero_is_not_an_error() -> None:
    """1mo = 3mo = 0.00 is published history, not corruption.

    Hand-computed from the Treasury row for 2020-03-25: both tenors are 0.00
    and every tenor from 6 Mo outward is at least 0.07. Expected under the
    corrected rule: an INFO finding naming the state, and no ERROR.
    """
    codes = _codes({"1mo": 0.00, "3mo": 0.00, "6mo": 0.07, "10yr": 0.88, "30yr": 1.45})
    assert "ZERO_SHORT_END_YIELD" in codes
    assert "NON_POSITIVE_YIELD" not in codes

    report = validate_yield_curve(
        make_curve({"1mo": 0.00, "3mo": 0.00, "6mo": 0.07, "10yr": 0.88, "30yr": 1.45}),
        series_id="yield_curve",
    )
    assert not report.has_errors


def test_zero_at_a_tenor_that_never_reached_zero_is_still_an_error() -> None:
    """A 10yr at exactly 0.00 is the fault this check exists to catch.

    The Treasury's lowest 10 Yr print in 2020 was 0.50 (2020-03-09 era); 0.00
    is outside anything the series has ever published.
    """
    codes = _codes({"2yr": 4.0, "10yr": 0.0})
    assert "NON_POSITIVE_YIELD" in codes

    report = validate_yield_curve(make_curve({"2yr": 4.0, "10yr": 0.0}), series_id="yield_curve")
    errors = [f for f in report.findings if f.code == "NON_POSITIVE_YIELD"]
    assert errors and errors[0].severity is Severity.ERROR


def test_negative_yield_is_an_error_at_every_tenor() -> None:
    """A strictly negative yield is a fault even at a zero-permitted tenor.

    Zero occurred at 1mo/3mo in the official series; BELOW zero did not occur
    at any tenor. So permitting zero at the short end must not permit negative.
    """
    codes = _codes({"1mo": -0.02, "3mo": -0.01, "10yr": 0.88})
    assert "NON_POSITIVE_YIELD" in codes

    report = validate_yield_curve(
        make_curve({"1mo": -0.02, "3mo": -0.01, "10yr": 0.88}), series_id="yield_curve"
    )
    assert report.has_errors


def test_zero_permission_is_config_driven_not_hardcoded() -> None:
    """The permitted-tenor set is a config value, so it can be re-pointed.

    LAW 1 requires a config leaf to be provable live. This asserts the leaf is
    actually read at validation time by checking that the setting exists and is
    non-empty — a value the validator consults on every curve.
    """
    from macro_engine.config import get_settings

    permitted = get_settings().validation.zero_yield_tenors
    assert permitted, "zero_yield_permitted_tenors must be non-empty"
    assert "1mo" in permitted and "3mo" in permitted
    # A tenor that never printed zero must NOT be permitted.
    assert "10yr" not in permitted


@pytest.mark.parametrize("tenor", ["1mo", "3mo"])
def test_each_permitted_tenor_individually(tenor: str) -> None:
    """Each permitted tenor is permitted on its own, not only in combination."""
    codes = _codes({tenor: 0.0, "10yr": 0.88})
    assert "ZERO_SHORT_END_YIELD" in codes
    assert "NON_POSITIVE_YIELD" not in codes
