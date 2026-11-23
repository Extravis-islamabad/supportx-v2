# Restoring the database (WP-014b)

The database's WAL is archived continuously and a base backup is taken daily
(`postgresql.cnpg.backup`, [deployment.md, Backups](../deployment.md#backups)), so it can be
restored to any moment within the retention period. CI runs this runbook's restore steps on
every change to the deployment (`deploy/k3d/restore-drill.sh`, in Cluster > k3d HA smoke):
a restore here is a command that has worked, not one first tried on the bad day.

## Before you need it

- **Backups outside the cluster, encrypted at rest.** The chart refuses an external target
  without encryption, and warns when backups stay in the cluster.
- **The keys that read them.** Keep copies of the backup bucket's credentials
  (`credentialsSecret`) and of the installation secret outside the cluster. Without them the
  backups can't be read; for the offsite copy, a lost encryption key means the backups are gone
  for good.
- **Check that backups run:**
  ```sh
  kubectl -n supportx get backups.postgresql.cnpg.io -l cnpg.io/cluster=supportx-pg
  kubectl -n supportx get clusters.postgresql.cnpg.io supportx-pg \
    -o jsonpath='{.status.conditions[?(@.type=="ContinuousArchiving")].status}'   # True
  ```

## 1. Choose the moment

Pick the last good moment, in UTC, e.g. just before a bad import:
`2026-11-04 14:30:00+00`. Any moment between the oldest kept base backup and the last archived
WAL works.

## 2. Stop writes

Scale the API and workers to zero so nothing writes while you restore. The HA SeaweedFS filers
(D-166) stay up: when the backups are in this release's own SeaweedFS (dev), the restore reads
them through the filers. CI's and production's backups are outside the cluster's nodes.
```sh
kubectl -n supportx scale deploy --replicas=0 \
  -l 'app.kubernetes.io/instance=supportx,app.kubernetes.io/component!=seaweedfs-filer'
```

## 3. Restore into a new cluster

Fill in `deploy/runbooks/restore-cluster.yaml` (its header lists the placeholders) and apply it:
```sh
sed -e 's|RESTORE_NAME|supportx-pg-restore|' -e 's|SOURCE_NAME|supportx-pg|' \
    -e 's|OBJECT_STORE|supportx-pg-backups|' -e "s|IMAGE|$(kubectl -n supportx get \
      clusters.postgresql.cnpg.io supportx-pg -o jsonpath='{.spec.imageName}')|" \
    -e 's|STORAGE|20Gi|' -e 's|TARGET_TIME|2026-11-04 14:30:00+00|' \
    deploy/runbooks/restore-cluster.yaml | kubectl -n supportx apply -f -
kubectl -n supportx wait clusters.postgresql.cnpg.io/supportx-pg-restore --for=condition=Ready --timeout=30m
```

Keep the name `<release>-pg-restore` (here `supportx-pg-restore`) when the egress allow-list
is on (`networkPolicies.egress.enabled`): the rule that opens an external backup target
(`networkPolicies.egress.database`) selects only the clusters `<release>-pg` and
`<release>-pg-restore`, so a restore cluster under another name cannot read the backups.

## 4. Check it

Look at the data as of the chosen moment before switching to it, for example the newest records:
```sh
kubectl -n supportx exec supportx-pg-restore-1 -c postgres -- psql -U postgres -d supportx \
  -c "SELECT max(created_at) FROM work_items"
```

With the HA SeaweedFS (D-166), the filers' file tree is the `seaweedfs_filer` database of this
same cluster, so it is restored to the same moment (the CI drill checks it has its entries):
```sh
kubectl -n supportx exec supportx-pg-restore-1 -c postgres -- psql -U postgres -d seaweedfs_filer \
  -c "SELECT count(*) FROM filemeta"
```
Files uploaded after the moment then have no entry (their data stays on the volume servers,
unused); files deleted after it have an entry but may have lost their data once SeaweedFS
reclaimed the space. The SupportX records restored to the same moment match the file tree.

## 5. Switch to it

**Not automated yet (WP-014b session 2, next):** a chart value that bootstraps
`<release>-pg` from the backups in place, so the app finds the restored database under its own
name. Until it lands, treat this runbook as checking that the backups restore, and ask lane B
before a production restore.

## After a restore: the event stream

Events newer than the chosen moment may already be on NATS while the restored database has
never heard of them. The stream reset for that comes with this runbook's next part (WP-014b
session 2).
