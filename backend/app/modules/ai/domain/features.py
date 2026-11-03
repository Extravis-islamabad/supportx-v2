"""AI features and their areas (REQ-AI-027). Pure.

A feature is one thing AI does for a person. Each has a stable code (labels `ai_feature.<code>`),
an area for grouping on the settings screen (`ai_area.<area>`), and the permission a person must
hold to use it, checked by the gateway before anything else (REQ-AI-025).
"""

from dataclasses import dataclass
from enum import StrEnum


class AiArea(StrEnum):
    """Groups on the AI settings screen."""

    WRITING = "writing"
    SUMMARIES = "summaries"
    PREDICTIONS = "predictions"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True)
class FeatureSpec:
    """One AI feature."""

    code: str
    area: AiArea
    permission: str


# WP-038 builds the incident features on these codes (REQ-INC-022, 136, 137).
FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("reply_draft", AiArea.WRITING, "incidents.reply"),
    FeatureSpec("text_improve", AiArea.WRITING, "incidents.reply"),
    FeatureSpec("conversation_summary", AiArea.SUMMARIES, "incidents.view"),
    FeatureSpec("possible_duplicates", AiArea.PREDICTIONS, "incidents.create"),
)
BY_CODE = {feature.code: feature for feature in FEATURES}


def feature(code: str) -> FeatureSpec | None:
    """The feature with this code, or None."""
    return BY_CODE.get(code)
