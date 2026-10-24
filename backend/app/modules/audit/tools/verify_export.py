#!/usr/bin/env python3
# ruff: noqa: EM101, EM102, TRY003, T201 - a standalone CLI shipped inside exports: plain messages, prints
"""Verify a SupportX audit export offline (REQ-AUD-009; ADR-027).

Usage:
    python3 verify_export.py supportx-audit-export.zip

Needs only Python 3.10 or later and its standard library. If the `cryptography` package is
installed, the Ed25519 signatures of the manifest and of the chain anchors are checked too;
otherwise the script says they were not checked (see README.txt in the export for the openssl
commands).

What it checks:
1. the data file is exactly the one the manifest describes (SHA-256);
2. every entry still hashes to its recorded entry hash (nothing in it was changed);
3. every chain link follows from the previous one and from its entry, and, for a complete
   (unfiltered) export, that no position is missing between the first and the last;
4. personal data still matches the commitments inside the hashed entries;
5. anchors (signed checkpoints) name chain values that are in the export.

Exit code 0: verified. Exit code 1: the export was changed or is incomplete; the first problem
is printed. The byte layout matches app/modules/audit/domain/integrity.py; keep them in step.
"""

import csv
import hashlib
import io
import json
import sys
import uuid
import zipfile
from typing import Any

DOMAIN_TAG = b"sx-audit-v1"
GENESIS = "00" * 32


class Broken(Exception):
    """The first problem found."""


def canonical(value: Any) -> bytes:  # noqa: ANN401 - plain JSON values
    """Canonical JSON: sorted keys, no whitespace, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    """Hex SHA-256."""
    return hashlib.sha256(data).hexdigest()


def chain_hash(tenant: str, seq: int, previous: str, entry: str) -> str:
    """The chain link for position `seq`."""
    return sha256_hex(
        DOMAIN_TAG
        + uuid.UUID(tenant).bytes
        + seq.to_bytes(8, "big", signed=True)
        + bytes.fromhex(previous)
        + bytes.fromhex(entry)
    )


def records(data: bytes, data_format: str) -> list[dict[str, Any]]:
    """The export's records, in file order."""
    if data_format == "jsonl":
        return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    rows = csv.DictReader(io.StringIO(data.decode("utf-8")))
    return [
        {
            "seq": int(row["seq"]),
            "prev_hash": row["prev_hash"],
            "chain_hash": row["chain_hash"],
            "entry_hash": row["entry_hash"],
            "entry": json.loads(row["entry"]),
            "personal": json.loads(row["personal"] or "{}"),
        }
        for row in rows
    ]


def check_record(tenant: str, record: dict[str, Any]) -> None:
    """Entry hash, personal commitments and the link of one record."""
    seq = record["seq"]
    entry = record["entry"]
    if sha256_hex(canonical(entry)) != record["entry_hash"]:
        raise Broken(f"entry at position {seq} ({entry.get('id')}) was changed")
    commitments = entry.get("personal_commitments") or {}
    for subject, personal in (record.get("personal") or {}).items():
        expected = sha256_hex(bytes.fromhex(personal["salt"]) + canonical(personal["data"]))
        if commitments.get(subject) != expected:
            raise Broken(f"personal data of entry at position {seq} was changed")
    if chain_hash(tenant, seq, record["prev_hash"], record["entry_hash"]) != record["chain_hash"]:
        raise Broken(f"chain link at position {seq} does not follow from its entry")


def check_chain(manifest: dict[str, Any], items: list[dict[str, Any]]) -> None:
    """Order and completeness of the chain."""
    complete = bool(manifest.get("complete"))
    previous_seq = None
    previous_hash = manifest.get("previous_chain_hash") or GENESIS
    for record in items:
        seq = record["seq"]
        if previous_seq is not None and seq <= previous_seq:
            raise Broken(f"positions out of order at {seq}")
        if complete:
            expected_seq = (previous_seq + 1) if previous_seq is not None else manifest["first_seq"]
            if seq != expected_seq:
                raise Broken(f"position {expected_seq} is missing")
            if record["prev_hash"] != previous_hash:
                raise Broken(f"chain is broken before position {seq}")
        previous_seq, previous_hash = seq, record["chain_hash"]
    if complete and items and previous_seq != manifest["last_seq"]:
        raise Broken(f"entries after position {previous_seq} are missing")
    if len(items) != manifest["entries"]:
        raise Broken(f"the manifest lists {manifest['entries']} entries, the file has {len(items)}")


def verify_signature(public_hex: str, message: bytes, signature_hex: str) -> bool | None:
    """True or False if `cryptography` is installed, None if it is not."""
    try:
        from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
            Ed25519PublicKey,
        )
    except ImportError:
        return None
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex)).verify(
            bytes.fromhex(signature_hex), message
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def check_anchors(manifest: dict[str, Any], items: list[dict[str, Any]]) -> str:
    """Anchors match the exported chain; signatures checked when possible."""
    by_seq = {record["seq"]: record["chain_hash"] for record in items}
    trusted = manifest.get("trusted_keys") or {}
    unchecked = 0
    for anchor in manifest.get("anchors") or []:
        if anchor["seq"] in by_seq and by_seq[anchor["seq"]] != anchor["chain_hash"]:
            raise Broken(f"anchor at position {anchor['seq']} no longer matches the chain")
        if trusted.get(anchor["key_id"]) != anchor["public_key"]:
            raise Broken(f"anchor at position {anchor['seq']} uses an untrusted key")
        message = canonical(
            {
                "chain_hash": anchor["chain_hash"],
                "created_at": anchor["created_at"],
                "seq": anchor["seq"],
                "tenant_id": manifest["tenant_id"],
                "v": 1,
            }
        )
        valid = verify_signature(anchor["public_key"], message, anchor["signature"])
        if valid is False:
            raise Broken(f"anchor at position {anchor['seq']} has an invalid signature")
        unchecked += valid is None
    return (
        f", {unchecked} anchor signatures not checked (cryptography not installed)"
        if unchecked
        else ""
    )


def verify(path: str) -> str:
    """Verify the export at `path`; returns a summary or raises Broken."""
    with zipfile.ZipFile(path) as archive:
        manifest_bytes = archive.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        data = archive.read(manifest["data_file"])
        signature = (
            json.loads(archive.read("manifest.sig"))
            if "manifest.sig" in archive.namelist()
            else None
        )
    if sha256_hex(data) != manifest["data_sha256"]:
        raise Broken("the data file was changed (SHA-256 differs from the manifest)")
    items = records(data, manifest["format"])
    for record in items:
        check_record(manifest["tenant_id"], record)
    check_chain(manifest, items)
    note = check_anchors(manifest, items)
    if signature is not None:
        public = (manifest.get("trusted_keys") or {}).get(signature["key_id"])
        valid = public and verify_signature(public, manifest_bytes, signature["signature"])
        if valid is False or public is None:
            raise Broken("the manifest signature is not valid")
        if valid is None:
            note += ", manifest signature not checked (cryptography not installed)"
    first, last = (items[0]["seq"], items[-1]["seq"]) if items else (None, None)
    kind = "complete" if manifest.get("complete") else "filtered"
    return f"verified {len(items)} entries ({kind}), positions {first} to {last}{note}"


def main(argv: list[str]) -> int:
    """Command line entry point."""
    if len(argv) != 2:  # noqa: PLR2004 - program name + one path
        print("usage: verify_export.py <export.zip>", file=sys.stderr)
        return 2
    try:
        print(verify(argv[1]))
    except Broken as problem:
        print(f"NOT VERIFIED: {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
