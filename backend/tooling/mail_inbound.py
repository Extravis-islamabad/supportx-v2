"""`make mail-inbound-test`: feed one e-mail into a dev tenant's inbound pipeline (QA6-NTF-01).

The dev stack has no mail server to fetch from: Mailpit only catches outgoing mail. So "an e-mail
creates an incident" (WP-024) could not be QA'd. This builds a real RFC 822 message (or reads an
.eml file) and hands it to the same `inbound.process` the mailbox fetcher calls. It runs the same
ledger claim, routing, new incident or reply, polite refusals and held queue, and commits like a
fetch. Refuses to run in production.

    make mail-inbound-test ARGS="--create"                          # a dev mailbox, then one mail
    make mail-inbound-test ARGS="--from rana@demo.test --subject 'Printer jam'"
    make mail-inbound-test ARGS="--in-reply-to '<id-of-a-reply@...>' --body 'Still broken'"
    make mail-inbound-test ARGS="--eml path/to/message.eml"

`--create` adds a mailbox `dev-inbound@<tenant>.test` with an unreachable IMAP host
(inbound.dev.invalid): its scheduled fetch reports it cannot connect, and that is expected here.
"""

import argparse
import asyncio
import secrets
import sys
import uuid
from collections.abc import Sequence
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import Database, create_engine
from app.core.modules import discover_modules
from app.core.tenancy import TenantContext
from app.modules.integrations.infra.models import Mailbox
from app.modules.integrations.service import inbound, mailboxes
from app.modules.integrations.service.fetching import own_addresses
from tooling.dev_subscription import tenant_id

DEV_HOST = "inbound.dev.invalid"  # RFC 6761: never resolves


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """The tenant, the mailbox and the message."""
    parser = argparse.ArgumentParser(prog="mail-inbound-test", description=__doc__.split("\n")[0])
    parser.add_argument("--tenant", type=tenant_id, default=tenant_id("demo"))
    parser.add_argument("--mailbox", help="the mailbox address (default: the tenant's first)")
    parser.add_argument("--create", action="store_true", help="add a dev mailbox if none exists")
    parser.add_argument("--from", dest="sender", default="rana@demo.test")
    parser.add_argument("--subject", default="Printer on floor 2 is jammed")
    parser.add_argument("--body", default="Hello, the printer shows a paper jam. Thanks.")
    parser.add_argument("--in-reply-to", help="a Message-ID to answer (a reply on its record)")
    parser.add_argument("--eml", type=Path, help="send this .eml file as it is instead")
    return parser.parse_args(argv)


def build(args: argparse.Namespace, to: str) -> bytes:
    """The raw message: the .eml file, or one built from the options."""
    if args.eml is not None:
        return Path(args.eml).read_bytes()
    message = EmailMessage()
    message["From"] = args.sender
    message["To"] = to
    message["Subject"] = args.subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain="dev-inbound.test")
    if args.in_reply_to:
        message["In-Reply-To"] = args.in_reply_to
        message["References"] = args.in_reply_to
    message.set_content(args.body)
    return message.as_bytes()


async def _mailbox(
    session: AsyncSession, settings: Settings, tenant: uuid.UUID, args: argparse.Namespace
) -> Mailbox:
    query = select(Mailbox).where(Mailbox.deleted_at.is_(None)).order_by(Mailbox.created_at)
    if args.mailbox:
        query = query.where(func.lower(Mailbox.address) == args.mailbox.lower())
    found = await session.scalar(query.limit(1))
    if found is not None:
        return found
    if not args.create:
        msg = "no mailbox: add one in Admin > Mail, or pass --create"
        raise SystemExit(msg)
    address = args.mailbox or f"dev-inbound@{str(tenant)[:8]}.test"
    view = await mailboxes.create_mailbox(
        session,
        settings,
        tenant,
        {
            "address": address,
            "display_name": "Dev inbound (QA)",
            "protocol": "imap",
            "host": DEV_HOST,
            "port": 993,
            "username": "dev-inbound",
        },
        password=secrets.token_urlsafe(24),  # never used: the host never resolves
    )
    return view.row


async def run(database_url: str, settings: Settings, args: argparse.Namespace) -> str:
    """Process one message in the tenant's transaction; returns a report."""
    discover_modules()
    database = Database(create_engine(database_url, application_name="mail-inbound-test"))
    try:
        async with database.tenant_session(TenantContext(args.tenant)) as session:
            mailbox = await _mailbox(session, settings, args.tenant, args)
            raw = build(args, mailbox.address)
            outcome = await inbound.process(
                session,
                settings,
                mailbox,
                raw,
                own_addresses=own_addresses(settings, [mailbox]),
            )
            if outcome is None:
                return f"{mailbox.address}: seen before (same Message-ID), skipped"
            return f"{mailbox.address}: {outcome}"
    finally:
        await database.dispose()


def main() -> int:  # pragma: no cover - thin CLI over the tested functions
    """CLI entry point."""
    settings = Settings()
    if settings.profile == "production":
        sys.stderr.write("mail-inbound-test never runs in the production profile\n")
        return 2
    if settings.migration_database_url is None:
        sys.stderr.write("SUPPORTX_MIGRATION_DATABASE_URL is not set (make backend-env)\n")
        return 2
    args = parse_args(sys.argv[1:])
    url = settings.migration_database_url.get_secret_value()
    sys.stdout.write(asyncio.run(run(url, settings, args)) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
