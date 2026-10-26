"""Feature catalogue: every licensable feature, edition and counted limit, in one place (WP-009).

architecture.md §13.1 defines the shape (edition, features, counted limits, term);
product-plan.md §9 the three tiers. This file is the only place that says which edition includes
which feature and what a plan gets when it does not set a limit itself. Display text never lives
here: the UI renders `feature.<key>`, `edition.<key>` and `limit.<key>` through
frontend/packages/labels (en + ar, CI-checked by tests/test_licensing_labels.py).

The default limits and rate-limit multipliers are engineering placeholders: real numbers need
commercial input (product-plan.md §9 leaves prices and bands open). A subscription or licence
that names a limit always overrides the default.
"""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType


class Edition(StrEnum):
    """Commercial tier (product-plan.md §9)."""

    ESSENTIALS = "essentials"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class Feature(StrEnum):
    """A licensable capability. A module declares one in its ModuleSpec (`feature=`)."""

    INCIDENT = "incident"
    SERVICE_REQUEST = "service_request"
    KNOWLEDGE = "knowledge"
    SLA = "sla"
    AI_ASSIST = "ai_assist"
    PROBLEM = "problem"
    CHANGE = "change"
    RELEASE = "release"
    CATALOG = "catalog"
    CMDB = "cmdb"
    ASSETS = "assets"
    DISCOVERY = "discovery"
    PROCUREMENT = "procurement"
    WORKFLOWS = "workflows"
    AI_AGENTS = "ai_agents"
    MONETX_INTEGRATION = "monetx_integration"
    PROJECTS = "projects"
    ESM = "esm"
    MSP = "msp"
    ADVANCED_REPORTING = "advanced_reporting"
    SANDBOX = "sandbox"
    CONFIG_AS_CODE = "config_as_code"
    CUSTOM_FUNCTIONS = "custom_functions"
    LOCAL_AI_RUNTIME = "local_ai_runtime"
    COMPLIANCE_PACKS = "compliance_packs"


class LimitKey(StrEnum):
    """A counted limit (architecture.md §13.1). End users (requesters) are never counted."""

    TECHNICIANS = "technicians"
    ASSETS = "assets"
    DEPARTMENTS = "departments"
    MSP_CUSTOMERS = "msp_customers"
    AI_AGENT_RUNS_PER_MONTH = "ai_agent_runs_per_month"
    # Stored files in GB (WP-022, D-082 D6): counted in whole GB for display; uploads compare bytes.
    STORAGE_GB = "storage_gb"


_ESSENTIALS = frozenset(
    {Feature.INCIDENT, Feature.SERVICE_REQUEST, Feature.KNOWLEDGE, Feature.SLA, Feature.AI_ASSIST}
)
# "All ITIL practices available from Professional" (product-plan.md §9.1); the agent library is
# in every paid tier from Professional (§9, pillar 4).
_PROFESSIONAL = _ESSENTIALS | {
    Feature.PROBLEM,
    Feature.CHANGE,
    Feature.RELEASE,
    Feature.CATALOG,
    Feature.CMDB,
    Feature.ASSETS,
    Feature.DISCOVERY,
    Feature.PROCUREMENT,
    Feature.WORKFLOWS,
    Feature.AI_AGENTS,
    Feature.MONETX_INTEGRATION,
}
_ENTERPRISE = _PROFESSIONAL | {
    Feature.PROJECTS,
    Feature.ESM,
    Feature.MSP,
    Feature.ADVANCED_REPORTING,
    Feature.SANDBOX,
    Feature.CONFIG_AS_CODE,
    Feature.CUSTOM_FUNCTIONS,
    Feature.LOCAL_AI_RUNTIME,
    Feature.COMPLIANCE_PACKS,
}

EDITION_FEATURES: Mapping[Edition, frozenset[Feature]] = MappingProxyType(
    {
        Edition.ESSENTIALS: _ESSENTIALS,
        Edition.PROFESSIONAL: frozenset(_PROFESSIONAL),
        Edition.ENTERPRISE: frozenset(_ENTERPRISE),
    }
)

# None = unlimited. Placeholders until commercial input (see module docstring).
EDITION_DEFAULT_LIMITS: Mapping[Edition, Mapping[LimitKey, int | None]] = MappingProxyType(
    {
        Edition.ESSENTIALS: MappingProxyType(
            {
                LimitKey.TECHNICIANS: 10,
                LimitKey.ASSETS: 1_000,
                LimitKey.DEPARTMENTS: 1,
                LimitKey.MSP_CUSTOMERS: 0,
                LimitKey.AI_AGENT_RUNS_PER_MONTH: 500,
                LimitKey.STORAGE_GB: 50,
            }
        ),
        Edition.PROFESSIONAL: MappingProxyType(
            {
                LimitKey.TECHNICIANS: 50,
                LimitKey.ASSETS: 10_000,
                LimitKey.DEPARTMENTS: 1,
                LimitKey.MSP_CUSTOMERS: 0,
                LimitKey.AI_AGENT_RUNS_PER_MONTH: 5_000,
                LimitKey.STORAGE_GB: 250,
            }
        ),
        # "Unlimited department desks (ESM)" is an Enterprise selling point (product-plan.md §9).
        Edition.ENTERPRISE: MappingProxyType(
            {
                LimitKey.TECHNICIANS: 250,
                LimitKey.ASSETS: 50_000,
                LimitKey.DEPARTMENTS: None,
                LimitKey.MSP_CUSTOMERS: 25,
                LimitKey.AI_AGENT_RUNS_PER_MONTH: 50_000,
                LimitKey.STORAGE_GB: 1_000,
            }
        ),
    }
)

# API rate-limit budgets (SUPPORTX_RATE_LIMITS) are multiplied by this per edition (WP-008 hook).
EDITION_RATE_LIMIT_MULTIPLIER: Mapping[Edition, int] = MappingProxyType(
    {Edition.ESSENTIALS: 1, Edition.PROFESSIONAL: 2, Edition.ENTERPRISE: 4}
)


def unknown_features(keys: set[str] | frozenset[str]) -> set[str]:
    """The keys in `keys` that are not in the catalogue (module declarations, licence files)."""
    known = {feature.value for feature in Feature}
    return {key for key in keys if key not in known}
