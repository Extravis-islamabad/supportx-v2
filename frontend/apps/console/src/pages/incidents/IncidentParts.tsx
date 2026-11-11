import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  BulbOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Flex,
  Form,
  Input,
  InputNumber,
  List,
  Popconfirm,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  queryKeys,
  useIncidentLinks,
  useIncidentTasks,
  useIncidentWorklogs,
  useLinkChange,
  useSession,
  useTaskChange,
  useUsers,
  useWorklogChange,
  type Incident,
  type PartsBase,
  type IncidentTask,
  type TaskStatus,
  type WorklogType,
} from '@supportx/api-client';
import {
  DateTimeField,
  EmptyText,
  lengthLimit,
  reportError,
  SPACE,
  TimeZoneNote,
  ToneTag,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';
import { useRecordChannel } from '@supportx/realtime';

import { IncidentPicker } from './IncidentPicker';
import { UserPicker } from './pickers';

// Tasks, worklogs and links of an incident (WP-020e; REQ-INC-067, 072, 084). Each list follows
// the record's channel (`work_items.part_changed`), so two windows see the same thing live.

const TASK_STATUSES: readonly TaskStatus[] = ['open', 'in_progress', 'done', 'canceled'];
const WORKLOG_TYPES: readonly WorklogType[] = [
  'investigation',
  'fix',
  'communication',
  'travel',
  'other',
];

/** Display names of the people a list mentions (looked up once per list). */
/** After a save: empty a field only if it still holds what was sent, not what came since. */
function clearIfSent<T>(sent: T, empty: T): (current: T) => T {
  return (current) => (current === sent ? empty : current);
}

function usePeople(ids: (string | null | undefined)[]): Map<string, string> {
  const wanted = [...new Set(ids.filter((id): id is string => typeof id === 'string'))].sort();
  const users = useUsers(
    { filter: { field: 'id', op: 'in', value: wanted }, limit: 100 },
    wanted.length > 0,
  );
  return new Map(
    (users.data?.pages ?? []).flatMap((page) => page.items).map((u) => [u.id, u.display_name]),
  );
}

/** Minutes as hours and minutes, in words. */
function useDuration() {
  const t = useLabel();
  return (minutes: number) => {
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return hours > 0
      ? t('incidents.worklogs.hours_minutes', { hours, minutes: rest })
      : t('incidents.worklogs.minutes', { minutes: rest });
  };
}

// --- tasks ----------------------------------------------------------------------------------------

export function IncidentTasks({
  item,
  canEdit,
  base = 'incidents',
}: {
  item: Incident;
  canEdit: boolean;
  /** The record's type prefix: problems use the same parts (WP-044c). */
  base?: PartsBase;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const found = useIncidentTasks(item.id, true, base);
  const change = useTaskChange(item.id, base);
  const [title, setTitle] = useState('');
  const [owner, setOwner] = useState<string | null>(null);
  const [due, setDue] = useState<string | null>(null);
  const rows = found.data?.items ?? [];
  const people = usePeople(rows.flatMap((r) => [r.owner_id, r.done_by ?? null]));
  const add = () => {
    change.mutate(
      {
        kind: 'create',
        task: {
          title: title.trim(),
          owner_id: owner,
          due_at: due,
          status: 'open',
          priority: 'normal',
        },
      },
      {
        onSuccess: () => {
          // The next task may already be typed (a quick second add, or the e2e in CI).
          setTitle(clearIfSent(title, ''));
          setOwner(clearIfSent(owner, null));
          setDue(clearIfSent(due, null));
        },
        onError: reportError,
      },
    );
  };
  const setStatus = (task: IncidentTask, status: TaskStatus) => {
    change.mutate(
      { kind: 'update', taskId: task.id, version: task.version, task: { status } },
      { onError: reportError },
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text data-testid="inc-tasks-count" aria-live="polite">
        {t('incidents.tasks.count', { done: found.data?.done ?? 0, total: found.data?.total ?? 0 })}
      </Typography.Text>
      <List
        dataSource={rows}
        data-testid="inc-tasks"
        locale={{ emptyText: <EmptyText>{t('incidents.tasks.none')}</EmptyText> }}
        renderItem={(task, index) => (
          <List.Item
            data-testid={`inc-task-${String(index)}`}
            actions={
              canEdit
                ? [
                    <Button
                      key="up"
                      size="small"
                      type="text"
                      icon={<ArrowUpOutlined />}
                      disabled={index === 0}
                      aria-label={t('incidents.tasks.move_up', { title: task.title })}
                      onClick={() => {
                        change.mutate(
                          { kind: 'move', taskId: task.id, direction: 'up' },
                          { onError: reportError },
                        );
                      }}
                      data-testid={`inc-task-up-${String(index)}`}
                    />,
                    <Button
                      key="down"
                      size="small"
                      type="text"
                      icon={<ArrowDownOutlined />}
                      disabled={index === rows.length - 1}
                      aria-label={t('incidents.tasks.move_down', { title: task.title })}
                      onClick={() => {
                        change.mutate(
                          { kind: 'move', taskId: task.id, direction: 'down' },
                          { onError: reportError },
                        );
                      }}
                    />,
                    <Popconfirm
                      key="delete"
                      title={t('incidents.tasks.delete_confirm', { title: task.title })}
                      okText={t('incidents.tasks.delete')}
                      cancelText={t('incidents.tasks.cancel')}
                      onConfirm={() => {
                        change.mutate(
                          { kind: 'delete', taskId: task.id, version: task.version },
                          { onError: reportError },
                        );
                      }}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={t('incidents.tasks.delete_one', { title: task.title })}
                      />
                    </Popconfirm>,
                  ]
                : []
            }
          >
            <Flex gap={12} wrap align="center" style={{ width: '100%' }}>
              <Select<TaskStatus>
                size="small"
                aria-label={t('incidents.tasks.status_of', { title: task.title })}
                value={task.status}
                disabled={!canEdit}
                onChange={(status) => {
                  setStatus(task, status);
                }}
                options={TASK_STATUSES.map((s) => ({ value: s, label: t(`task_status.${s}`) }))}
                style={{ minWidth: 140 }}
                data-testid={`inc-task-status-${String(index)}`}
              />
              <bdi
                dir="auto"
                style={{
                  textDecoration: task.status === 'done' ? 'line-through' : undefined,
                  flex: '1 1 200px',
                }}
              >
                {task.title}
              </bdi>
              {task.stage != null && (
                // A change's task is for one stage, and holds the move out of it (REQ-CHG-094).
                <Tag data-testid={`inc-task-stage-${String(index)}`}>
                  {t(`work_item_stage.${task.stage}`)}
                </Tag>
              )}
              {task.owner_id !== null && (
                <Typography.Text type="secondary">
                  {people.get(task.owner_id) ?? t('incidents.unknown_value')}
                </Typography.Text>
              )}
              {task.status === 'done' && task.done_by != null && (
                // D-154d: who did it, never a guess from the history.
                <Typography.Text type="secondary" data-testid={`inc-task-done-by-${String(index)}`}>
                  {t('incidents.tasks.done_by', {
                    name: people.get(task.done_by) ?? t('incidents.unknown_value'),
                  })}
                </Typography.Text>
              )}
              {task.due_at !== null && (
                <Tag>{t('incidents.tasks.due', { at: dates.format(task.due_at) })}</Tag>
              )}
            </Flex>
          </List.Item>
        )}
      />
      {canEdit && (
        <Flex gap={8} wrap align="start">
          <Input
            aria-label={t('incidents.tasks.title')}
            placeholder={t('incidents.tasks.title')}
            value={title}
            count={lengthLimit(200)}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
            onPressEnter={() => {
              if (title.trim() !== '') add();
            }}
            style={{ flex: '1 1 240px' }}
            data-testid="inc-task-title"
          />
          <div style={{ minWidth: 220 }}>
            <UserPicker
              value={owner}
              onChange={setOwner}
              testId="inc-task-owner"
              ariaLabel={t('incidents.tasks.owner')}
            />
          </div>
          <DateTimeField value={due} onChange={setDue} testId="inc-task-due" />
          <WriteButton
            type="primary"
            disabled={title.trim() === ''}
            whyDisabled={t('why.task_title')}
            loading={change.isPending}
            onClick={add}
            data-testid="inc-task-add"
          >
            {t('incidents.tasks.add')}
          </WriteButton>
        </Flex>
      )}
    </Space>
  );
}

// --- worklogs -------------------------------------------------------------------------------------

export function IncidentWorklogs({
  item,
  canEdit,
  base = 'incidents',
}: {
  item: Incident;
  canEdit: boolean;
  base?: PartsBase;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const duration = useDuration();
  const me = useSession().data?.user.id ?? null;
  const found = useIncidentWorklogs(item.id, true, base);
  const change = useWorklogChange(item.id, base);
  const [type, setType] = useState<WorklogType>('fix');
  const [owner, setOwner] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const [end, setEnd] = useState<string | null>(null);
  const [minutes, setMinutes] = useState<number | null>(null);
  const [description, setDescription] = useState('');
  // The form opens on "Log time" and Cancel clears and closes it (template B, Haider 11-10).
  const [open, setOpen] = useState(false);
  const cancel = () => {
    setType('fix');
    setOwner(null);
    setStart(null);
    setEnd(null);
    setMinutes(null);
    setDescription('');
    setOpen(false);
  };
  const rows = found.data?.items ?? [];
  const people = usePeople([...rows.map((r) => r.owner_id), owner]);
  // The other way round (AC2): start + duration shows the end, start + end shows the duration.
  const filledEnd =
    start !== null && end === null && minutes !== null
      ? new Date(Date.parse(start) + minutes * 60_000).toISOString()
      : null;
  const filledMinutes =
    start !== null && end !== null && minutes === null
      ? Math.round((Date.parse(end) - Date.parse(start)) / 60_000)
      : null;
  const endBeforeStart = start !== null && end !== null && Date.parse(end) < Date.parse(start);
  const ready = start !== null && (end !== null || minutes !== null) && !endBeforeStart;
  // Why "Log time" is off, said next to it (D-147); an end before the start has its own alert.
  const why =
    start === null
      ? t('incidents.worklogs.why_start')
      : end === null && minutes === null
        ? t('incidents.worklogs.why_end')
        : null;
  const add = () => {
    change.mutate(
      {
        kind: 'create',
        worklog: {
          worklog_type: type,
          owner_id: owner,
          started_at: start,
          ended_at: end,
          minutes,
          description: description.trim() === '' ? null : description,
        },
      },
      {
        onSuccess: () => {
          setStart(clearIfSent(start, null));
          setEnd(clearIfSent(end, null));
          setMinutes(clearIfSent(minutes, null));
          setDescription(clearIfSent(description, ''));
        },
        onError: reportError,
      },
    );
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Descriptions
        size="small"
        column={1}
        data-testid="inc-worklog-totals"
        items={[
          {
            key: 'total',
            label: t('incidents.worklogs.total'),
            children: duration(found.data?.minutes ?? 0),
          },
          ...(found.data?.by_owner ?? []).map((row) => ({
            key: `owner-${row.key}`,
            label: people.get(row.key) ?? t('incidents.unknown_value'),
            children: duration(row.minutes),
          })),
          ...(found.data?.by_type ?? []).map((row) => ({
            key: `type-${row.key}`,
            label: t(`worklog_type.${row.key}`),
            children: duration(row.minutes),
          })),
        ]}
      />
      <List
        dataSource={rows}
        data-testid="inc-worklogs"
        locale={{ emptyText: <EmptyText>{t('incidents.worklogs.none')}</EmptyText> }}
        renderItem={(row) => (
          <List.Item
            actions={
              canEdit
                ? [
                    <Popconfirm
                      key="delete"
                      title={t('incidents.worklogs.delete_confirm')}
                      okText={t('incidents.worklogs.delete')}
                      cancelText={t('incidents.tasks.cancel')}
                      onConfirm={() => {
                        change.mutate(
                          { kind: 'delete', worklogId: row.id, version: row.version },
                          { onError: reportError },
                        );
                      }}
                    >
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        aria-label={t('incidents.worklogs.delete')}
                      />
                    </Popconfirm>,
                  ]
                : []
            }
          >
            <Space direction="vertical" size={0}>
              <Typography.Text>
                {t('incidents.worklogs.line', {
                  person: people.get(row.owner_id) ?? t('incidents.unknown_value'),
                  type: t(`worklog_type.${row.worklog_type}`),
                  duration: duration(row.minutes),
                })}
              </Typography.Text>
              <Typography.Text type="secondary">
                {t('incidents.worklogs.when', {
                  from: dates.format(row.started_at),
                  to: dates.format(row.ended_at),
                })}
              </Typography.Text>
              {row.description !== null && <bdi dir="auto">{row.description}</bdi>}
            </Space>
          </List.Item>
        )}
      />
      {canEdit && !open && (
        <Flex>
          <WriteButton
            onClick={() => {
              setOpen(true);
            }}
            data-testid="inc-worklog-open"
          >
            {t('incidents.worklogs.add')}
          </WriteButton>
        </Flex>
      )}
      {canEdit && open && (
        // Template B's form in a card (D-147): labels above the fields, the three time fields in
        // one row with one time-zone note, and the reason "Log time" is off said beside it; the
        // footer is Cancel, then the primary action.
        <Card size="small" data-testid="inc-worklog-form">
          <Form layout="vertical" component="div" requiredMark={false}>
            <div style={WORKLOG_GRID}>
              <Form.Item label={t('incidents.worklogs.type')} htmlFor="inc-worklog-type-field">
                <Select<WorklogType>
                  id="inc-worklog-type-field"
                  value={type}
                  onChange={setType}
                  options={WORKLOG_TYPES.map((w) => ({ value: w, label: t(`worklog_type.${w}`) }))}
                  style={{ width: '100%' }}
                  data-testid="inc-worklog-type"
                />
              </Form.Item>
              <Form.Item label={t('incidents.worklogs.owner')}>
                <UserPicker
                  value={owner ?? me}
                  onChange={setOwner}
                  testId="inc-worklog-owner"
                  ariaLabel={t('incidents.worklogs.owner')}
                />
              </Form.Item>
            </div>
            <div style={WORKLOG_GRID}>
              <Form.Item
                label={t('incidents.worklogs.start')}
                htmlFor="inc-worklog-start-field"
                style={{ marginBottom: SPACE.xxs }}
              >
                <DateTimeField
                  id="inc-worklog-start-field"
                  hideZone
                  value={start}
                  onChange={setStart}
                  testId="inc-worklog-start"
                />
              </Form.Item>
              <Form.Item
                label={t('incidents.worklogs.end')}
                htmlFor="inc-worklog-end-field"
                style={{ marginBottom: SPACE.xxs }}
              >
                <DateTimeField
                  id="inc-worklog-end-field"
                  hideZone
                  value={end ?? filledEnd}
                  onChange={(value) => {
                    setEnd(value);
                    if (value !== null) setMinutes(null);
                  }}
                  testId="inc-worklog-end"
                />
              </Form.Item>
              <Form.Item
                label={t('incidents.worklogs.duration')}
                htmlFor="inc-worklog-minutes-field"
                style={{ marginBottom: SPACE.xxs }}
              >
                <InputNumber
                  id="inc-worklog-minutes-field"
                  min={1}
                  max={10080}
                  value={minutes ?? filledMinutes}
                  onChange={(value) => {
                    setMinutes(value);
                    if (value !== null) setEnd(null);
                  }}
                  suffix={t('incidents.worklogs.minutes_unit')}
                  style={{ width: '100%' }}
                  data-testid="inc-worklog-minutes"
                />
              </Form.Item>
            </div>
            <div style={{ marginBottom: SPACE.sm }}>
              <TimeZoneNote />
            </div>
            {endBeforeStart && (
              <Alert
                type="error"
                showIcon
                role="alert"
                message={t('errors.field.end_before_start')}
                data-testid="inc-worklog-end-error"
                style={{ marginBottom: SPACE.sm }}
              />
            )}
            <Form.Item
              label={t('incidents.worklogs.description')}
              htmlFor="inc-worklog-description"
            >
              <Input.TextArea
                id="inc-worklog-description"
                value={description}
                count={lengthLimit(4000)}
                rows={2}
                onChange={(event) => {
                  setDescription(event.target.value);
                }}
              />
            </Form.Item>
            <Flex justify="flex-end" align="center" gap={SPACE.sm} wrap>
              {why !== null && (
                <Typography.Text
                  type="secondary"
                  style={{ fontSize: 12 }}
                  id="inc-worklog-why"
                  data-testid="inc-worklog-why"
                >
                  {why}
                </Typography.Text>
              )}
              <Button onClick={cancel} data-testid="inc-worklog-cancel">
                {t('actions.cancel')}
              </Button>
              <WriteButton
                type="primary"
                disabled={!ready}
                whyDisabled={why ?? undefined}
                loading={change.isPending}
                onClick={add}
                aria-describedby={why === null ? undefined : 'inc-worklog-why'}
                data-testid="inc-worklog-add"
              >
                {t('incidents.worklogs.add')}
              </WriteButton>
            </Flex>
          </Form>
        </Card>
      )}
    </Space>
  );
}

/**
 * Fields that share a row, each exactly as wide as a date and time field (D-147 template B), so
 * the two rows line up column by column (QA10V-24: Duration was wider than Start and End).
 */
const WORKLOG_GRID = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, 220px)',
  columnGap: SPACE.sm,
} as const;

// --- links ----------------------------------------------------------------------------------------

const OWN_ROUTE = new Set(['caused_by', 'causes', 'merged_into', 'merged_from']);

export function IncidentLinks({ item, canEdit }: { item: Incident; canEdit: boolean }) {
  const t = useLabel();
  const found = useIncidentLinks(item.id);
  const change = useLinkChange(item.id);
  // The causing problem's own changes (marked a known error, retired) show here at once.
  const queryClient = useQueryClient();
  const cause = (found.data ?? []).find((l) => l.relation === 'caused_by')?.other_id ?? undefined;
  useRecordChannel('wi', cause, () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.links(item.id) });
  });
  const [other, setOther] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const rows = found.data ?? [];
  const requester = item.people[item.requester_id];

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {rows.length === 0 ? (
        <EmptyText>{t('incidents.links.none')}</EmptyText>
      ) : (
        <List
          dataSource={rows}
          data-testid="inc-links"
          renderItem={(link) => (
            <List.Item
              data-testid={`inc-link-${link.other_display_id ?? 'hidden'}`}
              actions={
                // A cause or a merge is undone in its own place (unlink, undo the merge): the
                // generic delete would be refused (QA10-P1-03), so it is not offered.
                canEdit && !OWN_ROUTE.has(link.relation)
                  ? [
                      <Popconfirm
                        key="delete"
                        title={t('incidents.links.delete_confirm')}
                        okText={t('incidents.links.delete')}
                        cancelText={t('incidents.tasks.cancel')}
                        onConfirm={() => {
                          change.mutate(
                            { kind: 'delete', linkId: link.id, version: link.version },
                            { onError: reportError },
                          );
                        }}
                      >
                        <Button
                          size="small"
                          type="text"
                          danger
                          icon={<DeleteOutlined />}
                          aria-label={t('incidents.links.delete')}
                          data-testid={`inc-link-delete-${link.other_display_id ?? 'hidden'}`}
                        />
                      </Popconfirm>,
                    ]
                  : []
              }
            >
              <Space direction="vertical" size={0}>
                <Space wrap>
                  <Tag>{t(`link_relation.${link.relation}`)}</Tag>
                  {link.other_id === null ? (
                    // REQ-INC-084 AC3: the link exists; the other record stays private.
                    <Typography.Text type="secondary">
                      {t('incidents.links.hidden')}
                    </Typography.Text>
                  ) : (
                    <Link
                      to={`/${link.other_type === 'problem' ? 'problems' : 'incidents'}/${link.other_id}`}
                    >
                      {link.other_display_id} · <bdi dir="auto">{link.other_subject}</bdi>
                    </Link>
                  )}
                  {link.other_known_error && (
                    // REQ-PRB-036 AC3: the incident's problem is a known error, shown live.
                    <ToneTag tone="warning" icon={<BulbOutlined />} testId="inc-known-error">
                      {t('problems.known_error.tag')}
                    </ToneTag>
                  )}
                </Space>
                {link.comment !== null && (
                  <Typography.Text type="secondary">
                    <bdi dir="auto">{link.comment}</bdi>
                  </Typography.Text>
                )}
              </Space>
            </List.Item>
          )}
        />
      )}
      {canEdit && (
        <Flex gap={8} wrap align="start" data-testid="inc-link-form">
          <div style={{ flex: '1 1 280px' }}>
            <IncidentPicker
              value={other}
              onChange={(id) => {
                setOther(id);
              }}
              from={{
                id: item.id,
                requesterId: item.requester_id,
                requesterName: requester?.display_name ?? '',
              }}
              testId="inc-link-other"
              ariaLabel={t('incidents.links.other')}
            />
          </div>
          <Input
            aria-label={t('incidents.links.comment')}
            placeholder={t('incidents.links.comment')}
            value={comment}
            count={lengthLimit(500)}
            onChange={(event) => {
              setComment(event.target.value);
            }}
            style={{ flex: '1 1 200px' }}
            data-testid="inc-link-comment"
          />
          <WriteButton
            type="primary"
            disabled={other === null}
            whyDisabled={t('why.choose_record')}
            loading={change.isPending}
            onClick={() => {
              if (other === null) return;
              change.mutate(
                { kind: 'create', otherId: other, comment: comment.trim() === '' ? null : comment },
                {
                  onSuccess: () => {
                    setOther(null);
                    setComment('');
                  },
                  onError: reportError,
                },
              );
            }}
            data-testid="inc-link-add"
          >
            {t('incidents.links.add')}
          </WriteButton>
        </Flex>
      )}
    </Space>
  );
}
