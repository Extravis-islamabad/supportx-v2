"""The TXT lookup behind verified domains (WP-057 S5d, REQ-SEC-010; dnspython, D-183).

It asks the resolver this installation is configured with (the host's or the pod's resolv.conf),
never a public resolver named here: an on-prem or air-gapped installation keeps its own DNS, and
a SaaS pod uses its cluster DNS. Bounded on every side, since the answers come from outside:

- a timeout per query and a lifetime for the whole lookup;
- at most `ANSWERS_MAX` TXT records read, each record at most `RECORD_BYTES_MAX` long (longer
  ones are skipped, never truncated into something that might match);
- a name that does not exist, or has no TXT records, is an empty answer (the record is simply not
  there); a timeout, a refusal or no answering server is `DnsUnreachable`; no resolver configured
  at all (an air-gapped host without DNS) is `DnsCheckUnavailable`, which never counts towards a
  lapse, and the admin's manual verify stays the way on a single-tenant installation.
"""

from collections.abc import Awaitable, Callable

import dns.asyncresolver
import dns.exception
import dns.rdatatype
import dns.resolver

from app.modules.identity_access.domain.verified_domains import (
    DnsCheckUnavailable,
    DnsUnreachable,
)

ANSWERS_MAX = 20  # the same cap the service applies (lane B (4)): a capped read
RECORD_BYTES_MAX = 1024  # a verification token is about 60 bytes; DNS allows far more
QUERY_TIMEOUT_SECONDS = 2.0
LIFETIME_SECONDS = 5.0


def system_resolver() -> dns.asyncresolver.Resolver:
    """The installation's own resolver (resolv.conf), with this module's bounds."""
    try:
        resolver = dns.asyncresolver.Resolver(configure=True)
    except dns.resolver.NoResolverConfiguration as missing:
        raise DnsCheckUnavailable from missing
    resolver.timeout = QUERY_TIMEOUT_SECONDS
    resolver.lifetime = LIFETIME_SECONDS
    return resolver


def _text(rdata: object) -> str | None:
    """One TXT record as text (its strings joined, as DNS splits long ones), or None if too long."""
    strings: tuple[bytes, ...] = getattr(rdata, "strings", ())
    joined = b"".join(strings)
    if len(joined) > RECORD_BYTES_MAX:
        return None
    return joined.decode("ascii", errors="replace")


def lookup_with(
    make_resolver: Callable[[], dns.asyncresolver.Resolver],
) -> Callable[[str], Awaitable[list[str]]]:
    """A TXT lookup on the resolver `make_resolver` gives (tests pass a local fake server's)."""

    async def lookup(name: str) -> list[str]:
        resolver = make_resolver()
        try:
            answer = await resolver.resolve(name, dns.rdatatype.TXT, raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            return []
        except dns.resolver.NoResolverConfiguration as missing:
            raise DnsCheckUnavailable from missing
        except dns.exception.DNSException as failed:  # timeout, no nameservers, a refusal
            raise DnsUnreachable from failed
        found: list[str] = []
        for rdata in answer:
            if len(found) >= ANSWERS_MAX:
                break
            text = _text(rdata)
            if text is not None:
                found.append(text)
        return found

    return lookup


lookup = lookup_with(system_resolver)
