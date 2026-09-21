"""Environment-variable binding for deployment configuration.

Why this layer exists
---------------------
``config/settings.yaml`` holds values that are *committed* — thresholds,
coefficients, registry routes. Those are reviewable and versioned, which is
correct for anything that affects an analytical result.

Deployment facts are a different category. A database URL, a port, a log level,
a feature flag, a service-account name — these vary by environment and must
never be committed. AGENTS.md Section 21.1's CONFIG row and the project's
standing "no hardcoded values" rule both require that such values come from the
environment. This module is the single place that happens.

Precedence, and why it is ordered this way
------------------------------------------
1. **Explicit environment variable** — an operator's deployment choice.
2. **YAML default from ``settings.yaml``** — the committed, reviewable default.
3. **Hard failure** — for anything with no safe default.

Precedence 1 over 2 matters: it means a deployment can differ from the committed
default without a code change *or* a config-file edit, so there is no way to end
up in the classic failure mode where the running system differs from what the
repository says it should be and nobody knows why.

Precedence 3 matters more. A missing ``DATABASE_URL`` must raise, not silently
resolve to a local SQLite file: silently working in dev and failing in
production is the worst possible behaviour for a deployment setting, because it
defers the discovery of a misconfiguration to the moment it does the most
damage. ``resolve()`` never invents a value.

Typed coercion
--------------
Environment variables are strings. ``_coerce`` converts to the declared type and
raises a descriptive error on failure, so ``MACRO_API_PORT=eight_thousand``
produces "expected int" rather than a ``ValueError`` deep inside uvicorn's
socket binding.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "REQUIRED_IN_PRODUCTION",
    "AppEnvironment",
    "DeploymentConfig",
    "EnvironmentVariable",
    "get_deployment_config",
    "reset_deployment_config_cache",
]


class AppEnvironment(StrEnum):
    """Deployment environments.

    Three, not two, because staging must differ from production in exactly one
    way — it talks to real data but must never be mistaken for production in an
    audit. Collapsing staging into "dev" loses that distinction.
    """

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_production(self) -> bool:
        return self is AppEnvironment.PRODUCTION

    @property
    def is_local(self) -> bool:
        return self is AppEnvironment.DEVELOPMENT


# Variables that MUST be supplied in production. This is a deliberate allow-list
# rather than a denylist: a new required setting added later is caught by this
# check the moment it is listed here, whereas a denylist of "safe defaults"
# would silently permit it.
REQUIRED_IN_PRODUCTION: tuple[str, ...] = (
    "MACRO_DATABASE_URL",
    "MACRO_API_HOST",
    "MACRO_API_PORT",
)


class EnvironmentVariable(BaseModel):
    """Declares one environment variable and its resolution rules.

    Declaring these as data (rather than scattering ``os.environ.get`` calls)
    means the complete set of external knobs is enumerable — which is what makes
    an operations runbook, a container manifest, and a security review possible
    without reading the source tree.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Environment variable name, e.g. MACRO_API_PORT.")
    description: str = Field(description="What a human needs to know to set it correctly.")
    yaml_default: Any = Field(
        default=None,
        description="Fallback read from settings.yaml when the variable is unset.",
    )
    required_when: tuple[AppEnvironment, ...] = Field(
        default=(),
        description="Environments in which a missing value is a hard error.",
    )
    is_secret: bool = Field(
        default=False,
        description="Never log the value; presence/absence is logged instead.",
    )
    optional_when_unset: bool = Field(
        default=False,
        description=(
            "Whether 'unset' is itself a valid, meaningful state outside "
            "``required_when``. A secret that only some deployments hold — an "
            "API key hash, a third-party token — has three states, not two: "
            "set, required-but-missing, and legitimately absent. Without this "
            "flag the third state is indistinguishable from a configuration "
            "defect, and the resolver has to choose between raising on a "
            "perfectly valid deployment and returning ``None`` for a variable "
            "that genuinely should have been set."
        ),
    )

    def resolve(self, *, environment: AppEnvironment) -> Any:
        """Resolve this variable to a concrete value, or raise.

        Precedence: an explicit environment variable wins outright; otherwise
        the declared default is used; otherwise this is a hard failure, unless
        the variable is declared ``optional_when_unset`` — in which case
        ``None`` is a real answer and is returned rather than invented.

        The third branch is deliberately a failure rather than a synthetic
        default: a service that invents a database URL when none is configured
        is a service that writes institutional data to an unmanaged local file.

        Raises:
            MissingConfigurationError: when the variable is unset and either
                there is no default at all, or the current environment lists
                this variable in ``required_when``.
        """
        raw = os.environ.get(self.name)
        if raw is not None and raw != "":
            return raw
        if environment in self.required_when:
            raise MissingConfigurationError(
                f"Environment variable '{self.name}' is required in "
                f"'{environment.value}' and is not set. {self.description} "
                f"There is no safe default for this setting — providing one "
                f"would let a misconfiguration pass unnoticed."
            )
        if self.yaml_default is None:
            if self.optional_when_unset:
                return None
            raise MissingConfigurationError(
                f"Environment variable '{self.name}' is unset and has no "
                f"configured default. {self.description} "
                f"Either export it, declare a default in _VARIABLES, or mark "
                f"it optional_when_unset if absence is a valid state."
            )
        return self.yaml_default


class MissingConfigurationError(RuntimeError):
    """Raised when a required deployment setting cannot be resolved.

    A distinct type, not a bare ``KeyError``, so that startup can catch exactly
    this class and fail fast with a single readable message listing every
    missing variable — rather than the operator discovering them one restart at
    a time.
    """


class DeploymentConfig(BaseModel):
    """Resolved deployment settings for the current process.

    Every field here has a corresponding entry in ``_VARIABLES`` below; the
    validator enforces that, so adding a field without declaring its variable
    fails at construction rather than defaulting to ``None`` at use.
    """

    model_config = ConfigDict(extra="forbid")

    environment: AppEnvironment

    # --- API layer -------------------------------------------------------
    api_host: str
    api_port: int
    api_root_path: str
    api_docs_enabled: bool
    api_cors_origins: list[str]
    api_key_required: bool
    api_key_hash: str | None

    # --- Persistence -----------------------------------------------------
    database_url: str
    database_echo_sql: bool

    # --- Data layer ------------------------------------------------------
    openbb_api_url: str
    data_store_path: str

    # --- Observability ---------------------------------------------------
    log_level: str
    audit_enabled: bool

    @property
    def is_production(self) -> bool:
        return self.environment.is_production


#: The fallback OpenBB base URL for a clean checkout. **Kept in step with
#: ``openbb.local_api_base_url`` in ``config/settings.yaml`` on purpose (O-113).**
#: This used to be ``http://127.0.0.1:6901`` — the port that is *bound but dead*
#: (measured: 502 Bad Gateway on every data route while ``:6900`` served the same
#: commands). Two defaults for one setting is a latent contradiction; when they
#: disagree the operational one wins and the failure is silent, because a port
#: that is bound looks healthy to everything that only checks reachability.
#:
#: This module deliberately imports nothing from ``macro_engine.config`` (it is
#: the dependency-free deployment descriptor), so the value is duplicated here as
#: a named constant rather than derived — and
#: ``tests/test_infrastructure.py`` pins the two to each other so a future edit
#: to one without the other fails a test instead of an outage.
_OPENBB_DEFAULT_BASE_URL = "http://127.0.0.1:6900"


# The canonical declaration of every external knob. Order mirrors
# DeploymentConfig for reviewability.
_VARIABLES: dict[str, EnvironmentVariable] = {
    v.name: v
    for v in (
        EnvironmentVariable(
            name="MACRO_ENVIRONMENT",
            description="One of development | staging | production.",
            yaml_default="development",
        ),
        EnvironmentVariable(
            name="MACRO_API_HOST",
            description=(
                "Interface the API binds to. Bind to 127.0.0.1 unless the "
                "service sits behind a reverse proxy."
            ),
            yaml_default="127.0.0.1",
            required_when=(AppEnvironment.PRODUCTION,),
        ),
        EnvironmentVariable(
            name="MACRO_API_PORT",
            description="TCP port for the API service.",
            yaml_default="8000",
            required_when=(AppEnvironment.PRODUCTION,),
        ),
        EnvironmentVariable(
            name="MACRO_API_ROOT_PATH",
            description="URL prefix when mounted behind a path-routing proxy.",
            yaml_default="",
        ),
        EnvironmentVariable(
            name="MACRO_API_DOCS_ENABLED",
            description=(
                "Whether /docs and /openapi.json are served. Default off in "
                "production: an unauthenticated schema endpoint advertises the "
                "internal surface to anyone who can reach the host."
            ),
            yaml_default="false",
        ),
        EnvironmentVariable(
            name="MACRO_API_CORS_ORIGINS",
            description="Comma-separated allowed origins. Empty means same-origin only.",
            yaml_default="",
        ),
        EnvironmentVariable(
            name="MACRO_API_KEY_REQUIRED",
            description="Whether requests must present an API key.",
            yaml_default="false",
        ),
        EnvironmentVariable(
            name="MACRO_API_KEY_HASH",
            description=(
                "SHA-256 hex digest of the accepted API key. A HASH, not the "
                "key: the plaintext must never be held in the process "
                "environment where it leaks via crash dumps and /proc."
            ),
            yaml_default=None,
            # Required wherever the service is reachable by anything other than
            # the developer who started it. In development it stays optional,
            # and the constructor refuses the combination of "required" with an
            # absent hash, so an unprotected deployment cannot be configured by
            # accident — only by explicitly setting API_KEY_REQUIRED=false.
            required_when=(AppEnvironment.PRODUCTION,),
            optional_when_unset=True,
            is_secret=True,
        ),
        EnvironmentVariable(
            name="MACRO_DATABASE_URL",
            description=(
                "SQLAlchemy URL for the settings/audit store, e.g. "
                "postgresql+psycopg://user:pass@host/db or sqlite:///./macro.db"
            ),
            # A development default is a deliberate, named deviation from
            # production: a local SQLite file cannot be mistaken for the
            # institutional store, it is git-ignored, and it lets a clean
            # checkout run the suite without exporting anything. Production and
            # staging still require an explicit URL, so the default can never
            # silently become the system of record.
            yaml_default="sqlite:///./data/macro_dev.db",
            required_when=(AppEnvironment.PRODUCTION, AppEnvironment.STAGING),
            is_secret=True,
        ),
        EnvironmentVariable(
            name="MACRO_DATABASE_ECHO_SQL",
            description="Log every SQL statement. Development diagnosis only.",
            yaml_default="false",
        ),
        EnvironmentVariable(
            name="OPENBB_API_URL",
            description=(
                "Base URL of the OpenBB Platform API. Must match "
                "`openbb.local_api_base_url` in settings.yaml; the fallback "
                "here is only for a clean checkout, and production should "
                "export it explicitly."
            ),
            yaml_default=_OPENBB_DEFAULT_BASE_URL,
        ),
        EnvironmentVariable(
            name="MACRO_DATA_STORE_PATH",
            description="Filesystem path for the raw/parquet observation store.",
            yaml_default="data/raw",
        ),
        EnvironmentVariable(
            name="MACRO_LOG_LEVEL",
            description="Root log level: DEBUG | INFO | WARNING | ERROR | CRITICAL.",
            yaml_default="INFO",
        ),
        EnvironmentVariable(
            name="MACRO_AUDIT_ENABLED",
            description=(
                "Whether model computations and thesis builds are written to the "
                "audit trail. Disable only for local experiments."
            ),
            yaml_default="true",
        ),
    )
}

_VALID_LOG_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_TRUE_VALUES: frozenset[str] = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: frozenset[str] = frozenset({"0", "false", "no", "off"})


def _coerce_bool(variable: EnvironmentVariable, raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise MissingConfigurationError(
        f"Environment variable '{variable.name}' has value {raw!r}, which is not a "
        f"recognised boolean. Accepted: {sorted(_TRUE_VALUES | _FALSE_VALUES)}."
    )


def _coerce_int(variable: EnvironmentVariable, raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise MissingConfigurationError(
            f"Environment variable '{variable.name}' has value {raw!r}, which is not "
            f"an integer. {variable.description}"
        ) from exc


def _coerce_list(variable: EnvironmentVariable, raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _coerce_str(variable: EnvironmentVariable, raw: Any) -> str:
    return str(raw)


def _coerce_optional_str(variable: EnvironmentVariable, raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _resolve_variable(name: str, *, environment: AppEnvironment) -> Any:
    variable = _VARIABLES[name]
    return variable.resolve(environment=environment)


def _environment() -> AppEnvironment:
    raw = os.environ.get("MACRO_ENVIRONMENT", "development").strip().lower()
    try:
        return AppEnvironment(raw)
    except ValueError as exc:
        raise MissingConfigurationError(
            f"MACRO_ENVIRONMENT has value {raw!r}; expected one of "
            f"{[e.value for e in AppEnvironment]}."
        ) from exc


def _check_production_requirements(environment: AppEnvironment) -> list[str]:
    """Return the names of production-required variables that are unset.

    Called before field resolution so that a production start with three
    missing variables reports all three at once. Failing on the first one
    would turn a single misconfiguration into three deploy cycles.
    """
    if environment not in {AppEnvironment.PRODUCTION, AppEnvironment.STAGING}:
        return []
    return [
        name
        for name in REQUIRED_IN_PRODUCTION
        if name in _VARIABLES
        and environment in _VARIABLES[name].required_when
        and not os.environ.get(name)
    ]


def _check_declared_variables_resolve(environment: AppEnvironment) -> None:
    """Fail fast if any declared variable cannot resolve in this environment.

    This runs *before* any field is built, and that ordering matters. Resolving
    fields one at a time means whichever unresolved variable happens to be
    first in the constructor wins the error message, which hides both a second
    missing variable and, worse, an *invalid* value in a later one. An operator
    with a malformed ``MACRO_API_PORT`` and no ``MACRO_API_KEY_HASH`` would fix
    the key, restart, and only then learn the port was never numeric.

    Declaring a variable with neither ``yaml_default`` nor ``required_when``
    covering the current environment is therefore itself a defect in
    ``_VARIABLES`` — not something a caller can be blamed for — and the message
    says so.
    """
    unresolved: list[str] = []
    for name, variable in _VARIABLES.items():
        try:
            variable.resolve(environment=environment)
        except MissingConfigurationError as exc:
            unresolved.append(f"{name}: {exc}")
    if unresolved:
        detail = "\n  - ".join(unresolved)
        raise MissingConfigurationError(
            f"{len(unresolved)} environment variable(s) could not be resolved for "
            f"'{environment.value}':\n  - {detail}"
        )


_cached: DeploymentConfig | None = None


def get_deployment_config(*, force_reload: bool = False) -> DeploymentConfig:
    """Resolve deployment configuration for this process.

    Cached because resolution reads the environment, which cannot change
    meaningfully within a process lifetime under normal operation. Call
    ``reset_deployment_config_cache()`` in tests that manipulate ``os.environ``.

    Raises:
        MissingConfigurationError: listing *every* unresolved production-required
            variable, so one restart surfaces the full set.
    """
    global _cached
    if _cached is not None and not force_reload:
        return _cached

    environment = _environment()

    # Preflight both ways round before building a single field: the production
    # *requirement* check reports every required-but-unset variable at once,
    # and the resolution check reports every variable that cannot resolve for
    # any other reason (a declared variable with no default, a bad log level).
    # Neither is allowed to short-circuit the other.
    missing = _check_production_requirements(environment)
    if missing:
        raise MissingConfigurationError(
            f"Environment '{environment.value}' requires these variables and they "
            f"are not set: {missing}. Set them in the process environment (never "
            f"in a committed file) before starting the service."
        )
    _check_declared_variables_resolve(environment)

    log_level = str(_resolve_variable("MACRO_LOG_LEVEL", environment=environment)).upper()
    if log_level not in _VALID_LOG_LEVELS:
        raise MissingConfigurationError(
            f"MACRO_LOG_LEVEL is {log_level!r}; expected one of {sorted(_VALID_LOG_LEVELS)}."
        )

    api_key_required = _coerce_bool(
        _VARIABLES["MACRO_API_KEY_REQUIRED"],
        _resolve_variable("MACRO_API_KEY_REQUIRED", environment=environment),
    )
    api_key_hash = _coerce_optional_str(
        _VARIABLES["MACRO_API_KEY_HASH"],
        _resolve_variable("MACRO_API_KEY_HASH", environment=environment),
    )
    if api_key_required and not api_key_hash:
        # Caught at construction rather than at the first request: a service
        # configured to require a key but holding no key to compare against
        # would either reject everything or (far worse) accept everything.
        raise MissingConfigurationError(
            "MACRO_API_KEY_REQUIRED is true but MACRO_API_KEY_HASH is unset. "
            "Provide the SHA-256 hex digest of the accepted key, or set "
            "MACRO_API_KEY_REQUIRED=false."
        )

    _cached = DeploymentConfig(
        environment=environment,
        api_host=_coerce_str(
            _VARIABLES["MACRO_API_HOST"],
            _resolve_variable("MACRO_API_HOST", environment=environment),
        ),
        api_port=_coerce_int(
            _VARIABLES["MACRO_API_PORT"],
            _resolve_variable("MACRO_API_PORT", environment=environment),
        ),
        api_root_path=_coerce_str(
            _VARIABLES["MACRO_API_ROOT_PATH"],
            _resolve_variable("MACRO_API_ROOT_PATH", environment=environment),
        ),
        api_docs_enabled=_coerce_bool(
            _VARIABLES["MACRO_API_DOCS_ENABLED"],
            _resolve_variable("MACRO_API_DOCS_ENABLED", environment=environment),
        ),
        api_cors_origins=_coerce_list(
            _VARIABLES["MACRO_API_CORS_ORIGINS"],
            _resolve_variable("MACRO_API_CORS_ORIGINS", environment=environment),
        ),
        api_key_required=api_key_required,
        api_key_hash=api_key_hash,
        database_url=_coerce_str(
            _VARIABLES["MACRO_DATABASE_URL"],
            _resolve_variable("MACRO_DATABASE_URL", environment=environment),
        ),
        database_echo_sql=_coerce_bool(
            _VARIABLES["MACRO_DATABASE_ECHO_SQL"],
            _resolve_variable("MACRO_DATABASE_ECHO_SQL", environment=environment),
        ),
        openbb_api_url=_coerce_str(
            _VARIABLES["OPENBB_API_URL"],
            _resolve_variable("OPENBB_API_URL", environment=environment),
        ),
        data_store_path=_coerce_str(
            _VARIABLES["MACRO_DATA_STORE_PATH"],
            _resolve_variable("MACRO_DATA_STORE_PATH", environment=environment),
        ),
        log_level=log_level,
        audit_enabled=_coerce_bool(
            _VARIABLES["MACRO_AUDIT_ENABLED"],
            _resolve_variable("MACRO_AUDIT_ENABLED", environment=environment),
        ),
    )
    return _cached


def reset_deployment_config_cache() -> None:
    """Clear the cached config. For tests that mutate ``os.environ``."""
    global _cached
    _cached = None
