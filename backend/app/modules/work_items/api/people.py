"""People on work item responses: one schema for the record, history and conversation (WP-020)."""

from pydantic import BaseModel


class PersonOut(BaseModel):
    """A person on a record: the name, and the email that tells two people of one name apart."""

    display_name: str
    email: str


def people_out(found: dict[str, tuple[str, str]]) -> dict[str, PersonOut]:
    """{user id: PersonOut} from {user id: (name, email)}."""
    return {k: PersonOut(display_name=n, email=e) for k, (n, e) in found.items()}
