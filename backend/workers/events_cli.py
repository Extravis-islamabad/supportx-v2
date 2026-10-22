"""Operator commands for the event bus (WP-007; docs/architecture/events.md, "Debugging").

    python -m workers.events_cli tail [--tenant T] [--type PATTERN] [--since 10m|all]
    python -m workers.events_cli dlq-list [--consumer C]
    python -m workers.events_cli dlq-replay (--seq N | --all) [--consumer C]
    python -m workers.events_cli stats

`tail` uses an ephemeral ordered consumer: it leaves nothing behind on the server and never
affects any real consumer. `dlq-replay` republishes a dead letter to `replay.<consumer>...`, which
only that consumer receives, then removes it from the DLQ; the consumer's idempotency record
still prevents a double effect.
"""

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TextIO

import nats.errors
from nats.aio.msg import Msg
from nats.js import JetStreamContext, api
from nats.js.errors import NoKeysError, NotFoundError
from nats.js.kv import KeyValue

from app.core.config import Settings
from app.shared.events import BusNames, EventEnvelope
from workers import bus

_SINCE = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def parse_since(value: str | None) -> datetime | str | None:
    """`10m` → a start time; `all` → "all"; None → None (new events only)."""
    if value is None:
        return None
    if value == "all":
        return "all"
    match = _SINCE.fullmatch(value)
    if not match:
        msg = f"--since must look like 30s, 10m, 2h, 1d or 'all', not {value!r}"
        raise argparse.ArgumentTypeError(msg)
    return datetime.now(UTC) - timedelta(**{_UNITS[match.group(2)]: int(match.group(1))})


def format_event(data: bytes) -> str:
    """One readable line per event (the payload holds IDs and codes only)."""
    try:
        event = EventEnvelope.from_json(data)
    except ValueError:
        return f"(not an event envelope: {data[:120]!r})"
    at = event.occurred_at.astimezone(UTC).strftime("%H:%M:%S.%f")[:-3]
    payload = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
    version = f" v{event.aggregate_version}" if event.aggregate_version is not None else ""
    return (
        f"{at}  {event.event_type:<42} tenant={str(event.tenant_id)[:8]}…  "
        f"{event.aggregate_type}:{event.aggregate_id}{version}  "
        f"by {event.actor.type}:{event.actor.id}  {payload}"
    )


async def tail(  # noqa: PLR0913 - CLI options
    js: JetStreamContext,
    names: BusNames,
    *,
    tenant: str | None,
    pattern: str,
    since: datetime | str | None,
    out: TextIO,
    stop: asyncio.Event,
) -> int:
    """Print events as they arrive until `stop`; returns how many were printed."""
    subject = f"{names.events_root}.{tenant or '*'}.{pattern}"
    if pattern == ">" and tenant is None:
        subject = f"{names.events_root}.>"
    config = api.ConsumerConfig(deliver_policy=api.DeliverPolicy.NEW)
    if since == "all":
        config = api.ConsumerConfig(deliver_policy=api.DeliverPolicy.ALL)
    elif isinstance(since, datetime):
        config = api.ConsumerConfig(
            deliver_policy=api.DeliverPolicy.BY_START_TIME,
            opt_start_time=since,
        )
    printed = 0
    queue: asyncio.Queue[Msg] = asyncio.Queue()

    async def on_message(message: Msg) -> None:
        await queue.put(message)

    subscription = await js.subscribe(
        subject, stream=names.events_stream, ordered_consumer=True, config=config, cb=on_message
    )
    out.write(f"watching {subject} (Ctrl+C to stop)\n")
    out.flush()
    try:
        while not stop.is_set():
            try:
                message = await asyncio.wait_for(queue.get(), 0.5)
            except TimeoutError:
                continue
            out.write(format_event(message.data) + "\n")
            out.flush()
            printed += 1
    finally:
        await subscription.unsubscribe()
    return printed


@dataclass(frozen=True)
class DeadLetter:
    """One message in the DLQ stream."""

    seq: int
    subject: str
    data: bytes
    headers: dict[str, str]

    @property
    def consumer(self) -> str:
        """The consumer that gave up on it."""
        return self.headers.get("Supportx-Consumer", "?")

    def envelope(self) -> EventEnvelope | None:
        """The original event, if it is one."""
        try:
            return EventEnvelope.from_json(self.data)
        except ValueError:
            return None


async def dead_letters(
    js: JetStreamContext, names: BusNames, consumer: str | None = None
) -> list[DeadLetter]:
    """Every message currently in the DLQ (optionally of one consumer), oldest first."""
    info = await js.stream_info(names.dlq_stream)
    found: list[DeadLetter] = []
    if not info.state.messages:
        return found
    for seq in range(info.state.first_seq, info.state.last_seq + 1):
        try:
            raw = await js.get_msg(names.dlq_stream, seq)
        except NotFoundError:
            continue  # replayed (deleted) earlier
        letter = DeadLetter(
            seq=seq,
            subject=raw.subject or "",
            data=raw.data or b"",
            headers={k: str(v) for k, v in (raw.headers or {}).items()},
        )
        if consumer is None or letter.consumer == consumer:
            found.append(letter)
    return found


def format_dead_letter(letter: DeadLetter) -> str:
    """Two lines per dead letter: what and why."""
    event = letter.envelope()
    what = (
        f"{event.event_type} event={event.event_id} tenant={event.tenant_id}"
        if event
        else "(unparseable message)"
    )
    return (
        f"#{letter.seq}  consumer={letter.consumer}  {what}\n"
        f"      attempts={letter.headers.get('Supportx-Attempts', '?')}  "
        f"failed_at={letter.headers.get('Supportx-Failed-At', '?')}  "
        f"error={letter.headers.get('Supportx-Error-Type', '?')}: "
        f"{letter.headers.get('Supportx-Error', '')}"
    )


async def replay(js: JetStreamContext, names: BusNames, letter: DeadLetter) -> bool:
    """Send one dead letter back to its consumer only; remove it from the DLQ once accepted."""
    event = letter.envelope()
    if event is None:
        return False  # nothing a consumer could do with it; leave it for a human
    await js.publish(
        names.replay_subject(letter.consumer, event.tenant_id, event.event_type),
        letter.data,
        stream=names.events_stream,
        # Unique per DLQ entry: replaying the same letter twice (crash in between) stays one.
        headers={"Nats-Msg-Id": f"replay:{letter.consumer}:{letter.seq}:{event.event_id}"},
    )
    await js.delete_msg(names.dlq_stream, letter.seq)
    return True


async def heartbeats(bucket: KeyValue) -> dict[str, dict[str, object]]:
    """Every live worker's last heartbeat."""
    try:
        keys = await bucket.keys()
    except NoKeysError:
        return {}
    found: dict[str, dict[str, object]] = {}
    for key in sorted(keys):
        try:
            entry = await bucket.get(key)
        except nats.errors.Error:
            continue
        if entry.value:
            found[key] = json.loads(entry.value)
    return found


async def _tail(args: argparse.Namespace, connected: bus.Bus, out: TextIO) -> int:
    stop = asyncio.Event()
    try:
        await tail(
            connected.js,
            connected.names,
            tenant=args.tenant,
            pattern=args.type,
            since=parse_since(args.since),
            out=out,
            stop=stop,
        )
    except asyncio.CancelledError:
        stop.set()
    return 0


async def _dlq_list(args: argparse.Namespace, connected: bus.Bus, out: TextIO) -> int:
    letters = await dead_letters(connected.js, connected.names, args.consumer)
    out.writelines(format_dead_letter(letter) + "\n" for letter in letters)
    out.write(f"{len(letters)} dead letter(s)\n")
    return 0


async def _dlq_replay(args: argparse.Namespace, connected: bus.Bus, out: TextIO) -> int:
    if args.seq is None and not args.all:
        out.write("choose --seq N (one letter) or --all (optionally with --consumer)\n")
        return 2
    letters = await dead_letters(connected.js, connected.names, args.consumer)
    if args.seq is not None:
        letters = [letter for letter in letters if letter.seq == args.seq]
    replayed = 0
    for letter in letters:
        if await replay(connected.js, connected.names, letter):
            replayed += 1
            out.write(f"replayed #{letter.seq} to {letter.consumer}\n")
        else:
            out.write(f"skipped #{letter.seq}: not an event envelope\n")
    out.write(f"{replayed} replayed\n")
    return 0 if letters else 1


async def _stats(_args: argparse.Namespace, connected: bus.Bus, out: TextIO) -> int:
    names = connected.names
    beats = await heartbeats(connected.heartbeats)
    events = await connected.js.stream_info(names.events_stream)
    dlq = await connected.js.stream_info(names.dlq_stream)
    out.write(f"stream {names.events_stream}: {events.state.messages} messages\n")
    out.write(f"stream {names.dlq_stream}: {dlq.state.messages} dead letters\n")
    if not beats:
        out.write("no worker heartbeats (start make worker-relay / worker-consumers)\n")
    out.writelines(
        f"{key}: at={beat.get('at')} {json.dumps(beat.get('stats'))}\n"
        for key, beat in beats.items()
    )
    return 0


COMMANDS = {"tail": _tail, "dlq-list": _dlq_list, "dlq-replay": _dlq_replay, "stats": _stats}


async def run_command(args: argparse.Namespace, settings: Settings, out: TextIO) -> int:
    """Connect, run one subcommand, disconnect."""
    connected = await bus.connect(settings, "events-cli")
    try:
        return await COMMANDS[args.command](args, connected, out)
    finally:
        await connected.close()


def build_parser() -> argparse.ArgumentParser:
    """CLI arguments."""
    parser = argparse.ArgumentParser(prog="events", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tail_cmd = commands.add_parser("tail", help="print events live")
    tail_cmd.add_argument("--tenant", help="only this tenant ID")
    tail_cmd.add_argument("--type", default=">", help="e.g. identity_access.> (default: all)")
    tail_cmd.add_argument("--since", help="also show the last 30s/10m/2h/1d, or 'all'")
    dlq_list = commands.add_parser("dlq-list", help="list dead letters")
    dlq_list.add_argument("--consumer")
    dlq_replay = commands.add_parser("dlq-replay", help="send dead letters back to their consumer")
    dlq_replay.add_argument("--consumer")
    dlq_replay.add_argument("--seq", type=int)
    dlq_replay.add_argument("--all", action="store_true")
    commands.add_parser("stats", help="stream sizes and worker heartbeats")
    return parser


def main(argv: Sequence[str]) -> int:  # pragma: no cover - thin CLI over tested functions
    """Entry point."""
    args = build_parser().parse_args(argv)
    settings = Settings.load(service_name="supportx-events-cli")
    try:
        return asyncio.run(run_command(args, settings, sys.stdout))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main(sys.argv[1:]))
