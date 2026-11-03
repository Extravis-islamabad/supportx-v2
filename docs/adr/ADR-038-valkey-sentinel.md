# ADR-038: Valkey high availability through our own Sentinel on the official image

- **Status:** Proposed (WP-014b; the coordinator's choice for the product owner, 2026-11-04,
  pending his review)
- **Date:** 2026-11-04
- **Deciders:** Haider (Product Owner), lane B

## Context

Valkey holds the browser sessions of the backend-for-frontend (D-009), rate limits, the policy
and entitlement caches, and realtime's state. Losing its only node signs every person out and
stops rate limiting. The HA profile (WP-014b, D-038) must survive the loss of any one node.

The Valkey chart we bundle (valkey-io/valkey-helm 0.12.0, D-037) supports master and replica
replication, but has no Sentinel and so no automatic failover. The app reaches Valkey through
one client factory (`app/core/valkey.py`), which already speaks Sentinel when
`SUPPORTX_VALKEY_SENTINELS` is set.

## Decision

1. **In the HA profile our chart renders Valkey itself**: a StatefulSet of three pods on the
   official Valkey image, each with a Valkey server and a Sentinel (`valkey-sentinel`, the same
   image). They monitor one master named `supportx`, with a quorum of 2. The official chart
   can't be used here: its start-up script always makes pod 0 the master, so a restarted pod 0
   would claim the role again after a failover.
2. **No pod reclaims the master role by itself.** Each pod's start-up step asks the sentinels for
   the current master and starts as its replica unless it is that master. Only on a first start,
   when no sentinel answers, does pod 0 begin as master. A restarted former master rejoins as a
   replica (no split brain).
3. **The app and Centrifugo find the master through Sentinel** and follow a failover by
   themselves (`SUPPORTX_VALKEY_SENTINELS`; Centrifugo's own Sentinel support), which lets
   Centrifugo run more than one copy on the Valkey engine.
4. **The sentinels' password and TLS follow Valkey's own secret handling**: from the
   installation secret, never in a values file.
5. **Single-node installs keep the official chart** (one Valkey, optional replicas), where there
   is no second node to fail over to.
6. **A failover test** on the reduced HA profile on k3d, in CI, proves:
   - stopping the master lets Sentinel promote a replica;
   - the app reconnects, and a signed-in person's session survives;
   - the old master comes back as a replica.

## Options rejected

- **(b) Replication only, with manual failover in the runbook.** A lost master node would sign
  everyone out until an operator acts, which doesn't meet "survives the loss of any one node".
- **(c) A third-party chart with Sentinel built in.** The usual one's images are no longer
  published, and only legacy copies exist. That's a supply-chain risk for an on-prem product we
  must be able to rebuild.
- **Valkey Cluster mode.** It shards keys over several masters, which the app doesn't need. Its
  multi-key and pub/sub limits would ripple through the cache, the sessions and realtime.

## Consequences

- No new image or package: the official Valkey image and valkey-py, both approved (D-020,
  D-037).
- Our chart owns the HA Valkey StatefulSet and its start-up script, so their upgrades are
  ours. The failover test guards them.
- Sessions survive a failover only if they were replicated before the master was lost.
  Asynchronous replication can lose the last moments, and those people sign in again. This is
  accepted, and documented in the runbook.
