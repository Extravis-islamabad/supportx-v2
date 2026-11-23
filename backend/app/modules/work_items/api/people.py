"""People on work item responses: one schema for the record, history and conversation (WP-020)."""

from collections.abc import Mapping

from pydantic import BaseModel


class PersonOut(BaseModel):
    """A person on a record: the name, and the email that tells two people of one name apart."""

    display_name: str
    email: str


def people_out(found: Mapping[str, tuple[str, str | None]]) -> dict[str, PersonOut]:
    """{user id: PersonOut} from {user id: (name, email)}.

    A service identity (a connector, a workflow, a service account: WP-057 S4a) has no address;
    it shows by name with an empty email, never a 500 (the response type stays a string).
    """
    return {k: PersonOut(display_name=n, email=e or "") for k, (n, e) in found.items()}
