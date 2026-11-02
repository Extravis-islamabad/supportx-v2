import { DeleteOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons';
import {
  Alert,
  App,
  Button,
  Drawer,
  Flex,
  Form,
  Input,
  InputNumber,
  List,
  Popconfirm,
  Select,
  Space,
  Table,
  Tabs,
  Tooltip,
  Typography,
  Upload,
} from 'antd';
import { useMemo, useState } from 'react';
import { Navigate, useNavigate, useParams } from 'react-router';

import {
  ApiError,
  useSlaCalendarChange,
  useSlaCalendars,
  useSlaHolidayChange,
  useSlaHolidayListChange,
  useSlaHolidayLists,
  useSlaHolidays,
  useSlaSpecialHoursChange,
  type SlaCalendar,
  type SlaHoliday,
  type SlaHolidayImport,
  type SlaHolidayList,
  type SlaHolidayPart,
  type SlaSpecialHours,
  type SlaWeekPreset,
  type SlaWorkingPeriod,
} from '@supportx/api-client';
import {
  ConflictDialog,
  DateField,
  FormProblem,
  NoAccess,
  ToneTag,
  lengthLimit,
  markHandled,
  reportError,
  useAccess,
  useFormProblem,
  useLabel,
  useLicence,
} from '@supportx/ui';

import { minutes, weekMinutes } from './week';

type Translate = ReturnType<typeof useLabel>;
const SECTIONS = ['calendars', 'holidays'] as const;
const PRESETS: SlaWeekPreset[] = ['mon_fri', 'sun_thu', 'mon_sat'];
const PARTS: SlaHolidayPart[] = ['full', 'morning', 'afternoon'];
const ZONES: string[] =
  typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
// Quarter-hour steps; a period may end at 24:00 (midnight).
const STEPS = Array.from({ length: 97 }, (_, i) => {
  const minutes = i * 15;
  return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
});

/** A calendar's name for people: the system calendars by their label, others as typed. */
function calendarName(calendar: SlaCalendar, t: Translate, language: string): string {
  if (calendar.system_key !== null && calendar.name === systemEnglish(calendar.system_key)) {
    return t(`sla_calendar.${calendar.system_key}`);
  }
  return calendar.labels[language] ?? calendar.name;
}

function systemEnglish(key: string): string {
  return key === 'around_the_clock' ? 'Around the clock' : 'Operating hours';
}

function fieldProblems(error: ApiError, t: Translate): Record<string, string> {
  return Object.fromEntries(
    error.fieldErrors.map((f) => [
      f.field.replace(/^body\./, '').replace(/\..*$/, ''),
      t(f.message_key, f.params ?? {}),
    ]),
  );
}

/** Admin › SLA (WP-025): working calendars and holidays. Policies join in session 2. */
export function SlaPage() {
  const t = useLabel();
  const { can } = useAccess();
  const licence = useLicence();
  const navigate = useNavigate();
  const { section } = useParams();
  if (!licence.has('sla') || !can('sla.view')) return <NoAccess titleKey="nav.admin_sla" />;
  if (!SECTIONS.includes(section as (typeof SECTIONS)[number])) {
    return <Navigate to="/admin/sla/calendars" replace />;
  }
  const editable = can('sla.manage');
  return (
    <Tabs
      activeKey={section}
      onChange={(key) => void navigate(`/admin/sla/${key}`)}
      items={[
        {
          key: 'calendars',
          label: t('sla.calendars.title'),
          children: <CalendarsTab editable={editable} />,
        },
        {
          key: 'holidays',
          label: t('sla.holidays.title'),
          children: <HolidaysTab editable={editable} />,
        },
      ]}
    />
  );
}

// --- calendars -----------------------------------------------------------------------------------

function CalendarsTab({ editable }: { editable: boolean }) {
  const t = useLabel();
  const { message } = App.useApp();
  // Live: any change arrives as `sla.setup.changed` on the tenant channel (ConsoleLayout).
  const calendars = useSlaCalendars();
  const lists = useSlaHolidayLists();
  const { remove } = useSlaCalendarChange();
  const [editing, setEditing] = useState<SlaCalendar | 'new'>();
  const language = document.documentElement.lang || 'en';
  const listName = useMemo(
    () => new Map((lists.data ?? []).map((l) => [l.id, l.labels[language] ?? l.name])),
    [lists.data, language],
  );
  const rows = calendars.data ?? [];
  const live = editing === 'new' ? undefined : rows.find((r) => r.id === editing?.id);

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="baseline" wrap gap={8}>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          {t('sla.calendars.explain')}
        </Typography.Paragraph>
        {editable && (
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setEditing('new');
            }}
            data-testid="sla-calendar-add"
          >
            {t('sla.calendars.add')}
          </Button>
        )}
      </Flex>
      <Table<SlaCalendar>
        rowKey="id"
        loading={calendars.isPending}
        dataSource={rows}
        pagination={false}
        data-testid="sla-calendars"
        scroll={{ x: 'max-content' }}
        onRow={(row) => ({
          onClick: () => {
            if (editable) setEditing(row);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `sla-calendar-row-${row.id}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('sla.calendar.field.name'),
            render: (_, row) => (
              <Flex gap={6} wrap align="center">
                <bdi>{calendarName(row, t, language)}</bdi>
                {row.system_key !== null && (
                  <ToneTag tone="info">{t(`sla_calendar_kind.${row.kind}`)}</ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'week',
            title: t('sla.calendar.field.week'),
            render: (_, row) =>
              row.fixed
                ? t('sla_calendar_kind.around_the_clock')
                : t('sla.calendar.hours_per_week', {
                    hours: Math.round((weekMinutes(row.week) / 60) * 10) / 10,
                  }),
          },
          {
            key: 'zone',
            title: t('sla.calendar.field.time_zone'),
            render: (_, row) => (row.fixed ? '' : <bdi dir="ltr">{row.time_zone}</bdi>),
          },
          {
            key: 'holidays',
            title: t('sla.calendar.field.holiday_list_ids'),
            render: (_, row) => (
              <Flex gap={4} wrap>
                {row.holiday_list_ids.map((id) => (
                  <ToneTag key={id} tone="default">
                    <bdi>{listName.get(id) ?? ''}</bdi>
                  </ToneTag>
                ))}
              </Flex>
            ),
          },
          {
            key: 'used',
            title: t('sla.calendar.used_by'),
            render: (_, row) => (
              <bdi data-testid={`sla-calendar-used-${row.id}`}>
                {[...row.used_by_sites, ...row.used_by_groups].map((u) => u.name).join(' · ')}
              </bdi>
            ),
          },
          ...(editable
            ? [
                {
                  key: 'actions',
                  title: '',
                  render: (_: unknown, row: SlaCalendar) => {
                    const refusal = row.delete_refusal;
                    const button = (
                      <Button
                        type="text"
                        icon={<DeleteOutlined />}
                        aria-label={t('sla.calendars.delete')}
                        disabled={refusal !== null}
                        data-testid={`sla-calendar-delete-${row.id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                        }}
                      />
                    );
                    if (refusal !== null) {
                      return (
                        <Tooltip title={t(`action_reason.${refusal}`)}>
                          {/* A disabled button gets no hover: the span carries the reason. */}
                          <span data-testid={`sla-calendar-delete-reason-${row.id}`}>{button}</span>
                        </Tooltip>
                      );
                    }
                    return (
                      <Popconfirm
                        title={t('sla.calendars.delete_confirm')}
                        onConfirm={(event) => {
                          event?.stopPropagation();
                          remove.mutate(
                            { id: row.id, version: row.version },
                            {
                              onSuccess: () => void message.success(t('common.saved')),
                              onError: reportError,
                            },
                          );
                        }}
                      >
                        {button}
                      </Popconfirm>
                    );
                  },
                },
              ]
            : []),
        ]}
      />
      <CalendarEditor
        open={editing !== undefined}
        row={editing === 'new' ? undefined : editing}
        latest={live}
        lists={lists.data ?? []}
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Space>
  );
}

interface CalendarValues {
  name: string;
  label_ar?: string;
  label_ur?: string;
  time_zone: string;
  preset?: SlaWeekPreset;
  holiday_list_ids: string[];
}

function CalendarEditor({
  open,
  row,
  latest,
  lists,
  onClose,
}: {
  open: boolean;
  row: SlaCalendar | undefined;
  latest: SlaCalendar | undefined;
  lists: SlaHolidayList[];
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update } = useSlaCalendarChange();
  const [form] = Form.useForm<CalendarValues>();
  const problem = useFormProblem();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [week, setWeek] = useState<SlaWorkingPeriod[]>(row?.week ?? []);
  const [conflict, setConflict] = useState<unknown>();
  const [version, setVersion] = useState(row?.version);
  const [opened, setOpened] = useState(row?.id);
  // One Idempotency-Key per form: a retried save never makes a second calendar.
  const [key, setKey] = useState(() => crypto.randomUUID());
  if (row?.id !== opened) {
    setOpened(row?.id);
    setVersion(row?.version);
    setWeek(row?.week ?? []);
    setProblems({});
    setKey(crypto.randomUUID());
    problem.clear();
  }
  const fixed = row?.fixed === true;
  const stale = latest !== undefined && version !== undefined && latest.version !== version;

  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict && error.code === 'version_conflict') {
      setConflict(error);
      return;
    }
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(fieldProblems(error, t));
      return;
    }
    problem.show(error);
  };

  const save = (values: CalendarValues, at = version) => {
    setProblems({});
    problem.clear();
    const labels: Record<string, string> = {};
    if (values.label_ar?.trim()) labels.ar = values.label_ar.trim();
    if (values.label_ur?.trim()) labels.ur = values.label_ur.trim();
    const done = () => {
      void message.success(t('common.saved'));
      onClose();
    };
    if (row === undefined) {
      const body = {
        name: values.name,
        labels,
        time_zone: values.time_zone,
        holiday_list_ids: values.holiday_list_ids,
        ...(week.length > 0 ? { week } : { preset: values.preset ?? 'mon_fri' }),
      };
      create.mutate({ body, key }, { onSuccess: done, onError: failed });
      return;
    }
    const body = fixed
      ? { name: values.name, labels }
      : {
          name: values.name,
          labels,
          time_zone: values.time_zone,
          week,
          holiday_list_ids: values.holiday_list_ids,
        };
    update.mutate(
      { id: row.id, version: at ?? row.version, body },
      { onSuccess: done, onError: failed },
    );
  };

  const help = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={620}
      destroyOnHidden
      title={row === undefined ? t('sla.calendars.add') : t('sla.calendars.edit')}
      data-testid="sla-calendar-editor"
    >
      {stale && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('organization.changed_elsewhere')}
          data-testid="sla-calendar-stale"
        />
      )}
      {fixed && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t('sla.calendar.fixed')}
        />
      )}
      <Form<CalendarValues>
        form={form}
        layout="vertical"
        initialValues={{
          name: row?.name ?? '',
          label_ar: row?.labels.ar ?? '',
          label_ur: row?.labels.ur ?? '',
          time_zone: row?.time_zone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
          preset: 'mon_fri',
          holiday_list_ids: row?.holiday_list_ids ?? [],
        }}
        onFinish={(values) => {
          save(values);
        }}
      >
        <Form.Item name="name" label={t('sla.calendar.field.name')} required {...help('name')}>
          <Input count={lengthLimit(200)} data-testid="sla-calendar-name" />
        </Form.Item>
        <Form.Item label={t('sla.calendar.field.labels')} {...help('labels')}>
          <Space.Compact block>
            <Form.Item name="label_ar" noStyle>
              <Input dir="rtl" placeholder={t('locale.ar')} count={lengthLimit(200)} />
            </Form.Item>
            <Form.Item name="label_ur" noStyle>
              <Input dir="rtl" placeholder={t('locale.ur')} count={lengthLimit(200)} />
            </Form.Item>
          </Space.Compact>
        </Form.Item>
        {!fixed && (
          <>
            <Form.Item
              name="time_zone"
              label={t('sla.calendar.field.time_zone')}
              required
              {...help('time_zone')}
            >
              <Select
                showSearch
                options={ZONES.map((zone) => ({ value: zone, label: zone }))}
                data-testid="sla-calendar-zone"
              />
            </Form.Item>
            {row === undefined && week.length === 0 && (
              <Form.Item name="preset" label={t('sla.calendar.field.preset')}>
                <Select
                  data-testid="sla-calendar-preset"
                  options={PRESETS.map((p) => ({ value: p, label: t(`sla_week_preset.${p}`) }))}
                />
              </Form.Item>
            )}
            <Form.Item label={t('sla.calendar.field.week')} {...help('week')}>
              <WeekEditor value={week} onChange={setWeek} />
            </Form.Item>
            <Form.Item
              name="holiday_list_ids"
              label={t('sla.calendar.field.holiday_list_ids')}
              {...help('holiday_list_ids')}
            >
              <Select
                mode="multiple"
                allowClear
                optionFilterProp="label"
                data-testid="sla-calendar-lists"
                options={lists.map((l) => ({ value: l.id, label: l.name }))}
              />
            </Form.Item>
          </>
        )}
        {!fixed &&
          (row === undefined ? (
            <Typography.Paragraph type="secondary">
              {t('sla.special.save_first')}
            </Typography.Paragraph>
          ) : (
            <SpecialHoursSection calendar={latest ?? row} />
          ))}
        {row !== undefined && <UsedBy calendar={latest ?? row} />}
        <FormProblem problem={problem} />
        <Button
          type="primary"
          htmlType="submit"
          loading={create.isPending || update.isPending}
          data-testid="sla-calendar-save"
        >
          {t('actions.save')}
        </Button>
      </Form>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => t(`sla.calendar.field.${field}`)}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          if (latest === undefined) return;
          setVersion(latest.version);
          save(form.getFieldsValue(), latest.version);
        }}
      />
    </Drawer>
  );
}

/** Special hours for date ranges (Ramadan, a Friday prayer break), inside the calendar editor. */
function SpecialHoursSection({ calendar }: { calendar: SlaCalendar }) {
  const t = useLabel();
  const [editing, setEditing] = useState<SlaSpecialHours | 'new'>();
  return (
    <Form.Item label={t('sla.special.title')} extra={t('sla.special.explain')}>
      <List<SlaSpecialHours>
        size="small"
        bordered
        dataSource={calendar.special_hours}
        locale={{ emptyText: t('sla.special.empty') }}
        data-testid="sla-special-hours"
        renderItem={(item) => (
          <List.Item
            style={{ cursor: 'pointer' }}
            onClick={() => {
              setEditing(item);
            }}
            data-testid={`sla-special-${item.id}`}
          >
            <Flex vertical>
              <bdi>{item.name}</bdi>
              <Typography.Text type="secondary">
                <bdi dir="ltr">
                  {item.starts_on} – {item.ends_on}
                </bdi>{' '}
                ·{' '}
                {item.week.length === 0
                  ? t('sla.week.closed')
                  : t('sla.calendar.hours_per_week', {
                      hours: Math.round((weekMinutes(item.week) / 60) * 10) / 10,
                    })}
              </Typography.Text>
            </Flex>
          </List.Item>
        )}
      />
      <Button
        icon={<PlusOutlined />}
        style={{ marginTop: 8 }}
        onClick={() => {
          setEditing('new');
        }}
        data-testid="sla-special-add"
      >
        {t('sla.special.add')}
      </Button>
      <SpecialHoursEditor
        calendarId={calendar.id}
        row={editing === 'new' ? undefined : editing}
        open={editing !== undefined}
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Form.Item>
  );
}

function SpecialHoursEditor({
  calendarId,
  row,
  open,
  onClose,
}: {
  calendarId: string;
  row: SlaSpecialHours | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update, remove } = useSlaSpecialHoursChange(calendarId);
  const problem = useFormProblem();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<unknown>();
  const [name, setName] = useState(row?.name ?? '');
  const [startsOn, setStartsOn] = useState<string | null>(row?.starts_on ?? null);
  const [endsOn, setEndsOn] = useState<string | null>(row?.ends_on ?? null);
  const [week, setWeek] = useState<SlaWorkingPeriod[]>(row?.week ?? []);
  const [key] = useState(() => crypto.randomUUID());
  const [opened, setOpened] = useState(row?.id);
  if (row?.id !== opened) {
    setOpened(row?.id);
    setName(row?.name ?? '');
    setStartsOn(row?.starts_on ?? null);
    setEndsOn(row?.ends_on ?? null);
    setWeek(row?.week ?? []);
    setProblems({});
    problem.clear();
  }
  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict && error.code === 'version_conflict') {
      setConflict(error);
      return;
    }
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(fieldProblems(error, t));
      return;
    }
    problem.show(error);
  };
  const done = () => {
    void message.success(t('common.saved'));
    onClose();
  };
  const help = (field: string) =>
    problems[field] === undefined
      ? {}
      : { validateStatus: 'error' as const, help: problems[field] };
  const save = () => {
    setProblems({});
    problem.clear();
    const body = { name, starts_on: startsOn ?? '', ends_on: endsOn ?? startsOn ?? '', week };
    if (row === undefined) {
      create.mutate({ body, key }, { onSuccess: done, onError: failed });
    } else {
      update.mutate(
        { id: row.id, version: row.version, body },
        { onSuccess: done, onError: failed },
      );
    }
  };
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={600}
      destroyOnHidden
      title={row === undefined ? t('sla.special.add') : t('sla.special.edit')}
      data-testid="sla-special-editor"
    >
      <Form layout="vertical" onFinish={save}>
        <Form.Item label={t('sla.special.field.name')} required {...help('name')}>
          <Input
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
            count={lengthLimit(200)}
            data-testid="sla-special-name"
          />
        </Form.Item>
        <Flex gap={16} wrap>
          <Form.Item label={t('sla.special.field.starts_on')} required {...help('starts_on')}>
            <DateField value={startsOn} onChange={setStartsOn} testId="sla-special-starts" />
          </Form.Item>
          <Form.Item label={t('sla.special.field.ends_on')} required {...help('ends_on')}>
            <DateField value={endsOn} onChange={setEndsOn} testId="sla-special-ends" />
          </Form.Item>
        </Flex>
        <Form.Item
          label={t('sla.special.field.week')}
          extra={t('sla.special.break_hint')}
          {...help('week')}
        >
          <WeekEditor value={week} onChange={setWeek} />
        </Form.Item>
        <FormProblem problem={problem} />
        <Flex gap={8} wrap>
          <Button
            type="primary"
            htmlType="submit"
            loading={create.isPending || update.isPending}
            data-testid="sla-special-save"
          >
            {t('actions.save')}
          </Button>
          {row !== undefined && (
            <Button
              danger
              loading={remove.isPending}
              onClick={() => {
                remove.mutate(
                  { id: row.id, version: row.version },
                  { onSuccess: done, onError: failed },
                );
              }}
              data-testid="sla-special-remove"
            >
              {t('sla.special.remove')}
            </Button>
          )}
        </Flex>
      </Form>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => t(`sla.special.field.${field}`)}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          onClose();
        }}
      />
    </Drawer>
  );
}

function UsedBy({ calendar }: { calendar: SlaCalendar }) {
  const t = useLabel();
  const none = calendar.used_by_sites.length === 0 && calendar.used_by_groups.length === 0;
  return (
    <Form.Item label={t('sla.calendar.used_by')}>
      {none ? (
        <Typography.Text type="secondary">{t('sla.calendar.used_by_none')}</Typography.Text>
      ) : (
        <Space direction="vertical" size={4} data-testid="sla-calendar-used-by">
          {calendar.used_by_sites.length > 0 && (
            <span>
              {t('sla.calendar.sites')}:{' '}
              <bdi>{calendar.used_by_sites.map((s) => s.name).join(' · ')}</bdi>
            </span>
          )}
          {calendar.used_by_groups.length > 0 && (
            <span>
              {t('sla.calendar.groups')}:{' '}
              <bdi>{calendar.used_by_groups.map((g) => g.name).join(' · ')}</bdi>
            </span>
          )}
        </Space>
      )}
    </Form.Item>
  );
}

/** The working week: one row per period, a day and its start and end (in 15-minute steps). */
export function WeekEditor({
  value,
  onChange,
}: {
  value: SlaWorkingPeriod[];
  onChange: (week: SlaWorkingPeriod[]) => void;
}) {
  const t = useLabel();
  const set = (index: number, change: Partial<SlaWorkingPeriod>) => {
    onChange(value.map((p, i) => (i === index ? { ...p, ...change } : p)));
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }} data-testid="sla-week">
      {value.length === 0 && (
        <Typography.Text type="secondary">{t('sla.week.closed')}</Typography.Text>
      )}
      {value.map((period, index) => (
        <Flex key={index} gap={8} wrap align="center" data-testid={`sla-week-row-${String(index)}`}>
          <Select
            aria-label={t('sla.week.day')}
            style={{ minWidth: 140 }}
            value={period.weekday}
            onChange={(weekday) => {
              set(index, { weekday });
            }}
            options={[0, 1, 2, 3, 4, 5, 6].map((d) => ({
              value: d,
              label: t(`weekday.${String(d)}`),
            }))}
            data-testid={`sla-week-day-${String(index)}`}
          />
          <Select
            aria-label={t('sla.week.from')}
            style={{ width: 100 }}
            value={period.start}
            onChange={(start) => {
              set(index, { start });
            }}
            options={STEPS.slice(0, -1).map((s) => ({ value: s, label: s }))}
            data-testid={`sla-week-start-${String(index)}`}
          />
          <Select
            aria-label={t('sla.week.to')}
            style={{ width: 100 }}
            value={period.end}
            onChange={(end) => {
              set(index, { end });
            }}
            options={STEPS.slice(1).map((s) => ({ value: s, label: s }))}
            data-testid={`sla-week-end-${String(index)}`}
          />
          {minutes(period.end) <= minutes(period.start) && (
            <ToneTag tone="info">{t('sla.week.overnight')}</ToneTag>
          )}
          <Button
            type="text"
            icon={<DeleteOutlined />}
            aria-label={t('sla.week.remove_period')}
            onClick={() => {
              onChange(value.filter((_, i) => i !== index));
            }}
          />
        </Flex>
      ))}
      <Button
        icon={<PlusOutlined />}
        onClick={() => {
          const last = value.at(-1);
          onChange([
            ...value,
            {
              weekday: last === undefined ? 0 : (last.weekday + 1) % 7,
              start: last?.start ?? '09:00',
              end: last?.end ?? '18:00',
            },
          ]);
        }}
        data-testid="sla-week-add"
      >
        {t('sla.week.add_period')}
      </Button>
    </Space>
  );
}

// --- holidays ------------------------------------------------------------------------------------

function HolidaysTab({ editable }: { editable: boolean }) {
  const t = useLabel();
  const { message } = App.useApp();
  const lists = useSlaHolidayLists();
  const listChange = useSlaHolidayListChange();
  const [chosen, setChosen] = useState<string>();
  const [newName, setNewName] = useState('');
  const [listKey, setListKey] = useState(() => crypto.randomUUID());
  const rows = lists.data ?? [];
  const current = rows.find((l) => l.id === chosen) ?? rows[0];

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('sla.holidays.explain')}
      </Typography.Paragraph>
      <Flex gap={16} wrap align="flex-start">
        <div style={{ flex: '1 1 220px', maxWidth: 320 }}>
          <List<SlaHolidayList>
            bordered
            loading={lists.isPending}
            dataSource={rows}
            locale={{ emptyText: t('sla.holiday_lists.empty') }}
            data-testid="sla-holiday-lists"
            renderItem={(item) => (
              <List.Item
                onClick={() => {
                  setChosen(item.id);
                }}
                style={{
                  cursor: 'pointer',
                  fontWeight: item.id === current?.id ? 600 : undefined,
                }}
                data-testid={`sla-holiday-list-${item.id}`}
              >
                <bdi>{item.name}</bdi>
                <Typography.Text type="secondary">
                  {t('sla.holiday_list.count', { count: item.holiday_count })}
                </Typography.Text>
              </List.Item>
            )}
          />
          {editable && (
            <Space.Compact block style={{ marginTop: 8 }}>
              <Input
                value={newName}
                onChange={(event) => {
                  setNewName(event.target.value);
                }}
                placeholder={t('sla.holiday_list.field.name')}
                count={lengthLimit(200)}
                data-testid="sla-holiday-list-name"
              />
              <Button
                icon={<PlusOutlined />}
                disabled={newName.trim() === ''}
                loading={listChange.create.isPending}
                onClick={() => {
                  listChange.create.mutate(
                    { body: { name: newName.trim() }, key: listKey },
                    {
                      onSuccess: (created) => {
                        setNewName('');
                        setListKey(crypto.randomUUID());
                        setChosen(created.id);
                      },
                      onError: reportError,
                    },
                  );
                }}
                data-testid="sla-holiday-list-add"
              >
                {t('sla.holiday_lists.add')}
              </Button>
            </Space.Compact>
          )}
        </div>
        <div style={{ flex: '3 1 420px', minWidth: 0 }}>
          {current !== undefined && (
            <HolidayListPanel
              key={current.id}
              list={current}
              editable={editable}
              onDeleted={() => {
                setChosen(undefined);
                void message.success(t('common.saved'));
              }}
            />
          )}
        </div>
      </Flex>
    </Space>
  );
}

function HolidayListPanel({
  list,
  editable,
  onDeleted,
}: {
  list: SlaHolidayList;
  editable: boolean;
  onDeleted: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const [year, setYear] = useState(new Date().getFullYear());
  const holidays = useSlaHolidays(list.id, year);
  const change = useSlaHolidayChange(list.id);
  const { remove: removeList } = useSlaHolidayListChange();
  const [editing, setEditing] = useState<SlaHoliday | 'new'>();
  const [report, setReport] = useState<SlaHolidayImport>();
  const [importKey, setImportKey] = useState(() => crypto.randomUUID());
  const [copyKey, setCopyKey] = useState(() => crypto.randomUUID());

  const finished = (result: SlaHolidayImport) => {
    setReport(result);
    void message.success(t('sla.holidays.import_done', { count: result.created.length }));
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }} data-testid="sla-holidays">
      <Flex justify="space-between" wrap gap={8} align="center">
        <Typography.Title level={2} style={{ fontSize: 18, margin: 0 }}>
          <bdi>{list.name}</bdi>
        </Typography.Title>
        <Space wrap>
          <InputNumber
            aria-label={t('sla.holidays.year')}
            min={2000}
            max={2200}
            value={year}
            onChange={(value) => {
              if (value !== null) setYear(value);
            }}
            data-testid="sla-holidays-year"
          />
          {editable && (
            <>
              <Button
                icon={<PlusOutlined />}
                onClick={() => {
                  setEditing('new');
                }}
                data-testid="sla-holiday-add"
              >
                {t('sla.holidays.add')}
              </Button>
              <Upload
                accept=".ics,text/calendar"
                showUploadList={false}
                beforeUpload={(file) => {
                  change.importFile.mutate(
                    { file, key: importKey },
                    {
                      onSuccess: (result) => {
                        setImportKey(crypto.randomUUID());
                        finished(result);
                      },
                      onError: reportError,
                    },
                  );
                  return false;
                }}
              >
                <Button
                  icon={<UploadOutlined />}
                  loading={change.importFile.isPending}
                  data-testid="sla-holidays-import"
                >
                  {t('sla.holidays.import')}
                </Button>
              </Upload>
              <Button
                loading={change.copyYear.isPending}
                onClick={() => {
                  change.copyYear.mutate(
                    { year, key: copyKey },
                    {
                      onSuccess: (result) => {
                        setCopyKey(crypto.randomUUID());
                        finished(result);
                      },
                      onError: reportError,
                    },
                  );
                }}
                data-testid="sla-holidays-copy"
              >
                {t('sla.holidays.copy_year', { year, next: year + 1 })}
              </Button>
              <Popconfirm
                title={t('sla.holiday_lists.delete_confirm')}
                onConfirm={() => {
                  removeList.mutate(
                    { id: list.id, version: list.version },
                    { onSuccess: onDeleted, onError: reportError },
                  );
                }}
              >
                <Button danger icon={<DeleteOutlined />} data-testid="sla-holiday-list-delete">
                  {t('sla.holiday_lists.delete')}
                </Button>
              </Popconfirm>
            </>
          )}
        </Space>
      </Flex>
      {report !== undefined && report.skipped.length > 0 && (
        <Alert
          type="warning"
          showIcon
          closable
          onClose={() => {
            setReport(undefined);
          }}
          message={t('sla.holidays.import_skipped')}
          data-testid="sla-import-skipped"
          description={
            <ul style={{ margin: 0, paddingInlineStart: 18 }}>
              {report.skipped.map((s, i) => (
                <li key={i}>
                  {s.name !== null && <bdi>{s.name}</bdi>}
                  {s.name !== null && ': '}
                  {t(`sla_import_skip.${s.reason}`)}
                </li>
              ))}
            </ul>
          }
        />
      )}
      <Table<SlaHoliday>
        rowKey="id"
        loading={holidays.isPending}
        dataSource={holidays.data ?? []}
        pagination={false}
        scroll={{ x: 'max-content' }}
        locale={{ emptyText: t('sla.holidays.empty') }}
        data-testid="sla-holiday-table"
        onRow={(row) => ({
          onClick: () => {
            if (editable) setEditing(row);
          },
          style: editable ? { cursor: 'pointer' } : undefined,
          'data-testid': `sla-holiday-row-${row.id}`,
        })}
        columns={[
          {
            key: 'name',
            title: t('sla.holiday.field.name'),
            render: (_, row) => (
              <Flex gap={6} wrap align="center">
                <bdi>{row.name}</bdi>
                {row.needs_review && (
                  <ToneTag tone="warning">{t('sla.holiday.needs_review')}</ToneTag>
                )}
              </Flex>
            ),
          },
          {
            key: 'starts',
            title: t('sla.holiday.field.starts_on'),
            render: (_, row) => <bdi dir="ltr">{row.starts_on}</bdi>,
          },
          {
            key: 'ends',
            title: t('sla.holiday.field.ends_on'),
            render: (_, row) => <bdi dir="ltr">{row.ends_on}</bdi>,
          },
          {
            key: 'part',
            title: t('sla.holiday.field.part'),
            render: (_, row) => t(`sla_holiday_part.${row.part}`),
          },
          {
            key: 'origin',
            title: '',
            render: (_, row) => (
              <Typography.Text type="secondary">
                {t(`sla_holiday_origin.${row.origin}`)}
              </Typography.Text>
            ),
          },
        ]}
      />
      <HolidayEditor
        listId={list.id}
        row={editing === 'new' ? undefined : editing}
        open={editing !== undefined}
        onClose={() => {
          setEditing(undefined);
        }}
      />
    </Space>
  );
}

interface HolidayValues {
  name: string;
  starts_on: string | null;
  ends_on: string | null;
  part: SlaHolidayPart;
}

function HolidayEditor({
  listId,
  row,
  open,
  onClose,
}: {
  listId: string;
  row: SlaHoliday | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const { create, update, remove } = useSlaHolidayChange(listId);
  const [form] = Form.useForm<HolidayValues>();
  const problem = useFormProblem();
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [conflict, setConflict] = useState<unknown>();
  const [key] = useState(() => crypto.randomUUID());

  const failed = (error: unknown) => {
    if (error instanceof ApiError && error.isConflict && error.code === 'version_conflict') {
      setConflict(error);
      return;
    }
    if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
      markHandled(error);
      setProblems(fieldProblems(error, t));
      return;
    }
    problem.show(error);
  };
  const done = () => {
    void message.success(t('common.saved'));
    onClose();
  };
  const help = (name: string) =>
    problems[name] === undefined ? {} : { validateStatus: 'error' as const, help: problems[name] };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={480}
      destroyOnHidden
      title={row === undefined ? t('sla.holidays.add') : t('sla.holidays.edit')}
      data-testid="sla-holiday-editor"
    >
      <Form<HolidayValues>
        form={form}
        layout="vertical"
        initialValues={{
          name: row?.name ?? '',
          starts_on: row?.starts_on ?? null,
          ends_on: row?.ends_on ?? null,
          part: row?.part ?? 'full',
        }}
        onFinish={(values) => {
          setProblems({});
          problem.clear();
          const body = {
            name: values.name,
            starts_on: values.starts_on ?? '',
            ends_on: values.ends_on ?? values.starts_on ?? '',
            part: values.part,
          };
          if (row === undefined) {
            create.mutate({ body, key }, { onSuccess: done, onError: failed });
          } else {
            update.mutate(
              { id: row.id, version: row.version, body: { ...body, needs_review: false } },
              { onSuccess: done, onError: failed },
            );
          }
        }}
      >
        {row?.needs_review === true && (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 16 }}
            message={t('sla.holiday.needs_review')}
          />
        )}
        <Form.Item name="name" label={t('sla.holiday.field.name')} required {...help('name')}>
          <Input count={lengthLimit(200)} data-testid="sla-holiday-name" />
        </Form.Item>
        <Form.Item
          name="starts_on"
          label={t('sla.holiday.field.starts_on')}
          required
          {...help('starts_on')}
        >
          <DateFormField testId="sla-holiday-starts" />
        </Form.Item>
        <Form.Item name="ends_on" label={t('sla.holiday.field.ends_on')} {...help('ends_on')}>
          <DateFormField testId="sla-holiday-ends" />
        </Form.Item>
        <Form.Item name="part" label={t('sla.holiday.field.part')} {...help('part')}>
          <Select
            data-testid="sla-holiday-part"
            options={PARTS.map((p) => ({ value: p, label: t(`sla_holiday_part.${p}`) }))}
          />
        </Form.Item>
        <FormProblem problem={problem} />
        <Flex gap={8} wrap>
          <Button
            type="primary"
            htmlType="submit"
            loading={create.isPending || update.isPending}
            data-testid="sla-holiday-save"
          >
            {t('actions.save')}
          </Button>
          {row !== undefined && (
            <Button
              danger
              loading={remove.isPending}
              onClick={() => {
                remove.mutate(
                  { id: row.id, version: row.version },
                  { onSuccess: done, onError: failed },
                );
              }}
              data-testid="sla-holiday-remove"
            >
              {t('sla.holidays.remove')}
            </Button>
          )}
        </Flex>
      </Form>
      <ConflictDialog
        open={conflict !== undefined}
        error={conflict}
        fieldLabel={(field) => t(`sla.holiday.field.${field}`)}
        onReload={() => {
          setConflict(undefined);
          onClose();
        }}
        onKeepMine={() => {
          setConflict(undefined);
          onClose();
        }}
      />
    </Drawer>
  );
}

/** `DateField` as a Form control (value / onChange injected by Form.Item). */
function DateFormField({
  value = null,
  onChange,
  testId,
}: {
  value?: string | null;
  onChange?: (value: string | null) => void;
  testId: string;
}) {
  return (
    <DateField
      value={value}
      onChange={(day) => {
        onChange?.(day);
      }}
      testId={testId}
    />
  );
}
