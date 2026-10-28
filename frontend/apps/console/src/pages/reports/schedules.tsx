import { CalendarOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App as AntApp,
  Button,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Tag,
  TimePicker,
  Tooltip,
  Typography,
} from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useMemo, useState } from 'react';

import {
  queryKeys,
  useReportSchedules,
  useScheduleChange,
  useStructure,
  useUsers,
  type ReportSchedule,
  type ReportScheduleInput,
} from '@supportx/api-client';
import { useIsolate, useLabels } from '@supportx/labels';
import { refreshList, usePersonalChannel } from '@supportx/realtime';
import {
  describeError,
  lengthLimit,
  ToneTag,
  type Tone,
  useAccess,
  useDateTime,
  useTimeZone,
  WriteButton,
} from '@supportx/ui';

type Frequency = ReportScheduleInput['frequency'];
type Format = NonNullable<ReportScheduleInput['format']>;

const FREQUENCIES: Frequency[] = ['weekly', 'daily', 'monthly'];
const WEEKDAYS = [6, 0, 1, 2, 3, 4, 5]; // shown from Sunday; stored 0 = Monday
const FORMATS: Format[] = ['xlsx', 'csv', 'pdf'];
const STATUS_TONE: Record<ReportSchedule['status'], Tone> = {
  active: 'success',
  paused: 'warning',
  finished: 'default',
};

function PeopleSelect({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const t = useLabels();
  const [search, setSearch] = useState('');
  const users = useUsers({ q: search, sort: 'display_name', limit: 20 });
  const options = (users.data?.pages ?? [])
    .flatMap((p) => p.items)
    .filter((u) => u.status !== 'disabled')
    .map((u) => ({ value: u.id, label: `${u.display_name} · ${u.email ?? ''}` }));
  return (
    <Select
      mode="multiple"
      showSearch
      filterOption={false}
      onSearch={setSearch}
      value={value}
      onChange={onChange}
      options={options}
      loading={users.isFetching}
      aria-label={t('reports.schedule_people')}
      notFoundContent={t('incidents.nobody_found')}
      data-testid="schedule-people"
    />
  );
}

function GroupsSelect({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const t = useLabels();
  const groups = useStructure('groups', true, true);
  return (
    <Select
      mode="multiple"
      optionFilterProp="label"
      value={value}
      onChange={onChange}
      options={(groups.data ?? [])
        .filter((g) => !g.disabled)
        .map((g) => ({ value: g.id, label: g.name }))}
      aria-label={t('reports.schedule_groups')}
      data-testid="schedule-groups"
    />
  );
}

/** "Schedule" on a built-in or saved report: when, to whom, which file (REQ-RPT-052). */
export function ScheduleButton({
  reportRef,
  title,
  changed,
}: {
  reportRef: string;
  title: string;
  /** The report on screen differs from what is saved: schedules send what is saved. */
  changed: boolean;
}) {
  const t = useLabels();
  const { can } = useAccess();
  const { message } = AntApp.useApp();
  const zone = useTimeZone();
  const schedules = useReportSchedules(can('reports.schedule'));
  const change = useScheduleChange();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [frequency, setFrequency] = useState<Frequency>('weekly');
  const [weekdays, setWeekdays] = useState<number[]>([0]);
  const [dayOfMonth, setDayOfMonth] = useState<number>(1);
  const [at, setAt] = useState<Dayjs>(dayjs().hour(7).minute(0));
  const [start, setStart] = useState<Dayjs>(dayjs());
  const [end, setEnd] = useState<Dayjs | null>(null);
  const [people, setPeople] = useState<string[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [format, setFormat] = useState<Format>('xlsx');
  const [note, setNote] = useState('');
  if (!can('reports.schedule')) return null;
  const mailReady = schedules.data?.mail_configured ?? true;
  const whyNot = !mailReady
    ? t('reports.mail_not_set_up')
    : changed
      ? t('reports.schedule_save_first')
      : undefined;

  const submit = () => {
    change.mutate(
      {
        kind: 'create',
        key,
        body: {
          title,
          report_ref: reportRef,
          frequency,
          at_time: at.format('HH:mm'),
          time_zone: zone,
          start_date: start.format('YYYY-MM-DD'),
          end_date: end ? end.format('YYYY-MM-DD') : null,
          weekdays: frequency === 'monthly' ? [] : weekdays,
          day_of_month: frequency === 'monthly' ? dayOfMonth : null,
          recipient_users: people,
          recipient_groups: groups,
          format,
          content: 'summary',
          message: note.trim() || null,
        },
      },
      {
        onSuccess: () => {
          setOpen(false);
          setKey(crypto.randomUUID());
          void message.success(t('reports.save'));
        },
      },
    );
  };

  return (
    <>
      <Tooltip title={whyNot}>
        <Button
          icon={<CalendarOutlined />}
          disabled={whyNot !== undefined}
          onClick={() => {
            setOpen(true);
          }}
          data-testid="report-schedule"
        >
          {t('reports.schedule')}
        </Button>
      </Tooltip>
      <Modal
        open={open}
        title={t('reports.schedule_title')}
        okText={t('reports.save')}
        cancelText={t('reports.cancel')}
        okButtonProps={{
          disabled: people.length === 0 && groups.length === 0,
          loading: change.isPending,
        }}
        onCancel={() => {
          setOpen(false);
        }}
        onOk={submit}
        width={560}
      >
        <Form layout="vertical">
          <Form.Item label={t('reports.schedule_frequency')}>
            <Radio.Group
              value={frequency}
              onChange={(event) => {
                const next = event.target.value as Frequency;
                setFrequency(next);
                if (next === 'weekly') setWeekdays([weekdays[0] ?? 0]);
              }}
              options={FREQUENCIES.map((f) => ({ value: f, label: t(`report_frequency.${f}`) }))}
              data-testid="schedule-frequency"
            />
          </Form.Item>
          {frequency !== 'monthly' && (
            <Form.Item label={t('reports.schedule_days')}>
              <Select
                mode={frequency === 'daily' ? 'multiple' : undefined}
                value={frequency === 'daily' ? weekdays : weekdays[0]}
                onChange={(next: number | number[]) => {
                  setWeekdays(Array.isArray(next) ? next : [next]);
                }}
                options={WEEKDAYS.map((d) => ({ value: d, label: t(`weekday.${String(d)}`) }))}
                aria-label={t('reports.schedule_days')}
                data-testid="schedule-days"
              />
            </Form.Item>
          )}
          {frequency === 'monthly' && (
            <Form.Item label={t('reports.schedule_day_of_month')}>
              <InputNumber
                min={1}
                max={28}
                value={dayOfMonth}
                onChange={(n) => {
                  setDayOfMonth(n ?? 1);
                }}
              />
            </Form.Item>
          )}
          <Space wrap>
            <Form.Item label={t('reports.schedule_time')}>
              <TimePicker
                format="HH:mm"
                minuteStep={5}
                value={at}
                allowClear={false}
                onChange={(value) => {
                  setAt(value);
                }}
              />
            </Form.Item>
            <Form.Item label={t('reports.schedule_zone')}>
              <Typography.Text>{zone}</Typography.Text>
            </Form.Item>
          </Space>
          <Space wrap>
            <Form.Item label={t('reports.schedule_start')}>
              <DatePicker
                value={start}
                allowClear={false}
                onChange={(value) => {
                  setStart(value);
                }}
              />
            </Form.Item>
            <Form.Item label={t('reports.schedule_end')}>
              <DatePicker value={end} onChange={setEnd} />
            </Form.Item>
          </Space>
          <Alert type="info" showIcon message={t('reports.schedule_recipients_hint')} />
          <Form.Item label={t('reports.schedule_people')} style={{ marginTop: 12 }}>
            <PeopleSelect value={people} onChange={setPeople} />
          </Form.Item>
          <Form.Item label={t('reports.schedule_groups')}>
            <GroupsSelect value={groups} onChange={setGroups} />
          </Form.Item>
          <Form.Item label={t('reports.export_format')}>
            <Radio.Group
              value={format}
              onChange={(event) => {
                setFormat(event.target.value as Format);
              }}
              options={FORMATS.map((f) => ({ value: f, label: t(`report_export_format.${f}`) }))}
            />
          </Form.Item>
          <Form.Item label={t('reports.schedule_message')}>
            <Input.TextArea
              value={note}
              onChange={(event) => {
                setNote(event.target.value);
              }}
              count={lengthLimit(2000)}
              autoSize={{ minRows: 2, maxRows: 5 }}
            />
          </Form.Item>
          {change.error && (
            <Typography.Text type="danger" role="alert">
              {describeError(change.error, t).title}
            </Typography.Text>
          )}
        </Form>
      </Modal>
    </>
  );
}

/** "Schedules": next run, last result, pause, resume, delete. Live (REQ-RPT-052 AC2, 056). */
export function SchedulesButton() {
  const t = useLabels();
  const isolate = useIsolate();
  const { can } = useAccess();
  const dates = useDateTime();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const schedules = useReportSchedules(open);
  const change = useScheduleChange();
  usePersonalChannel((message) => {
    if (message.type === 'reports.schedules_changed') {
      refreshList(queryClient, queryKeys.reports.schedules);
    }
  });
  const items = useMemo(() => schedules.data?.items ?? [], [schedules.data]);
  if (!can('reports.schedule')) return null;

  return (
    <>
      <Button
        icon={<CalendarOutlined />}
        onClick={() => {
          setOpen(true);
        }}
        data-testid="report-schedules"
      >
        {t('reports.schedules')}
      </Button>
      <Drawer
        open={open}
        title={t('reports.schedules')}
        onClose={() => {
          setOpen(false);
        }}
        width={520}
      >
        {schedules.data && !schedules.data.mail_configured && (
          <Alert type="warning" showIcon message={t('reports.mail_not_set_up')} />
        )}
        <List
          loading={schedules.isPending}
          dataSource={items}
          locale={{ emptyText: t('reports.no_schedules') }}
          renderItem={(item) => (
            <List.Item
              actions={[
                item.status === 'active' ? (
                  <WriteButton
                    key="pause"
                    size="small"
                    onClick={() => {
                      change.mutate({ kind: 'pause', id: item.id, version: item.version });
                    }}
                    data-testid={`schedule-pause-${item.id}`}
                  >
                    {t('reports.pause')}
                  </WriteButton>
                ) : (
                  <WriteButton
                    key="resume"
                    size="small"
                    onClick={() => {
                      change.mutate({ kind: 'resume', id: item.id, version: item.version });
                    }}
                    data-testid={`schedule-resume-${item.id}`}
                  >
                    {t('reports.resume')}
                  </WriteButton>
                ),
                <Popconfirm
                  key="delete"
                  title={t('reports.delete_confirm', { name: isolate(item.title) })}
                  okText={t('reports.delete')}
                  cancelText={t('reports.cancel')}
                  onConfirm={() => {
                    change.mutate({ kind: 'delete', id: item.id, version: item.version });
                  }}
                >
                  <WriteButton size="small" danger data-testid={`schedule-delete-${item.id}`}>
                    {t('reports.delete')}
                  </WriteButton>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <span>{item.title}</span>
                    <Tag>{t(`report_frequency.${item.frequency}`)}</Tag>
                    <ToneTag tone={STATUS_TONE[item.status]} testId={`schedule-status-${item.id}`}>
                      {t(`report_schedule_status.${item.status}`)}
                    </ToneTag>
                  </Space>
                }
                description={
                  <Space direction="vertical" size={0}>
                    {item.next_run_at && item.status === 'active' && (
                      <span>
                        {t('reports.next_run', { time: isolate(dates.format(item.next_run_at)) })}
                      </span>
                    )}
                    {item.last_run_at && item.last_result && (
                      <span data-testid={`schedule-last-${item.id}`}>
                        {t('reports.last_run', {
                          time: isolate(dates.format(item.last_run_at)),
                          result: t(`report_schedule_result.${item.last_result}`),
                        })}
                      </span>
                    )}
                    {item.paused_reason !== null && (
                      <Typography.Text type="warning">
                        {t(`report_schedule_result.${item.paused_reason}`)}
                      </Typography.Text>
                    )}
                  </Space>
                }
              />
            </List.Item>
          )}
        />
        {change.error && (
          <Typography.Text type="danger" role="alert">
            {describeError(change.error, t).title}
          </Typography.Text>
        )}
      </Drawer>
    </>
  );
}
