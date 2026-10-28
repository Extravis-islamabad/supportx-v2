import { Collapse, Descriptions, Drawer, Empty, List, Spin, Typography } from 'antd';
import { Link } from 'react-router';

import { useAuditEntry, useRoles, type AuditEntryDetail } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useDateTime, useLabel } from '@supportx/ui';

import { actorLabel, grantLabel, objectLabel, OUTCOME_COLOURS } from './present';
import { StateTag } from './StateTag';

// Settings that audit entries describe by name (old → new values are numbers or lists).
const NUMBER_DETAILS = new Set([
  'refusals',
  'window_minutes',
  'entries_checked',
  'first_broken_seq',
  'unsealed_overdue',
  'personal_rows_removed',
  'status',
]);

/**
 * One audit entry in plain words (REQ-AUD-003): when to the second, who (and how they acted),
 * what, on which object, the outcome and why, from where (client, IP address, request ID), the
 * change itself, the link to the record's history (REQ-AUD-006), and its place in the chain.
 */
export function AuditEntryDrawer({ id, onClose }: { id: string | undefined; onClose: () => void }) {
  const t = useLabel();
  const entry = useAuditEntry(id);
  return (
    <Drawer
      open={id !== undefined}
      onClose={onClose}
      width={560}
      title={
        entry.data === undefined ? t('audit.ui.entry') : t(`audit.action.${entry.data.action}`)
      }
      destroyOnHidden
      data-testid="audit-entry-drawer"
    >
      {entry.isPending ? (
        <Spin />
      ) : entry.data === undefined ? (
        <Empty />
      ) : (
        <Details e={entry.data} />
      )}
    </Drawer>
  );
}

function Details({ e }: { e: AuditEntryDetail }) {
  const t = useLabel();
  const dates = useDateTime();
  const roles = useRoles();
  const roleNames = new Map((roles.data ?? []).map((role) => [role.id, role.name]));
  const person = (id: string | null | undefined) =>
    id === null || id === undefined ? null : (e.names[id] ?? t('audit.ui.erased_person'));
  const actorPersonal = e.personal.find((p) => p.subject_id === e.actor_id);
  // The reason a person typed (free text, personal data), not a code.
  const statedWhy = actorPersonal?.reason;
  return (
    <>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label={t('audit.ui.col.time')}>
          <time dateTime={e.occurred_at}>{dates.formatExact(e.occurred_at)}</time>{' '}
          <Typography.Text type="secondary">({dates.zone})</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label={t('audit.ui.col.actor')}>
          {actorLabel(t, e)} · {t(`audit_actor_type.${e.actor_type}`)}
        </Descriptions.Item>
        {e.on_behalf_id !== null && (
          <Descriptions.Item label={t('audit.ui.on_behalf')}>
            {person(e.on_behalf_id)}
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t('audit.ui.col.action')}>
          {t(`audit.action.${e.action}`)} · {t(`audit_category.${e.category}`)}
        </Descriptions.Item>
        {e.object_type !== null && (
          <Descriptions.Item label={t('audit.ui.col.object')}>
            {objectLabel(t, e)}
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t('audit.ui.col.outcome')}>
          <StateTag tone={OUTCOME_COLOURS[e.outcome]}>{t(`audit_outcome.${e.outcome}`)}</StateTag>
          {e.reason_code !== null && t(`errors.${e.reason_code}`)}
        </Descriptions.Item>
        <Descriptions.Item label={t('audit.ui.col.client')}>
          {t(`audit_client.${e.client}`)}
        </Descriptions.Item>
        {actorPersonal?.ip != null && (
          <Descriptions.Item label={t('audit.ui.ip')}>{actorPersonal.ip}</Descriptions.Item>
        )}
        {actorPersonal?.user_agent != null && (
          <Descriptions.Item label={t('audit.ui.user_agent')}>
            {actorPersonal.user_agent}
          </Descriptions.Item>
        )}
        {statedWhy != null && (
          <Descriptions.Item label={t('audit.ui.reason')}>{statedWhy}</Descriptions.Item>
        )}
        {e.request_id !== null && (
          <Descriptions.Item label={t('audit.ui.request_id')}>
            <Typography.Text copyable code>
              {e.request_id}
            </Typography.Text>
          </Descriptions.Item>
        )}
        {e.change_id !== null && e.object_type === 'incident' && e.object_id !== null && (
          <Descriptions.Item label={t('audit.ui.history')}>
            <Link to={`/incidents/${e.object_id}?tab=history`}>{t('audit.ui.history_open')}</Link>
          </Descriptions.Item>
        )}
      </Descriptions>
      <Typography.Title level={5} style={{ marginTop: 16 }}>
        {t('audit.ui.what_changed')}
      </Typography.Title>
      <Change e={e} roleNames={roleNames} person={person} />
      <Collapse
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'integrity',
            label: t('audit.ui.integrity'),
            children: (
              <Descriptions column={1} size="small">
                <Descriptions.Item label={t('audit.ui.col.seal')}>
                  {e.seq === null
                    ? t('audit.pending_seal')
                    : t('audit.ui.sealed_at_position', { seq: e.seq })}
                </Descriptions.Item>
                {e.sealed_at !== null && (
                  <Descriptions.Item label={t('audit.ui.sealed_at')}>
                    {dates.formatExact(e.sealed_at)}
                  </Descriptions.Item>
                )}
                <Descriptions.Item label={t('audit.ui.entry_hash')}>
                  <Typography.Text code copyable style={{ wordBreak: 'break-all' }}>
                    {e.entry_hash}
                  </Typography.Text>
                </Descriptions.Item>
                {e.chain_hash !== null && (
                  <Descriptions.Item label={t('audit.ui.chain_hash')}>
                    <Typography.Text code copyable style={{ wordBreak: 'break-all' }}>
                      {e.chain_hash}
                    </Typography.Text>
                  </Descriptions.Item>
                )}
              </Descriptions>
            ),
          },
        ]}
      />
    </>
  );
}

function Change({
  e,
  roleNames,
  person,
}: {
  e: AuditEntryDetail;
  roleNames: Map<string, string>;
  person: (id: string | null | undefined) => string | null;
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const rows: { key: string; text: string }[] = [];
  const details = e.details as Record<string, unknown>;
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
  for (const code of list(details.grants_added)) {
    rows.push({ key: `+${code}`, text: t('audit.ui.grant_added', { grant: grantLabel(t, code) }) });
  }
  for (const code of list(details.grants_removed)) {
    rows.push({
      key: `-${code}`,
      text: t('audit.ui.grant_removed', { grant: grantLabel(t, code) }),
    });
  }
  if (details.renamed === true) rows.push({ key: 'renamed', text: t('audit.ui.renamed') });
  if (typeof details.role_id === 'string') {
    rows.push({
      key: 'role',
      text: t('audit.ui.role', { name: roleNames.get(details.role_id) ?? t('audit.ui.deleted') }),
    });
  }
  for (const key of ['user_id', 'reassigned_to'] as const) {
    if (typeof details[key] === 'string') {
      rows.push({ key, text: t(`audit.detail.${key}`, { name: person(details[key]) ?? '' }) });
    }
  }
  const changes = details.changes as Record<string, { old: unknown; new: unknown }> | undefined;
  for (const [field, change] of Object.entries(changes ?? {})) {
    const show = (value: unknown) =>
      Array.isArray(value)
        ? listFormat(value.map((v) => t(`audit_read_category.${String(v)}`)))
        : String(value);
    rows.push({
      key: field,
      text: t('audit.ui.setting_changed', {
        setting: t(`audit.setting.${field}`),
        old: show(change.old),
        new: show(change.new),
      }),
    });
  }
  for (const field of list(details.changed_fields)) {
    rows.push({
      key: `f-${field}`,
      text: t('audit.ui.field_changed', { field: t(`audit.field.${field}`) }),
    });
  }
  for (const key of Object.keys(details).filter((k) => NUMBER_DETAILS.has(k))) {
    const value = details[key];
    if (typeof value === 'number') {
      rows.push({ key, text: t(`audit.detail.${key}`, { value }) });
    }
  }
  if (rows.length === 0)
    return <Typography.Text type="secondary">{t('audit.ui.no_details')}</Typography.Text>;
  return (
    <List
      size="small"
      dataSource={rows}
      renderItem={(row) => <List.Item key={row.key}>{row.text}</List.Item>}
      data-testid="audit-entry-changes"
    />
  );
}
