import { PlusOutlined } from '@ant-design/icons';
import { App, Flex, Form, Input, Select, Space, Switch, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  useChangeWindows,
  useCreateChangeWindow,
  useRemoveChangeWindow,
  useUnits,
  useUpdateChangeWindow,
  type ChangeWindow,
  type ChangeWindowInput,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  DateTimeField,
  EditDrawer,
  FormProblem,
  RowActions,
  SettingsPageHeader,
  TimeZoneNote,
  ToneTag,
  TranslatedField,
  WriteButton,
  useAccess,
  useAppearance,
  useDateTime,
  useFormProblem,
  useLabel,
  type TranslatedValue,
} from '@supportx/ui';

import { labelled } from '../../incidents/labels';

type Kind = ChangeWindow['kind'];
type Mode = ChangeWindow['mode'];
const KINDS: Kind[] = ['freeze', 'maintenance'];
const MODES: Mode[] = ['block', 'warn'];
// D-156 (held for Haider): a new freeze blocks, a maintenance window warns.
const DEFAULT_MODE: Record<Kind, Mode> = { freeze: 'block', maintenance: 'warn' };

interface Draft {
  kind: Kind;
  mode: Mode;
  labels: TranslatedValue;
  description: string;
  starts_at: string | null;
  ends_at: string | null;
  repeat_weekly: boolean;
  repeat_until: string | null;
  site_ids: string[];
  group_ids: string[];
}

const fromWindow = (w: ChangeWindow | undefined): Draft => ({
  kind: w?.kind ?? 'freeze',
  mode: w?.mode ?? 'block',
  labels: w?.labels ?? (w ? { en: w.name } : {}),
  description: w?.description ?? '',
  starts_at: w?.starts_at ?? null,
  ends_at: w?.ends_at ?? null,
  repeat_weekly: w?.repeat_weekly ?? false,
  repeat_until: w?.repeat_until ?? null,
  site_ids: w?.site_ids ?? [],
  group_ids: w?.group_ids ?? [],
});

function WindowEditor({
  window,
  onClose,
}: {
  window: ChangeWindow | undefined;
  onClose: () => void;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = App.useApp();
  const sites = useUnits('sites');
  const groups = useUnits('groups');
  const create = useCreateChangeWindow();
  const update = useUpdateChangeWindow();
  const problem = useFormProblem();
  const key = useMemo(() => crypto.randomUUID(), []);
  const [draft, setDraft] = useState<Draft>(() => fromWindow(window));
  const [dirty, setDirty] = useState(false);
  const set = (next: Partial<Draft>) => {
    setDraft((now) => ({ ...now, ...next }));
    setDirty(true);
  };
  const name = (draft.labels.en ?? '').trim();
  const ready = name !== '' && draft.starts_at !== null && draft.ends_at !== null;
  const body = (): ChangeWindowInput => ({
    kind: draft.kind,
    mode: draft.mode,
    name,
    labels: Object.keys(draft.labels).length > 0 ? draft.labels : null,
    description: draft.description.trim() === '' ? null : draft.description.trim(),
    starts_at: draft.starts_at ?? '',
    ends_at: draft.ends_at ?? '',
    repeat_weekly: draft.repeat_weekly,
    repeat_until: draft.repeat_weekly ? draft.repeat_until : null,
    site_ids: draft.site_ids,
    group_ids: draft.group_ids,
  });
  const done = () => {
    void message.success(t('settings.saved'));
    onClose();
  };
  const save = () => {
    if (window === undefined) {
      create.mutate({ key, body: body() }, { onSuccess: done, onError: (e) => problem.show(e) });
    } else {
      update.mutate(
        { id: window.id, version: window.version, body: body() },
        { onSuccess: done, onError: (e) => problem.show(e) },
      );
    }
  };
  return (
    <EditDrawer
      open
      title={window ? labelled(window.labels, locale, () => window.name) : t('changes.windows.add')}
      okText={window ? t('actions.save') : t('changes.windows.add')}
      saving={create.isPending || update.isPending}
      okDisabled={!ready}
      okWhyNot={
        ready
          ? undefined
          : t(name === '' ? 'changes.windows.why.name' : 'changes.windows.why.times')
      }
      dirty={dirty}
      onCancel={onClose}
      onOk={save}
      testId="window-editor"
    >
      <Form layout="vertical" data-testid="window-form">
        <Form.Item label={t('changes.windows.kind')} htmlFor="window-kind">
          <Select<Kind>
            id="window-kind"
            value={draft.kind}
            onChange={(kind) => {
              // A new window takes its kind's default mode; an existing one keeps its own.
              set(window === undefined ? { kind, mode: DEFAULT_MODE[kind] } : { kind });
            }}
            data-testid="window-kind"
            options={KINDS.map((k) => ({ value: k, label: t(`change_window_kind.${k}`) }))}
          />
        </Form.Item>
        <Form.Item
          label={t('changes.windows.mode')}
          htmlFor="window-mode"
          extra={t(`changes.windows.mode_help.${draft.kind}`)}
        >
          <Select<Mode>
            id="window-mode"
            value={draft.mode}
            onChange={(mode) => {
              set({ mode });
            }}
            data-testid="window-mode"
            options={MODES.map((m) => ({ value: m, label: t(`change_window_mode.${m}`) }))}
          />
        </Form.Item>
        <TranslatedField
          label={t('changes.windows.name')}
          value={draft.labels}
          onChange={(labels) => {
            set({ labels });
          }}
          required={['en']}
          max={200}
          testId="window-name"
        />
        <Form.Item label={t('changes.boards.description')} htmlFor="window-description">
          <Input.TextArea
            id="window-description"
            rows={2}
            value={draft.description}
            onChange={(e) => {
              set({ description: e.target.value });
            }}
            data-testid="window-description"
          />
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('releases.downtime.starts')} required htmlFor="window-starts">
            <DateTimeField
              id="window-starts"
              value={draft.starts_at}
              onChange={(starts_at) => {
                set({ starts_at });
              }}
              testId="window-starts"
              hideZone
            />
          </Form.Item>
          <Form.Item label={t('releases.downtime.ends')} required htmlFor="window-ends">
            <DateTimeField
              id="window-ends"
              value={draft.ends_at}
              onChange={(ends_at) => {
                set({ ends_at });
              }}
              testId="window-ends"
              hideZone
            />
          </Form.Item>
        </Flex>
        <Space style={{ marginBottom: 16 }}>
          <Switch
            checked={draft.repeat_weekly}
            onChange={(repeat_weekly) => {
              set({ repeat_weekly });
            }}
            aria-label={t('changes.windows.weekly')}
            data-testid="window-weekly"
          />
          <Typography.Text>{t('changes.windows.weekly')}</Typography.Text>
        </Space>
        {draft.repeat_weekly && (
          <Form.Item
            label={t('changes.windows.until')}
            htmlFor="window-until"
            extra={t('changes.windows.until_help')}
          >
            <DateTimeField
              id="window-until"
              value={draft.repeat_until}
              onChange={(repeat_until) => {
                set({ repeat_until });
              }}
              testId="window-until"
              hideZone
            />
          </Form.Item>
        )}
        <TimeZoneNote />
        <Typography.Title level={5} style={{ marginTop: 16 }}>
          {t('changes.windows.scope')}
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          {t('changes.windows.scope_help')}
        </Typography.Paragraph>
        <Form.Item label={t('work_item.field.site_id')} htmlFor="window-sites">
          <Select
            id="window-sites"
            mode="multiple"
            allowClear
            optionFilterProp="label"
            value={draft.site_ids}
            onChange={(site_ids: string[]) => {
              set({ site_ids });
            }}
            placeholder={t('changes.windows.everyone')}
            data-testid="window-sites"
            options={(sites.data ?? []).map((s) => ({ value: s.id, label: s.name }))}
          />
        </Form.Item>
        <Form.Item label={t('work_item.field.group_id')} htmlFor="window-groups">
          <Select
            id="window-groups"
            mode="multiple"
            allowClear
            optionFilterProp="label"
            value={draft.group_ids}
            onChange={(group_ids: string[]) => {
              set({ group_ids });
            }}
            placeholder={t('changes.windows.everyone')}
            data-testid="window-groups"
            options={(groups.data ?? []).map((g) => ({ value: g.id, label: g.name }))}
          />
        </Form.Item>
        <FormProblem problem={problem} />
      </Form>
    </EditDrawer>
  );
}

/**
 * Freeze and maintenance windows on template E (WP-045c; ADR-042): every live window by start,
 * its kind, what a conflict does, when, and where; add, edit and remove. Needs
 * `changes.manage_windows` or `settings.manage`; the server audits every change. Live: another
 * admin's change shows at once.
 */
export function ChangeWindowsPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const { can } = useAccess();
  const { message, modal } = App.useApp();
  const windows = useChangeWindows();
  const remove = useRemoveChangeWindow();
  const [editing, setEditing] = useState<ChangeWindow | 'new'>();
  const manage = can('changes.manage_windows') || can('settings.manage');
  useTenantChannel((m) => {
    if (m.type === 'work_items.change_windows_changed') void windows.refetch();
  });
  const nameOf = (w: ChangeWindow) => labelled(w.labels, locale, () => w.name);
  return (
    <Flex vertical gap={16} data-testid="change-windows">
      <SettingsPageHeader
        title={t('nav.admin_change_windows')}
        description={t('setup.page.change-windows.description')}
        testId="admin-page-header"
        primaryAction={
          manage && (
            <WriteButton
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditing('new');
              }}
              data-testid="window-add"
            >
              {t('changes.windows.add')}
            </WriteButton>
          )
        }
      />
      <Table<ChangeWindow>
        rowKey="id"
        loading={windows.isPending}
        pagination={false}
        dataSource={windows.data ?? []}
        data-testid="windows-table"
        scroll={{ x: 820 }}
        columns={[
          { key: 'name', title: t('changes.windows.name'), render: (_, w) => nameOf(w) },
          {
            key: 'kind',
            title: t('changes.windows.kind'),
            render: (_, w) => (
              <Space wrap>
                <ToneTag tone={w.kind === 'freeze' ? 'error' : 'info'}>
                  {t(`change_window_kind.${w.kind}`)}
                </ToneTag>
                <span>{t(`change_window_mode.${w.mode}`)}</span>
              </Space>
            ),
          },
          {
            key: 'when',
            title: t('changes.windows.when'),
            render: (_, w) => (
              <Space direction="vertical" size={0}>
                <span
                  style={{ whiteSpace: 'nowrap' }}
                >{`${format(w.starts_at)} – ${format(w.ends_at)}`}</span>
                {w.repeat_weekly && (
                  <Typography.Text type="secondary">
                    {w.repeat_until
                      ? t('changes.windows.weekly_until', { date: format(w.repeat_until) })
                      : t('changes.windows.weekly')}
                  </Typography.Text>
                )}
              </Space>
            ),
          },
          {
            key: 'scope',
            title: t('changes.windows.scope'),
            render: (_, w) =>
              w.site_ids.length === 0 && w.group_ids.length === 0
                ? t('changes.windows.everyone')
                : t('changes.windows.scoped', {
                    sites: w.site_ids.length,
                    groups: w.group_ids.length,
                  }),
          },
          {
            key: 'actions',
            title: <span className="sr-only">{t('settings.actions')}</span>,
            align: 'end' as const,
            render: (_, w) =>
              manage && (
                <RowActions
                  rowName={nameOf(w)}
                  primary={{
                    key: 'edit',
                    label: t('actions.edit'),
                    onClick: () => {
                      setEditing(w);
                    },
                    testId: `window-${w.id}-edit`,
                  }}
                  more={[
                    {
                      key: 'delete',
                      label: t('actions.delete'),
                      danger: true,
                      onClick: () => {
                        void modal.confirm({
                          title: t('changes.windows.remove_title', { name: nameOf(w) }),
                          okButtonProps: { danger: true },
                          okText: t('actions.delete'),
                          onOk: () =>
                            remove.mutateAsync({ id: w.id, version: w.version }).then(() => {
                              void message.success(t('changes.windows.removed'));
                            }),
                        });
                      },
                      testId: `window-${w.id}-remove`,
                    },
                  ]}
                />
              ),
          },
        ]}
      />
      {editing !== undefined && (
        <WindowEditor
          window={editing === 'new' ? undefined : editing}
          onClose={() => {
            setEditing(undefined);
          }}
        />
      )}
    </Flex>
  );
}
