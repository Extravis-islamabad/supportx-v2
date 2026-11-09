"""The knowledge manager role's defaults (coverage 2026-11-09 §17 item 4; D-108 (7))."""

from app.core.modules import ModuleRegistry, discover_modules
from app.modules.identity_access import KNOWLEDGE_MANAGER, build_catalogue

WRITE_REVIEW_PUBLISH = {
    ("knowledge.view", "all"),
    ("knowledge.create", "all"),
    ("knowledge.edit_own", "own"),
    ("knowledge.edit_any", "all"),
    ("knowledge.delete", "all"),
    ("knowledge.submit", "own"),
    ("knowledge.approve", "all"),
    ("knowledge.withdraw", "all"),
    ("knowledge.manage_topics", "all"),
    ("knowledge.manage_types", "all"),
    ("knowledge.manage_settings", "all"),
}


def test_the_knowledge_manager_writes_reviews_and_publishes_for_everyone() -> None:
    catalogue = build_catalogue(ModuleRegistry.from_specs(discover_modules()))
    grants = set(catalogue.system_grants(KNOWLEDGE_MANAGER))
    assert grants >= WRITE_REVIEW_PUBLISH
    # Knowledge only: no records, settings or people of other modules come with the role.
    assert {p for p, _ in grants} - {p for p, _ in WRITE_REVIEW_PUBLISH} <= {"profile.edit"}


def test_technicians_still_neither_approve_nor_withdraw() -> None:
    catalogue = build_catalogue(ModuleRegistry.from_specs(discover_modules()))
    keys = {p for p, _ in catalogue.system_grants("technician")}
    assert "knowledge.approve" not in keys
    assert "knowledge.withdraw" not in keys
