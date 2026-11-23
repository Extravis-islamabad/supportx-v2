"""The one marker for text removed at a person's request (D-171 D2a, ADR-052 §4).

When a person is erased, the free text they wrote on records they requested (subject,
description, custom text, answers) is replaced by `ERASED_ON_REQUEST`, in every module, so
screens, search and AI recognise it the same way. It is a reserved value, never shown as is:
screens render the label `ERASED_ON_REQUEST_LABEL` ("Removed at the person's request" in en/ar/ur).
Shared so modules and shared services alike reach it; identity_access re-exports it.
"""

ERASED_ON_REQUEST = "erased_on_request"
ERASED_ON_REQUEST_LABEL = "people_erasure.erased_on_request"


def is_erased_marker(value: object) -> bool:
    """Whether a stored text value is the erasure marker (search and AI skip it)."""
    return value == ERASED_ON_REQUEST
