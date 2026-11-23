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

## Addendum A (D-166, 2026-11-12): object storage in the HA profile, by SeaweedFS's own replication

*Approved by the coordinator for Haider on 2026-11-12 (D-166); lane B builds it. The same rule as
for Valkey: in the HA profile our chart runs the bundled stateful service in its upstream's own
HA mode, on the image we already pin, rather than a third-party chart or a new product.*

1. **Topology.** With `objectStorage.seaweedfs.ha` (on in `values-ha.yaml`) the chart runs, on
   `chrislusf/seaweedfs:4.48`: three masters in one raft group (hashicorp raft, so leadership can
   be handed over before maintenance), three volume servers and two filers, each running the S3
   gateway, behind the existing `<release>-seaweedfs` Service on port 8333. The app's settings
   do not change. Every copy of a component runs on its own node (required anti-affinity,
   whatever `ha.antiAffinity` says), with PodDisruptionBudgets (masters and volume servers 2,
   filers 1).
2. **Copies.** The masters' default replication is `001`: a second copy on another volume server
   of the same rack. All servers share SeaweedFS's default rack: with a rack per server, `001`
   could not be placed (it counts servers within one rack) and `010` would be needed. Because
   every server is on its own node, "another server" is another node. `002` (three copies) is
   allowed; the chart refuses `000` and too few volume servers to write every copy with one lost.
3. **Repair.** The leader master runs SeaweedFS's maintenance script every 17 minutes, under the
   cluster lock: `volume.deleteEmpty -quietFor=24h`, `volume.balance` and
   `volume.fix.replication` (all `-apply`, the 4.48 spelling of the older `-force`).
4. **File tree in PostgreSQL.** The filers use SeaweedFS's `postgres2` store in the release's own
   CloudNativePG cluster: a `Database` resource (`seaweedfs_filer`, kept on uninstall) owned by a
   CloudNativePG managed role `seaweedfs_filer` with sign-in only (no superuser, database or
   role creation, replication, RLS bypass or inheritance) and a connection limit. pg_hba lets it
   sign in over TLS to its own database only and refuses it everywhere else, so it cannot reach
   SupportX's, Keycloak's or Temporal's data. Its password is in its own basic-auth Secret
   (`deploy/scripts/secrets.sh`), passed to the filer as `WEED_POSTGRES2_PASSWORD`, never in the
   ConfigMap. The file tree is therefore in the database backups and restore.
5. **Single-node and dev keep the single `weed server` pod**, unchanged. With
   `objectStorage.mode: external` none of this is installed; the customer's own S3-compatible
   store stays a supported HA install.
6. **Proof.** The HA preflight checks the masters' and volume servers' spread and the
   replication from the running pods; the Cluster workflow's HA job stops the node with the raft
   leader and a volume server and requires every file to read and write within 60 s and every
   volume to get its copies back (`deploy/k3d/objects-node-loss.sh`); the restore drill checks
   the file tree's database comes back.

**Consequences.** Twice the disk with `001`. File reads and writes depend on the database: they
pause while it fails over, like the rest of SupportX. Replication is not a backup: a deleted or
overwritten file is gone in every copy, so the file-store backup (audit gap #1) is still needed.
A single-copy install moves to HA by a documented rclone copy and `rclone check`, not
automatically (docs/deployment.md).
