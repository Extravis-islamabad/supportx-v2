import { PlusOutlined } from '@ant-design/icons';
import { App, Flex, Form, Input, Select, Space, Switch, Table, Typography } from 'antd';
import { useMemo, useState } from 'react';

import {
  useChangeSettingsChange,
  useChangeWindows,
  useCreateChangeWindow,
  useStagedSettings,
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
  SettingsCard,
  SettingsPageHeader,
  reportError,
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
// D-156: weekly, or monthly on the Nth weekday ("first Sunday"; week 5 is the last).
const REPEATS = ['none', 'weekly', 'monthly'] as const;
type Repeat = (typeof REPEATS)[number];
const WEEKS = [1, 2, 3, 4, 5] as const;
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6] as const; // Monday .. Sunday, as the server counts
// The list starts on the tenant's first day of the week (lane C's #384 review).
const FIRST_WEEKDAY = { monday: 0, sunday: 6, saturday: 5 } as const;

interface Draft {
  kind: Kind;
  mode: Mode;
  labels: TranslatedValue;
  description: string;
  starts_at: string | null;
  ends_at: string | null;
  repeat: Repeat;
  repeat_week: number | null;
  repeat_weekday: number | null;
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
  repeat: w?.repeat ?? 'none',
  repeat_week: w?.repeat_week ?? null,
  repeat_weekday: w?.repeat_weekday ?? null,
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
  const { locale, dates } = useAppearance();
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
  const monthly = draft.repeat === 'monthly';
  const ready =
    name !== '' &&
    draft.starts_at !== null &&
    draft.ends_at !== null &&
    (!monthly || (draft.repeat_week !== null && draft.repeat_weekday !== null));
  const body = (): ChangeWindowInput => ({
    kind: draft.kind,
    mode: draft.mode,
    name,
    labels: Object.keys(draft.labels).length > 0 ? draft.labels : null,
    description: draft.description.trim() === '' ? null : draft.description.trim(),
    starts_at: draft.starts_at ?? '',
    ends_at: draft.ends_at ?? '',
    repeat: draft.repeat,
    repeat_weekly: draft.repeat === 'weekly', // kept in step for one release (0137)
    repeat_week: monthly ? draft.repeat_week : null,
    repeat_weekday: monthly ? draft.repeat_weekday : null,
    repeat_until: draft.repeat === 'none' ? null : draft.repeat_until,
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
        <Flex gap={12} wrap>
          <Form.Item label={t('changes.windows.repeat')} htmlFor="window-repeat">
            <Select<Repeat>
              id="window-repeat"
              style={{ minWidth: 180 }}
              value={draft.repeat}
              onChange={(repeat) => {
                set({ repeat });
              }}
              options={REPEATS.map((code) => ({ value: code, label: t(`window_repeat.${code}`) }))}
              data-testid="window-repeat"
            />
          </Form.Item>
          {monthly && (
            <>
              <Form.Item label={t('changes.windows.week')} required htmlFor="window-week">
                <Select<number>
                  id="window-week"
                  style={{ minWidth: 140 }}
                  value={draft.repeat_week ?? undefined}
                  onChange={(repeat_week) => {
                    set({ repeat_week });
                  }}
                  options={WEEKS.map((n) => ({ value: n, label: t(`window_week.${String(n)}`) }))}
                  data-testid="window-week"
                />
              </Form.Item>
              <Form.Item label={t('changes.windows.weekday')} required htmlFor="window-weekday">
                <Select<number>
                  id="window-weekday"
                  style={{ minWidth: 160 }}
                  value={draft.repeat_weekday ?? undefined}
                  onChange={(repeat_weekday) => {
                    set({ repeat_weekday });
                  }}
                  options={[
                    ...WEEKDAYS.slice(FIRST_WEEKDAY[dates.weekStart]),
                    ...WEEKDAYS.slice(0, FIRST_WEEKDAY[dates.weekStart]),
                  ].map((n) => ({
                    value: n,
                    label: t(`window_weekday.${String(n)}`),
                  }))}
                  data-testid="window-weekday"
                />
              </Form.Item>
            </>
          )}
        </Flex>
        {draft.repeat !== 'none' && (
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
      <OutsideMaintenanceSetting editable={manage} />
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
                {w.repeat === 'weekly' && (
                  <Typography.Text type="secondary">
                    {w.repeat_until
                      ? t('changes.windows.weekly_until', { date: format(w.repeat_until) })
                      : t('changes.windows.weekly')}
                  </Typography.Text>
                )}
                {w.repeat === 'monthly' && w.repeat_week !== null && w.repeat_weekday !== null && (
                  <Typography.Text type="secondary" data-testid={`window-monthly-${w.id}`}>
                    {t('changes.windows.monthly_on', {
                      week: t(`window_week.${String(w.repeat_week)}`),
                      day: t(`window_weekday.${String(w.repeat_weekday)}`),
                    })}
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

/**
 * D-156: whether a change outside every maintenance window is refused instead of warned (the
 * tenant's choice; off by default). Saved at once with the settings' If-Match; audited.
 */
function OutsideMaintenanceSetting({ editable }: { editable: boolean }) {
  const t = useLabel();
  const { message } = App.useApp();
  const settings = useStagedSettings('changes');
  const change = useChangeSettingsChange();
  const current = settings.data;
  if (current === undefined) return null;
  return (
    <SettingsCard title={t('changes.windows.rules')} testId="windows-rules">
      <Flex gap={12} align="flex-start">
        <Switch
          checked={current.outside_maintenance_blocks}
          disabled={!editable}
          loading={change.isPending}
          onChange={(on) => {
            change.mutate(
              { body: { outside_maintenance_blocks: on }, version: current.version },
              {
                onSuccess: () => void message.success(t('settings.saved')),
                onError: reportError,
              },
            );
          }}
          aria-label={t('changes.windows.outside_blocks')}
          data-testid="windows-outside-blocks"
        />
        <Flex vertical gap={2}>
          <Typography.Text>{t('changes.windows.outside_blocks')}</Typography.Text>
          <Typography.Text type="secondary">
            {t('changes.windows.outside_blocks_help')}
          </Typography.Text>
        </Flex>
      </Flex>
    </SettingsCard>
  );
}
