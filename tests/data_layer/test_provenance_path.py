"""Provenance must name the path that SERVED the data, not the preferred one.

The defect this pins
--------------------
``_normalize`` derived the ``source`` column from ``use_local_api_first`` — a
*preference* — rather than from the transport that actually answered. Those two
agree on the happy path and **disagree whenever the cross-path fallback fires**:

    use_local_api_first = True
      -> local API fails on every retry
      -> fallback to the package SUCCEEDS
      -> values returned, labelled ``openbb:http://127.0.0.1:6901``

Every value fetched during that degradation carries a provenance fact that is
wrong — not missing. The directive's POINT-IN-TIME / provenance rule requires
the retrieval path be traceable, and a wrong label is worse than an absent one
because a reader has no reason to doubt it.

Measured before the fix: the label followed the flag, so a package-served value
was attributed to the HTTP path.
"""

from __future__ import annotations

import pandas as pd

from macro_engine.data_layer.openbb_client import (
    _PATH_LOCAL_API,
    _PATH_PACKAGE,
    OpenBBClient,
    OpenBBClientConfig,
)


def _client() -> OpenBBClient:
    return OpenBBClient(OpenBBClientConfig(use_local_api_first=True))


def _raw_frame() -> pd.DataFrame:
    """A minimal frame in the shape ``_normalize`` accepts."""
    return pd.DataFrame(
        {"value": [334.131, 335.0]},
        index=pd.to_datetime(["2026-07-01", "2026-08-01"]).rename("date"),
    )


def _source_of(client: OpenBBClient, served_by: str) -> str:
    frame = client._normalize(_raw_frame(), "cpi_headline", served_by=served_by)
    return str(frame["source"].iloc[0])


def test_package_served_data_is_labelled_package_even_when_local_is_preferred() -> None:
    """THE regression: the fallback case must report the package path.

    With ``use_local_api_first=True`` but the package having answered, the
    source must say ``openbb:package``.
    """
    client = _client()
    assert client.config.use_local_api_first is True, "precondition: local API is preferred"

    source = _source_of(client, _PATH_PACKAGE)
    assert source == "openbb:package", (
        f"a package-served value was labelled {source!r}. The label must follow "
        "the serving path, not the configured preference — otherwise every "
        "value fetched during a cross-path fallback carries a wrong provenance "
        "fact."
    )


def test_local_api_served_data_is_labelled_with_the_url() -> None:
    """The complement: a local-API-served value names the URL it came from."""
    client = _client()
    source = _source_of(client, _PATH_LOCAL_API)
    assert source.startswith("openbb:http://"), f"unexpected local-API label: {source!r}"


def test_the_two_paths_produce_distinguishable_labels() -> None:
    """A reader must be able to tell the two transports apart.

    If the labels collapsed to one value, provenance would be untraceable and
    this whole distinction would be decorative.
    """
    client = _client()
    api_label = _source_of(client, _PATH_LOCAL_API)
    pkg_label = _source_of(client, _PATH_PACKAGE)
    assert api_label != pkg_label, (
        "the local-API and package labels are identical, so a reader cannot "
        "tell which transport served a value"
    )


def test_provenance_is_independent_of_the_preference_flag() -> None:
    """The label must be a fact about the request, not about configuration.

    Flipping the preference must not change how an *already-served* response is
    labelled: the same ``served_by`` yields the same label either way.
    """
    local_pref = OpenBBClient(OpenBBClientConfig(use_local_api_first=True))
    package_pref = OpenBBClient(OpenBBClientConfig(use_local_api_first=False))

    for served_by in (_PATH_LOCAL_API, _PATH_PACKAGE):
        assert _source_of(local_pref, served_by) == _source_of(package_pref, served_by), (
            f"served_by={served_by!r} is labelled differently depending on the "
            "preference flag, so the label is not a fact about the request"
        )


def test_normalize_signature_requires_the_serving_path() -> None:
    """``served_by`` must be keyword-only and mandatory.

    A default would let a future call site silently fall back to a guess, which
    is the exact failure this change removes.
    """
    import inspect

    sig = inspect.signature(OpenBBClient._normalize)
    param = sig.parameters["served_by"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is inspect.Parameter.empty, (
        "`served_by` has a default, so a new caller can omit it and reintroduce "
        "an inferred (i.e. potentially wrong) provenance label"
    )


def test_any_typed_kwargs_are_rejected_as_before() -> None:
    """Sanity: the normaliser still rejects a frame with no usable columns.

    Guards against the signature change accidentally loosening input checks.
    """
    import pytest

    from macro_engine.data_layer.openbb_client import OpenBBFetchError

    client = _client()
    with pytest.raises(OpenBBFetchError):
        client._normalize(
            pd.DataFrame({"unrelated": [1, 2]}), "cpi_headline", served_by=_PATH_PACKAGE
        )
