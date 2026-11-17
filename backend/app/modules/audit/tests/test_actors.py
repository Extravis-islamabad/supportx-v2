"""The audit names the real actor (WP-057 S4b, REQ-AUD-014): pure rules, no I/O.

- a signed-in person acts as themselves;
- an API key acts for its owner: the key is the actor, the owner `on_behalf`, and the owner is
  whose personal data (IP, device) the entry holds;
- a service account's key is the account itself, the key named in the details;
- an AI agent acts for a person, with its version and tools in the details (a fake agent here).
"""

import uuid

from app.core.tenancy import AgentActor, TenantContext
from app.modules.audit.domain.catalogue import AuditActorType
from app.modules.audit.service.recording import _acting

TENANT = uuid.uuid4()
PERSON = uuid.uuid4()
KEY = uuid.uuid4()


def test_a_signed_in_person_acts_as_themselves() -> None:
    acting = _acting(TenantContext(TENANT, PERSON))
    assert (acting.type, acting.id, acting.on_behalf) == (AuditActorType.PERSON, PERSON, None)
    assert acting.subject == PERSON
    assert dict(acting.details) == {}


def test_no_person_is_the_system() -> None:
    acting = _acting(TenantContext(TENANT))
    assert (acting.type, acting.id, acting.subject) == (AuditActorType.SYSTEM, None, None)
    assert _acting(None).type is AuditActorType.SYSTEM


def test_a_persons_key_acts_on_their_behalf() -> None:
    acting = _acting(TenantContext(TENANT, PERSON, api_key_id=KEY, api_scopes=frozenset()))
    assert (acting.type, acting.id, acting.on_behalf) == (AuditActorType.API_KEY, KEY, PERSON)
    assert acting.subject == PERSON  # the IP is the owner's, never filed under the key


def test_a_service_accounts_key_is_the_account() -> None:
    acting = _acting(
        TenantContext(TENANT, PERSON, api_key_id=KEY, api_scopes=frozenset(), service_identity=True)
    )
    assert (acting.type, acting.id, acting.on_behalf) == (
        AuditActorType.SERVICE_ACCOUNT,
        PERSON,
        None,
    )
    assert dict(acting.details) == {"api_key_id": str(KEY)}


def test_an_ai_agent_acts_for_a_person_with_its_version_and_tools() -> None:
    agent_id = uuid.uuid4()
    fake = AgentActor(
        key="triage_helper", version="3", tools=("search_kb", "set_priority"), id=agent_id
    )
    acting = _acting(TenantContext(TENANT, PERSON, agent=fake))
    assert (acting.type, acting.id, acting.on_behalf) == (AuditActorType.AI_AGENT, agent_id, PERSON)
    assert acting.subject == PERSON
    assert dict(acting.details) == {
        "agent": {"key": "triage_helper", "version": "3", "tools": ["search_kb", "set_priority"]}
    }


def test_an_agent_through_a_key_is_still_the_agent() -> None:
    """The most specific actor wins: the agent, on behalf of the key's owner."""
    fake = AgentActor(key="triage_helper", version="3")
    acting = _acting(
        TenantContext(TENANT, PERSON, api_key_id=KEY, api_scopes=frozenset(), agent=fake)
    )
    assert (acting.type, acting.on_behalf) == (AuditActorType.AI_AGENT, PERSON)
