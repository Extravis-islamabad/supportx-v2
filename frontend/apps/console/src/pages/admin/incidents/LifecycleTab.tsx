import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Alert, Button, Flex, Modal, Select, Table, Tag, Typography } from 'antd';
import { useState } from 'react';

import {
  lifecycleKeys,
  useCustomFields,
  useLifecycleChange,
  useLifecycleMoves,
  useLifecycleVersions,
  usePermissionCatalogue,
  type IncidentCatalogue,
  type LifecycleBase,
  type LifecycleMove,
  type LifecycleProblem,
  type LifecycleVersion,
  type ReasonMode,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  describeError,
  SettingsCard,
  useAppearance,
  useDateTime,
  useLabel,
  useLicence,
  WriteButton,
} from '@supportx/ui';

import { statusLabel } from '../../incidents/labels';
import { fieldName } from '../../customFields/values';

// Admin › Incidents › Life cycle (ADR-049; WP-046a S4, REQ-INC-049): the life cycle's versions,
// and its draft's moves as a table (the canvas designer comes with S4b). Published versions
// never change; records keep the version they were made on, and the publish dialog says so.

const LIFECYCLE = 'standard';
const SETTINGS_CHANGED = 'work_items.settings_changed';
const MODES: ReasonMode[] = ['none', 'optional', 'required'];
const FIELDS = [
  'category_id',
  'site_id',
  'department_id',
  'group_id',
  'technician_id',
  'impact',
  'urgency',
  'level',
  'description',
  'tags',
] as const;
const TYPE_OF: Record<LifecycleBase, 'incident' | 'service_request' | 'problem'> = {
  incidents: 'incident',
  requests: 'service_request',
  problems: 'problem',
};

type Translate = ReturnType<typeof useLabel>;

/** One problem in words: statuses, actions, fields and rights by their names, never codes. */
function problemText(
  t: Translate,
  problem: LifecycleProblem,
  status: (code: string) => string,
  field: (name: string) => string,
): string {
  const p = problem.params;
  return t(`lifecycle_problem.${problem.code}`, {
    ...p,
    ...(p.status === undefined ? {} : { status: status(p.status) }),
    ...(p.action === undefined ? {} : { action: t(`work_item_action.${p.action}`) }),
    ...(p.field === undefined ? {} : { field: field(p.field) }),
    ...(p.permission === undefined ? {} : { permission: t(`permission.${p.permission}`) }),
  });
}

export function LifecycleTab({
  catalogue,
  base = 'incidents',
}: {
  catalogue: IncidentCatalogue;
  base?: LifecycleBase;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const { writable } = useLicence();
  const queryClient = useQueryClient();
  const versions = useLifecycleVersions(base, LIFECYCLE);
  const change = useLifecycleChange(base, LIFECYCLE);
  const rights = usePermissionCatalogue();
  const custom = useCustomFields(TYPE_OF[base]);
  const draft = versions.data?.items.find((v) => v.state === 'draft');
  const saved = useLifecycleMoves(base, LIFECYCLE, draft?.number);
  // The draft's moves as edited here, until saved (null: as last saved).
  const [edited, setEdited] = useState<LifecycleMove[] | null>(null);
  const [confirm, setConfirm] = useState<'publish' | 'discard' | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Another admin's change (or this one's in another window) reaches the screen live (§8).
  useTenantChannel((event) => {
    if (event.type === SETTINGS_CHANGED) {
      void queryClient.invalidateQueries({ queryKey: lifecycleKeys.all(base) });
    }
  });

  const status = (code: string | null) =>
    code === null ? t('settings.previous_status') : statusLabel(t, catalogue, code, locale);
  const fieldLabel = (name: string) => {
    if (name.startsWith('custom.')) {
      const found = (custom.data ?? []).find((f) => `custom.${f.key}` === name);
      return found ? fieldName(found, locale) : name;
    }
    return t(`work_item.field.${name}`);
  };
  const moves = edited ?? saved.data ?? [];
  const locked = change.isPending || !writable || versions.data === undefined;
  const statuses = catalogue.statuses.filter((s) => !s.system);
  const actions = [
    ...new Set([...catalogue.transitions.map((m) => m.action), ...moves.map((m) => m.action)]),
  ];
  const prefix = `${base}.`;
  const rightOptions = (rights.data ?? [])
    .filter((p) => p.key.startsWith(prefix))
    .map((p) => ({ value: p.key, label: t(`permission.${p.key}`) }));
  const fieldOptions = [
    ...FIELDS.map((name) => ({ value: name, label: t(`work_item.field.${name}`) })),
    ...(custom.data ?? [])
      .filter((f) => !f.retired)
      .map((f) => ({ value: `custom.${f.key}`, label: fieldName(f, locale) })),
  ];

  const run = (next: Parameters<typeof change.mutate>[0]['change'], onDone?: () => void): void => {
    if (versions.data === undefined) return;
    setError(null);
    change.mutate(
      { change: next, version: versions.data.settings_version },
      {
        onSuccess: () => {
          setEdited(null);
          onDone?.();
        },
        onError: (failure) => {
          setError(describeError(failure, t).title);
        },
      },
    );
  };
  const edit = (index: number, patch: Partial<LifecycleMove>) => {
    setEdited(moves.map((m, i) => (i === index ? { ...m, ...patch } : m)));
  };

  if (versions.isError) {
    return <Alert type="error" showIcon message={t('settings.load_failed')} />;
  }
  const items = versions.data?.items ?? [];
  const latest = versions.data?.latest_published;
  return (
    <Flex vertical gap={16}>
      <SettingsCard
        title={t('settings.lifecycle.versions')}
        description={t('settings.lifecycle.versions_help')}
        testId="lifecycle-versions"
      >
        {error !== null && (
          <Alert type="error" showIcon message={error} role="alert" data-testid="lifecycle-error" />
        )}
        <Table<LifecycleVersion>
          size="small"
          rowKey="number"
          pagination={false}
          loading={versions.isPending}
          dataSource={items}
          columns={[
            {
              key: 'number',
              title: t('settings.lifecycle.version'),
              render: (_: unknown, v) => (
                <Flex gap={8} align="center">
                  <span data-testid={`lifecycle-version-${String(v.number)}`}>
                    {t('settings.lifecycle.version_number', { number: v.number })}
                  </span>
                  {v.number === latest && (
                    <Tag color="blue">{t('settings.lifecycle.new_records_start_here')}</Tag>
                  )}
                </Flex>
              ),
            },
            {
              key: 'state',
              title: t('settings.lifecycle.state'),
              render: (_: unknown, v) => <Tag>{t(`lifecycle_version_state.${v.state}`)}</Tag>,
            },
            {
              key: 'published',
              title: t('settings.lifecycle.published_at'),
              render: (_: unknown, v) =>
                v.published_at === null ? '' : dates.format(v.published_at),
            },
            {
              key: 'moves',
              title: t('settings.lifecycle.moves'),
              render: (_: unknown, v) => v.moves,
            },
            {
              key: 'actions',
              title: t('settings.actions'),
              render: (_: unknown, v) =>
                v.state === 'published' && v.number !== latest ? (
                  <WriteButton
                    type="link"
                    size="small"
                    disabled={locked}
                    onClick={() => {
                      run({ kind: 'retire', number: v.number });
                    }}
                    data-testid={`lifecycle-retire-${String(v.number)}`}
                  >
                    {t('settings.lifecycle.retire')}
                  </WriteButton>
                ) : null,
            },
          ]}
        />
        {draft === undefined && (
          <WriteButton
            icon={<PlusOutlined />}
            disabled={locked}
            onClick={() => {
              run({ kind: 'start' });
            }}
            style={{ marginTop: 12 }}
            data-testid="lifecycle-start"
          >
            {t('settings.lifecycle.start_draft')}
          </WriteButton>
        )}
      </SettingsCard>
      {draft !== undefined && (
        <SettingsCard
          title={t('settings.lifecycle.draft_title', { number: draft.number })}
          description={t('settings.lifecycle.draft_help')}
          testId="lifecycle-draft"
        >
          {draft.problems.length > 0 && edited === null && (
            <Alert
              type="warning"
              showIcon
              message={t('settings.lifecycle.problems_title', { count: draft.problems.length })}
              description={
                <ul style={{ margin: 0, paddingInlineStart: 20 }}>
                  {draft.problems.map((p, i) => (
                    <li key={`${p.code}-${String(i)}`}>{problemText(t, p, status, fieldLabel)}</li>
                  ))}
                </ul>
              }
              data-testid="lifecycle-problems"
              style={{ marginBottom: 12 }}
            />
          )}
          <Table<LifecycleMove>
            size="small"
            rowKey={(m) => `${m.from_status}.${m.action}`}
            pagination={false}
            loading={saved.isPending}
            dataSource={moves}
            scroll={{ x: 960 }}
            columns={[
              {
                key: 'from',
                title: t('settings.from_status'),
                render: (_: unknown, m, i) => (
                  <Select
                    value={m.from_status}
                    disabled={locked}
                    aria-label={t('settings.from_status')}
                    style={{ minWidth: 160 }}
                    options={statuses.map((s) => ({ value: s.code, label: status(s.code) }))}
                    onChange={(value: string) => {
                      edit(i, { from_status: value });
                    }}
                    data-testid={`lifecycle-from-${String(i)}`}
                  />
                ),
              },
              {
                key: 'action',
                title: t('settings.status_action'),
                render: (_: unknown, m, i) => (
                  <Select
                    value={m.action}
                    disabled={locked}
                    aria-label={t('settings.status_action')}
                    style={{ minWidth: 160 }}
                    options={actions.map((a) => ({ value: a, label: t(`work_item_action.${a}`) }))}
                    onChange={(value: LifecycleMove['action']) => {
                      edit(i, { action: value });
                    }}
                  />
                ),
              },
              {
                key: 'to',
                title: t('settings.to_status'),
                render: (_: unknown, m, i) => (
                  <Select
                    value={m.to_status ?? ''}
                    disabled={locked}
                    aria-label={t('settings.to_status')}
                    style={{ minWidth: 160 }}
                    options={[
                      { value: '', label: t('settings.previous_status') },
                      ...statuses.map((s) => ({ value: s.code, label: status(s.code) })),
                    ]}
                    onChange={(value: string) => {
                      edit(i, { to_status: value === '' ? null : value });
                    }}
                  />
                ),
              },
              {
                key: 'reason',
                title: t('settings.reason'),
                render: (_: unknown, m, i) => (
                  <Select<ReasonMode>
                    value={m.reason_mode}
                    disabled={locked}
                    aria-label={t('settings.reason')}
                    style={{ minWidth: 120 }}
                    options={MODES.map((mode) => ({
                      value: mode,
                      label: t(`reason_mode.${mode}`),
                    }))}
                    onChange={(mode) => {
                      edit(i, {
                        reason_mode: mode,
                        reason_list: mode === 'none' ? null : m.reason_list,
                      });
                    }}
                  />
                ),
              },
              {
                key: 'permission',
                title: t('settings.lifecycle.extra_right'),
                render: (_: unknown, m, i) => (
                  <Select
                    allowClear
                    value={m.permission ?? undefined}
                    disabled={locked}
                    aria-label={t('settings.lifecycle.extra_right')}
                    placeholder={t('settings.lifecycle.no_extra_right')}
                    style={{ minWidth: 180 }}
                    options={rightOptions}
                    onChange={(value?: string) => {
                      edit(i, { permission: value ?? null });
                    }}
                  />
                ),
              },
              {
                key: 'fields',
                title: t('settings.lifecycle.required_fields'),
                render: (_: unknown, m, i) => (
                  <Select
                    mode="multiple"
                    value={m.required_fields ?? []}
                    disabled={locked}
                    aria-label={t('settings.lifecycle.required_fields')}
                    style={{ minWidth: 200 }}
                    optionFilterProp="label"
                    options={fieldOptions}
                    onChange={(values: string[]) => {
                      edit(i, { required_fields: values });
                    }}
                  />
                ),
              },
              {
                key: 'remove',
                title: '',
                width: 48,
                render: (_: unknown, m, i) => (
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    disabled={locked}
                    aria-label={t('settings.lifecycle.remove_move', {
                      action: t(`work_item_action.${m.action}`),
                      status: status(m.from_status),
                    })}
                    onClick={() => {
                      setEdited(moves.filter((_m, j) => j !== i));
                    }}
                  />
                ),
              },
            ]}
          />
          <Flex gap={8} wrap style={{ marginTop: 12 }}>
            <WriteButton
              icon={<PlusOutlined />}
              disabled={locked || statuses.length === 0 || actions.length === 0}
              onClick={() => {
                const first = statuses[0]?.code ?? '';
                setEdited([
                  ...moves,
                  {
                    from_status: first,
                    action: actions[0] ?? 'start_work',
                    to_status: first,
                    reason_mode: 'none',
                    reason_list: null,
                    permission: null,
                    required_fields: [],
                  },
                ]);
              }}
              data-testid="lifecycle-add-move"
            >
              {t('settings.lifecycle.add_move')}
            </WriteButton>
            <WriteButton
              type="primary"
              disabled={locked || edited === null}
              onClick={() => {
                run({ kind: 'save', moves });
              }}
              data-testid="lifecycle-save"
            >
              {t('settings.lifecycle.save_draft')}
            </WriteButton>
            <WriteButton
              disabled={locked || edited !== null || draft.problems.length > 0}
              onClick={() => {
                setConfirm('publish');
              }}
              data-testid="lifecycle-publish"
            >
              {t('settings.lifecycle.publish')}
            </WriteButton>
            <WriteButton
              danger
              disabled={locked}
              onClick={() => {
                setConfirm('discard');
              }}
              data-testid="lifecycle-discard"
            >
              {t('settings.lifecycle.discard')}
            </WriteButton>
          </Flex>
          {edited !== null && (
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
              {t('settings.lifecycle.unsaved')}
            </Typography.Text>
          )}
        </SettingsCard>
      )}
      <Modal
        open={confirm !== null}
        title={
          confirm === 'publish'
            ? t('settings.lifecycle.publish_title', { number: draft?.number ?? 0 })
            : t('settings.lifecycle.discard_title', { number: draft?.number ?? 0 })
        }
        okText={
          confirm === 'publish' ? t('settings.lifecycle.publish') : t('settings.lifecycle.discard')
        }
        okButtonProps={{ danger: confirm === 'discard', loading: change.isPending }}
        cancelText={t('actions.cancel')}
        onCancel={() => {
          setConfirm(null);
        }}
        onOk={() => {
          if (confirm === null) return;
          run({ kind: confirm }, () => {
            setConfirm(null);
          });
        }}
        destroyOnHidden
      >
        <Typography.Paragraph data-testid={`lifecycle-confirm-${confirm ?? ''}`}>
          {confirm === 'publish'
            ? t('settings.lifecycle.publish_body')
            : t('settings.lifecycle.discard_body')}
        </Typography.Paragraph>
      </Modal>
    </Flex>
  );
}
