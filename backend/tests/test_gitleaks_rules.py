"""The secret scanner knows SupportX API keys (D-128): the rule matches what the code makes.

CI also runs gitleaks itself on a sample key with this config (security.yml, "the SupportX key
rule catches a key"); this test keeps the config, the code and the published pattern identical.
"""

import re
import tomllib
import uuid
from pathlib import Path

from app.modules.identity_access.domain import api_keys

ROOT = Path(__file__).resolve().parents[2]


def test_the_gitleaks_rule_is_the_published_pattern_and_catches_a_real_key() -> None:
    config = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    assert config["extend"]["useDefault"] is True  # the default rules stay on
    rule = next(r for r in config["rules"] if r["id"] == "supportx-api-key")
    assert rule["regex"] == api_keys.SCANNER_REGEX
    key = api_keys.make_key(uuid.uuid4(), uuid.uuid4()).text
    assert re.search(rule["regex"], f"SUPPORTX_TOKEN={key}\n") is not None
    assert any(k in key for k in rule["keywords"])


def test_the_published_documentation_shows_the_same_pattern() -> None:
    docs = (ROOT / "docs" / "api" / "keys.md").read_text(encoding="utf-8")
    assert api_keys.SCANNER_REGEX in docs
