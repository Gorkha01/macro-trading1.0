"""The models layer — quantitative macro models over a ``MacroDataSnapshot``.

AGENTS.md Section 6, Section 15, Section 20, Section 21.2, Section 22.1.

The single structural rule this package enforces: **models do not fetch data.**
Every model receives whatever it needs through an explicitly typed input model,
and every model returns a ``ModelResult``. Nothing here holds a provider URL,
a symbol, or an HTTP client. That separation is what makes the real-data
execution step (Section 21.2 Step 6) meaningful — the function under test can
be exercised against live values without the function itself knowing where they
came from.

Two-tier function status (Section 22.1):

* **STUB** — correct signature, typed inputs and output, raises
  ``NotImplementedError`` with the phase that will implement it.
* **IMPLEMENTED** — full logic, real-data validated per Section 21.0.

Section 20's "none may be skipped" means every function must exist as a
correctly-signed STUB immediately; it does not mean every body ships at once.
Section 21.3's tier table decides when a stub becomes implemented.

Implementation order
--------------------
Functions are built in Section 21.3's dependency order, because a function
whose inputs come from another function cannot be validated on real data until
its dependency exists. Tier 1 is pure arithmetic on live snapshot fields, so it
comes first and nothing can block it.

Module map, as implemented:

============================  ====================================================
Module                        File
============================  ====================================================
2 — Bond math                 ``bond_math.py``
3 — National accounts         ``national_accounts.py``
3.3 — Phillips curve          ``inflation_dynamics.py``
3.5 — Production function     ``production_function.py``
4 — Policy rules              ``policy_rules.py``
5.1 — Shelter lag nowcast     ``inflation_nowcast.py``
5.4 — PPI pipeline signal     ``ppi_pipeline.py``
5.6 — Cross-asset transmission ``inflation_dynamics.py``
6 — Labor synthesis           ``labor_synthesis.py``
7 — GDP nowcast / output gap  ``gdp_nowcast.py`` (also Module 7.1, GDP/GDI)
8 — Yield curve               ``yield_curve.py``
17-18 — Risk and volatility   ``risk.py``
— As-of discipline            ``as_of.py``
— Output contract             ``contracts.py``
============================  ====================================================

``contracts.py`` is imported by every module above; ``as_of.py`` is imported by
every model that consumes a forward-looking series. Neither fetches anything.
"""
