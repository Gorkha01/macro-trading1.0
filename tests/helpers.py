"""Shared narrowing and assertion helpers for the test suite.

Kept as a real module rather than living in ``conftest.py`` because
``conftest`` is not importable from subdirectories — pytest loads it by path,
so ``from conftest import ...`` works only for tests in the same directory.
Putting the helpers here makes them available to every test file.
"""

from __future__ import annotations

from macro_engine.models.contracts import ModelResult

__all__ = ["as_bool", "as_dict", "as_float", "as_float_or_none", "as_int", "as_str"]


def as_float(result: ModelResult, *, key: str | None = None) -> float:
    """Narrow ``ModelResult.value`` to a float for arithmetic in a test.

    ``ModelResult.value`` is a union by design (Section 22.9): ``float | int |
    str | bool | dict | list | None``. Retyping it in the model would destroy
    that — the union is what lets one result type carry a score, a verdict and
    a structured decomposition through the same interface.

    So the narrowing belongs at the *use* site, and this helper puts it in one
    place rather than scattering ``float(x)  # type: ignore`` across the suite.
    It asserts rather than casts: if a test calls ``as_float`` on a result that
    does not carry a float, that is a test bug and should fail loudly rather
    than be silenced by a cast.

    With ``key`` given, the value must be a dict and the named entry is
    extracted — the common case for a structured decomposition.
    """
    value = result.value
    if key is not None:
        assert isinstance(value, dict), (
            f"{result.model_name}: expected a dict value to read {key!r} from, "
            f"got {type(value).__name__}"
        )
        entry = value[key]
        assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
            f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not numeric"
        )
        return float(entry)
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{result.model_name}: expected a numeric value, got {type(value).__name__}"
    )
    return float(value)


def as_float_or_none(result: ModelResult, *, key: str) -> float | None:
    """Narrow a dict entry that is *legitimately* ``float | None``.

    Several models report "absent" as ``None`` rather than ``0.0`` — the rule
    established by ``ahe_composition_flag``, where ``0.0`` would assert a
    measured zero and ``None`` states that nothing was measured. A test for
    those fields has to accept both cases, and using ``as_float`` would fail on
    the branch the model is *supposed* to take.

    The type check is still performed on the numeric branch: a field that
    returned ``"0.0"`` or ``True`` would slip through a bare ``value.get(key)``.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r} from, "
        f"got {type(value).__name__}"
    )
    entry = value[key]
    if entry is None:
        return None
    assert isinstance(entry, (int, float)) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, neither numeric nor None"
    )
    return float(entry)


def as_bool(result: ModelResult, *, key: str) -> bool:
    """Narrow a named entry of a dict-valued result to a bool.

    ``bool`` is a subclass of ``int``, so ``as_float`` would accept a boolean
    and silently report it as 0.0 or 1.0 — turning a verdict into a magnitude.
    This accessor exists so the two cannot be confused: a flag is read as a
    flag or the test fails.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r} from, "
        f"got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a bool"
    )
    return entry


def as_int(result: ModelResult, *, key: str) -> int:
    """Narrow a named entry of a dict-valued result to an int.

    Rejects ``bool`` for the same reason as ``as_bool`` rejects numbers: a
    count and a flag are different quantities.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r} from, "
        f"got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, int) and not isinstance(entry, bool), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not an int"
    )
    return entry


def as_str(result: ModelResult, *, key: str | None = None) -> str:
    """Narrow ``ModelResult.value`` to a str, or a named dict entry to one.

    Needed for the verdict-carrying results. Without it a test would either
    index the union directly (which is a type error) or cast, and a cast would
    let a result that returned the *wrong kind* of value — a float where a
    verdict was promised — pass unnoticed.
    """
    value = result.value
    if key is not None:
        assert isinstance(value, dict), (
            f"{result.model_name}: expected a dict value to read {key!r} from, "
            f"got {type(value).__name__}"
        )
        entry = value[key]
        assert isinstance(entry, str), (
            f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a str"
        )
        return entry
    assert isinstance(value, str), (
        f"{result.model_name}: expected a str value, got {type(value).__name__}"
    )
    return value


def as_dict(result: ModelResult, *, key: str) -> dict[str, float]:
    """Narrow a named entry of a dict-valued result to ``dict[str, float]``.

    Needed by the risk-budgeting tests, whose headline output is several
    **keyed by instrument** (``weights``, ``risk_contributions``,
    ``notional_vs_risk_gap``, ``stressed_weights``). Without it a test would
    index the ``ModelResult.value`` union directly — a type error under
    ``--strict`` — or cast, and a cast would hide a result that returned a bare
    *vector* where a keyed mapping was promised. A caller must not have to
    remember a vector's order, so the mapping is the contract and this asserts
    it.

    The float values are asserted individually rather than the whole mapping,
    because ``dict[Any, Any]`` would satisfy the return type while allowing a
    nested object through.
    """
    value = result.value
    assert isinstance(value, dict), (
        f"{result.model_name}: expected a dict value to read {key!r} from, "
        f"got {type(value).__name__}"
    )
    entry = value[key]
    assert isinstance(entry, dict), (
        f"{result.model_name}: value[{key!r}] is {type(entry).__name__}, not a dict"
    )
    narrowed: dict[str, float] = {}
    for name, item in entry.items():
        assert isinstance(name, str), (
            f"{result.model_name}: value[{key!r}] has a non-str key ({type(name).__name__})"
        )
        assert isinstance(item, (int, float)) and not isinstance(item, bool), (
            f"{result.model_name}: value[{key!r}][{name!r}] is {type(item).__name__}, "
            f"neither numeric nor bool-excluded"
        )
        narrowed[name] = float(item)
    return narrowed
