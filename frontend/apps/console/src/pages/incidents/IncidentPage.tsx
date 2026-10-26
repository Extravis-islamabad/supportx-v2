import { EditOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Flex,
  Input,
  Popconfirm,
  Result,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tooltip,
  Typography,
} from 'antd';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  ApiError,
  queryKeys,
  useDeleteIncident,
  useIncident,
  useIncidentCatalogue,
  useIncidentCategories,
  useSession,
  useUnits,
  useUpdateIncident,
  type Incident,
  type IncidentActionState,
} from '@supportx/api-client';
import { useRecordChannel, type PresenceMember } from '@supportx/realtime';
import {
  ConflictDialog,
  describeError,
  PresenceAvatars,
  reportError,
  RichTextField,
  RichTextView,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

import { AssignDialog, TakeButton } from './assign';
import { OperationButton } from './operations';
import { IncidentConversation, type Typing } from './IncidentConversation';
import { lastTab, rememberTab } from './tabs';
import { TYPING_SHOWN_MS } from './typing';
import { FollowButton, FollowersCard } from './IncidentFollowers';
import { IncidentHistory } from './IncidentHistory';
import { categoryPath, personName } from './labels';
import { CategoryPicker, SitePicker, UserPicker } from './pickers';
import { SUBJECT_MAX } from './form';
import { StatusActions } from './StatusActions';
import { PriorityTag, SlaTag, StatusTag } from './tags';

const IMPACTS = ['one_person', 'team', 'department_or_site', 'organisation'] as const;
const URGENCIES = ['low', 'medium', 'high', 'critical'] as const;
const PRIORITIES = ['p1', 'p2', 'p3', 'p4'] as const;

/** One incident (REQ-INC-122): header, actions in a fixed order, fixed tabs, live (REQ-WI-005). */
export function IncidentPage() {
  const t = useLabel();
  const { id } = useParams();
  const incident = useIncident(id);
  if (incident.isError) {
    const error = incident.error;
    const gone = error instanceof ApiError && error.status === 404;
    return (
      <div data-testid="inc-not-found">
        <Result
          status={gone ? '404' : 'warning'}
          title={gone ? t('errors.work_item_not_found') : describeError(error, t).title}
        />
      </div>
    );
  }
  const item = incident.data;
  // Keyed by ID: while another incident loads, nothing of the previous one shows (REQ-INC-122).
  if (item === undefined || item.id !== id) {
    return (
      <div data-testid="inc-loading">
        <Skeleton active />
      </div>
    );
  }
  return (
    <IncidentDetail
      key={item.id}
      item={item}
      reload={async () => (await incident.refetch()).data}
    />
  );
}

function IncidentDetail({ item, reload }: { item: Incident; reload: () => Promise<unknown> }) {
  const t = useLabel();
  const dates = useDateTime();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const catalogue = useIncidentCatalogue();
  const groups = useUnits('groups');
  const others = useRef<PresenceMember[]>([]);
  const editing = useRef(0);
  const [changedBy, setChangedBy] = useState<string | null>(null);
  const behind = useRef(false); // a change arrived while someone here was editing
  const [assigning, setAssigning] = useState(false);
  const [typing, setTyping] = useState<Typing>({});
  const typingTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const me = useSession().data?.user.id ?? null;
  const [tab, setTab] = useState<string>(() => lastTab(me));
  const stopTyping = (userId: string) => {
    clearTimeout(typingTimers.current.get(userId));
    typingTimers.current.delete(userId);
    setTyping((current) =>
      Object.fromEntries(Object.entries(current).filter(([id]) => id !== userId)),
    );
  };
  useEffect(() => {
    const timers = typingTimers.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
    };
  }, []);
  const viewers = useRecordChannel('wi', item.id, (event) => {
    // Someone is writing (REQ-WI-006 AC2): shown until they stop, send, or go quiet.
    if (event.type === 'work_items.typing') {
      const by = event.by;
      if (by === undefined || by === me) return;
      if (event.fields?.[0] === 'stop') {
        stopTyping(by);
        return;
      }
      const name = others.current.find((v) => v.userId === by)?.name ?? t('live.someone');
      const kind = event.fields?.[1] === 'reply' ? 'reply' : 'note';
      setTyping((current) => ({ ...current, [by]: { name, kind } }));
      clearTimeout(typingTimers.current.get(by));
      typingTimers.current.set(
        by,
        setTimeout(() => {
          stopTyping(by);
        }, TYPING_SHOWN_MS),
      );
      return;
    }
    void queryClient.invalidateQueries({
      queryKey: [...queryKeys.incidents.all, 'history', item.id],
    });
    // A reply or note was added or changed visibility: refetch the timeline (and the record's
    // counts), never interrupting someone editing a field.
    if (event.type === 'work_items.conversation_changed') {
      if (event.by !== undefined) stopTyping(event.by);
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.conversation(item.id) });
      if (editing.current === 0) void reload();
      return;
    }
    if (event.type === 'work_items.followers_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.followers(item.id) });
      if (editing.current === 0) void reload();
      return;
    }
    if (event.type === 'refresh') {
      void reload();
      return;
    }
    const cached = queryClient.getQueryData<Incident>(queryKeys.incidents.detail(item.id));
    if (event.version !== undefined && cached !== undefined && event.version <= cached.version) {
      return; // our own save, already shown
    }
    if (editing.current === 0) {
      void reload();
      return;
    }
    behind.current = true;
    setChangedBy(others.current.find((v) => v.userId === event.by)?.name ?? t('live.someone'));
  });
  useEffect(() => {
    others.current = viewers;
  }, [viewers]);
  const remove = useDeleteIncident(item.id);
  const op = (name: string): IncidentActionState | undefined =>
    item.operations.find((o) => o.action === name);
  const deleteOp = op('delete');
  const groupName =
    item.group_id === null ? '' : (groups.data?.find((g) => g.id === item.group_id)?.name ?? '');

  return (
    // Full width: the record uses the whole screen (no fixed cap leaving the right side empty).
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Flex justify="space-between" align="start" wrap gap={12}>
        <Space direction="vertical" size={4}>
          <Typography.Text type="secondary" copyable data-testid="inc-display-id">
            {item.display_id}
          </Typography.Text>
          <Typography.Title level={1} style={{ margin: 0 }} data-testid="inc-heading">
            {/* What people typed reads in its own direction, whatever the UI's (QA BUG-12). */}
            <bdi dir="auto">{item.subject}</bdi>
          </Typography.Title>
          <Space size={4} wrap>
            <StatusTag status={item.status} catalogue={catalogue.data} />
            <PriorityTag priority={item.priority} source={item.priority_source} />
            <SlaTag
              policyId={item.sla_policy_id}
              dueAt={item.resolution_due_at}
              format={dates.format}
            />
          </Space>
          {(item.status_reason_code !== null || item.status_reason_text !== null) && (
            <Typography.Text type="secondary" data-testid="inc-status-reason">
              {t('incidents.status_reason')}:{' '}
              {item.status_reason_code === null
                ? ''
                : reasonLabel(t, catalogue.data, item.status_reason_code)}
              {item.status_reason_text === null ? (
                ''
              ) : (
                <>
                  {' — '}
                  <bdi dir="auto">{item.status_reason_text}</bdi>
                </>
              )}
            </Typography.Text>
          )}
          <Typography.Text type="secondary" data-testid="inc-people">
            {/* Names and the group are isolated, so a mixed Arabic and English line keeps
                "(group)" together in either reading direction (QA C6). */}
            {t('incidents.requested_by', { name: personName(item.people, item.requester_id) })}
            {' · '}
            {item.technician_id === null
              ? t('incidents.unassigned')
              : t('incidents.assigned_to', { name: personName(item.people, item.technician_id) })}
            {groupName === '' ? '' : ' '}
            {groupName === '' ? null : <bdi>({groupName})</bdi>}
          </Typography.Text>
        </Space>
        <Flex align="center" gap={12} wrap>
          <PresenceAvatars viewers={viewers} selfUserId={me} />
          <FollowButton item={item} me={me} />
        </Flex>
      </Flex>
      {changedBy !== null && (
        <Alert
          type="warning"
          showIcon
          role="status"
          data-testid="live-change-notice"
          message={t('live.changed_by', { name: changedBy })}
          action={
            <Button
              size="small"
              data-testid="live-change-reload"
              onClick={() => {
                behind.current = false;
                setChangedBy(null);
                void reload();
              }}
            >
              {t('live.reload')}
            </Button>
          }
        />
      )}
      <Flex gap={8} wrap align="center" data-testid="inc-operations">
        <OperationButton
          state={op('assign')}
          label={t('work_item_operation.assign')}
          testId="inc-op-assign"
          onClick={() => {
            setAssigning(true);
          }}
        />
        <TakeButton item={item} state={op('take')} />
        <StatusActions item={item} catalogue={catalogue.data} />
        <span style={{ flex: 1 }} />
        {deleteOp !== undefined && deleteOp.reason !== 'no_permission' && (
          <Popconfirm
            title={t('incidents.delete_confirm', { id: item.display_id })}
            okText={t('work_item_operation.delete')}
            okButtonProps={{ danger: true }}
            cancelText={t('actions.cancel')}
            onConfirm={() => {
              remove.mutate(item.version, {
                onSuccess: () => {
                  void message.success(t('incidents.deleted'));
                  void navigate('/incidents');
                },
                onError: reportError,
              });
            }}
          >
            <WriteButton
              danger
              disabled={!deleteOp.allowed}
              loading={remove.isPending}
              data-testid="inc-op-delete"
            >
              {t('work_item_operation.delete')}
            </WriteButton>
          </Popconfirm>
        )}
      </Flex>
      <AssignDialog
        item={item}
        open={assigning}
        refresh={reload}
        onClose={() => {
          setAssigning(false);
        }}
      />
      <Tabs
        data-testid="inc-tabs"
        // The tab this user used last, Conversation the first time (D-081).
        activeKey={tab}
        onChange={(key) => {
          setTab(key);
          rememberTab(me, key);
        }}
        items={[
          {
            key: 'conversation',
            label: t('incidents.tab.conversation', { count: item.conversation_count }),
            children: <IncidentConversation item={item} typing={typing} />,
          },
          {
            key: 'details',
            label: t('incidents.tab.details'),
            children: (
              <Details
                item={item}
                reload={reload}
                onEditing={(delta) => {
                  editing.current = Math.max(0, editing.current + delta);
                  // Nobody edits any more: catch up with what changed meanwhile (QA BUG-09).
                  if (editing.current === 0 && behind.current) {
                    behind.current = false;
                    setChangedBy(null);
                    void reload();
                  }
                }}
                me={me}
              />
            ),
          },
          {
            key: 'history',
            label: t('incidents.tab.history', { count: item.history_count }),
            children: <IncidentHistory id={item.id} />,
          },
        ]}
      />
    </Space>
  );
}

function reasonLabel(
  t: (key: string) => string,
  catalogue:
    | { reasons: { list: string; code: string; labels: Record<string, string> | null }[] }
    | undefined,
  code: string,
): string {
  const reason = catalogue?.reasons.find((r) => r.code === code);
  return reason === undefined ? t(code) : t(`reason.${reason.list}.${code}`);
}

/** Properties edited in place (REQ-INC-123) and the description (rich text). */
function Details({
  item,
  reload,
  onEditing,
  me,
}: {
  item: Incident;
  reload: () => Promise<unknown>;
  onEditing: (delta: number) => void;
  me: string | null;
}) {
  const t = useLabel();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const categories = useIncidentCategories();
  const sites = useUnits('sites');
  const canEdit = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const canPriority = item.operations.find((o) => o.action === 'change_priority')?.allowed === true;
  const person = (id: string | null) =>
    id === null
      ? null
      : { id, name: item.people[id]?.display_name ?? '', email: item.people[id]?.email ?? '' };
  const rows: { key: string; label: string; view: ReactNode; edit?: EditorSpec }[] = [
    {
      key: 'subject',
      label: t('work_item.field.subject'),
      view: <bdi dir="auto">{item.subject}</bdi>,
      edit: { kind: 'text', value: item.subject },
    },
    {
      key: 'requester_id',
      label: t('work_item.field.requester_id'),
      view: <Person item={item} id={item.requester_id} />,
      edit: {
        kind: 'user',
        value: item.requester_id,
        current: person(item.requester_id),
        required: true,
      },
    },
    {
      key: 'on_behalf_of_id',
      label: t('work_item.field.on_behalf_of_id'),
      view: <Person item={item} id={item.on_behalf_of_id} />,
      edit: { kind: 'user', value: item.on_behalf_of_id, current: person(item.on_behalf_of_id) },
    },
    {
      key: 'site_id',
      label: t('work_item.field.site_id'),
      view: sites.data?.find((s) => s.id === item.site_id)?.name ?? '',
      edit: { kind: 'site', value: item.site_id },
    },
    {
      key: 'category_id',
      label: t('work_item.field.category_id'),
      view: categoryPath(t, categories.data ?? [], item.category_id, locale),
      edit: { kind: 'category', value: item.category_id },
    },
    {
      key: 'impact',
      label: t('work_item.field.impact'),
      view: item.impact === null ? '' : t(`impact.${item.impact}`),
      edit: {
        kind: 'choice',
        value: item.impact,
        options: IMPACTS.map((v) => ({ value: v, label: t(`impact.${v}`) })),
      },
    },
    {
      key: 'urgency',
      label: t('work_item.field.urgency'),
      view: item.urgency === null ? '' : t(`urgency.${item.urgency}`),
      edit: {
        kind: 'choice',
        value: item.urgency,
        options: URGENCIES.map((v) => ({ value: v, label: t(`urgency.${v}`) })),
      },
    },
    {
      key: 'priority',
      label: t('work_item.field.priority'),
      view: <PriorityTag priority={item.priority} source={item.priority_source} />,
      edit: canPriority ? { kind: 'priority', value: item.priority } : undefined,
    },
    {
      key: 'channel',
      label: t('work_item.field.channel'),
      view: t(`work_item_channel.${item.channel}`),
    },
    {
      key: 'tags',
      label: t('work_item.field.tags'),
      view: item.tags.join(', '),
      edit: { kind: 'tags', value: item.tags },
    },
    {
      key: 'created_at',
      label: t('incidents.created_at'),
      view: dates.format(item.created_at),
    },
    {
      key: 'resolved_at',
      label: t('work_item.field.resolved_at'),
      view: dates.format(item.resolved_at),
    },
    {
      key: 'reopen_count',
      label: t('work_item.field.reopen_count'),
      view: String(item.reopen_count),
    },
  ];
  return (
    <Flex gap={16} wrap align="start">
      <Card style={{ flex: '2 1 420px', minWidth: 0 }} title={t('work_item.field.description')}>
        <Description item={item} canEdit={canEdit} reload={reload} onEditing={onEditing} />
      </Card>
      {/* Properties and followers share one column beside the description. */}
      <Flex vertical gap={16} style={{ flex: '1 1 340px', minWidth: 0 }}>
        <Card title={t('incidents.properties')}>
          <Descriptions column={1} size="small" data-testid="inc-properties">
            {rows.map((row) => (
              <Descriptions.Item key={row.key} label={row.label}>
                {row.edit !== undefined && canEdit ? (
                  <InlineEdit
                    item={item}
                    field={row.key}
                    label={row.label}
                    spec={row.edit}
                    reload={reload}
                    onEditing={onEditing}
                  >
                    {row.view}
                  </InlineEdit>
                ) : (
                  <span data-testid={`inc-prop-${row.key}`}>{row.view}</span>
                )}
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
        <FollowersCard item={item} me={me} />
      </Flex>
    </Flex>
  );
}

function Person({ item, id }: { item: Incident; id: string | null }) {
  if (id === null) return null;
  const found = item.people[id];
  if (found === undefined) return null;
  return (
    <Tooltip title={found.email}>
      <span>{found.display_name}</span>
    </Tooltip>
  );
}

type EditorSpec =
  | { kind: 'text'; value: string }
  | {
      kind: 'user';
      value: string | null;
      current: { id: string; name: string; email: string } | null;
      required?: boolean;
    }
  | { kind: 'site'; value: string | null }
  | { kind: 'category'; value: string | null }
  | { kind: 'choice'; value: string | null; options: { value: string; label: string }[] }
  | { kind: 'priority'; value: string }
  | { kind: 'tags'; value: string[] };

/** One property in place: view, pencil, then the control with save / cancel (and its errors). */
function InlineEdit({
  item,
  field,
  label,
  spec,
  reload,
  onEditing,
  children,
}: {
  item: Incident;
  field: string;
  label: string;
  spec: EditorSpec;
  reload: () => Promise<unknown>;
  onEditing: (delta: number) => void;
  children: ReactNode;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateIncident(item.id);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<unknown>(spec.value);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<unknown>(null);
  const close = () => {
    setOpen(false);
    setError(null);
    onEditing(-1);
  };
  const save = (version = item.version) => {
    const changes: Record<string, unknown> =
      spec.kind === 'priority'
        ? value === 'matrix'
          ? { priority: null }
          : { priority: value, priority_reason: reason }
        : { [field]: value };
    update.mutate(
      { changes: changes, version },
      {
        onSuccess: () => {
          void message.success(t('incidents.saved'));
          close();
        },
        onError: (failure) => {
          if (
            failure instanceof ApiError &&
            failure.isConflict &&
            failure.code === 'version_conflict'
          ) {
            setConflict(failure);
            return;
          }
          if (failure instanceof ApiError && failure.fieldErrors.length > 0) {
            setError(failure.fieldErrors.map((e) => t(e.message_key, e.params)).join(' '));
            return;
          }
          reportError(failure);
        },
      },
    );
  };
  if (!open) {
    return (
      <Flex gap={4} align="center" style={{ width: '100%' }}>
        <span data-testid={`inc-prop-${field}`} style={{ flex: 1 }}>
          {children}
        </span>
        <Button
          size="small"
          type="text"
          icon={<EditOutlined />}
          aria-label={t('incidents.edit_field', { field: label })}
          data-testid={`inc-edit-${field}`}
          onClick={() => {
            setValue(spec.kind === 'priority' ? spec.value : spec.value);
            setReason('');
            setOpen(true);
            onEditing(1);
          }}
        />
      </Flex>
    );
  }
  const control = (() => {
    const id = `inline-${field}`;
    switch (spec.kind) {
      case 'text':
        return (
          <Input
            id={id}
            aria-label={label}
            dir="auto"
            autoFocus
            value={typeof value === 'string' ? value : ''}
            maxLength={SUBJECT_MAX}
            showCount
            onChange={(event) => {
              setValue(event.target.value);
            }}
            onPressEnter={() => {
              save();
            }}
            data-testid={`inc-input-${field}`}
          />
        );
      case 'user':
        return (
          <UserPicker
            id={id}
            value={(value as string | null) ?? null}
            current={spec.current}
            onChange={setValue}
            testId={`inc-input-${field}`}
            ariaLabel={label}
          />
        );
      case 'site':
        return (
          <SitePicker
            id={id}
            value={(value as string | null) ?? null}
            onChange={setValue}
            testId={`inc-input-${field}`}
            ariaLabel={label}
          />
        );
      case 'category':
        return (
          <CategoryPicker
            id={id}
            value={(value as string | null) ?? null}
            onChange={setValue}
            testId={`inc-input-${field}`}
            ariaLabel={label}
          />
        );
      case 'choice':
        return (
          <Select
            id={id}
            allowClear
            aria-label={label}
            value={(value as string | null) ?? undefined}
            onChange={(next: string | undefined) => {
              setValue(next ?? null);
            }}
            options={spec.options}
            style={{ width: '100%' }}
            data-testid={`inc-input-${field}`}
          />
        );
      case 'priority':
        return (
          <Space direction="vertical" style={{ width: '100%' }}>
            <Select
              id={id}
              aria-label={label}
              value={value as string}
              onChange={setValue}
              options={[
                { value: 'matrix', label: t('incidents.priority_from_matrix') },
                ...PRIORITIES.map((p) => ({ value: p, label: t(`priority.${p}`) })),
              ]}
              style={{ width: '100%' }}
              data-testid="inc-input-priority"
            />
            {value !== 'matrix' && (
              <Input
                aria-label={t('work_item.field.priority_reason')}
                placeholder={t('work_item.field.priority_reason')}
                value={reason}
                maxLength={500}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
                data-testid="inc-input-priority-reason"
              />
            )}
          </Space>
        );
      case 'tags':
        return (
          <Select
            id={id}
            mode="tags"
            aria-label={label}
            value={value as string[]}
            onChange={setValue}
            tokenSeparators={[',']}
            style={{ width: '100%' }}
            data-testid={`inc-input-${field}`}
          />
        );
    }
  })();
  return (
    <Space
      direction="vertical"
      style={{ width: '100%' }}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !update.isPending) close(); // QA BUG-11
      }}
    >
      {control}
      {error !== null && (
        <Typography.Text type="danger" role="alert" data-testid={`inc-error-${field}`}>
          {error}
        </Typography.Text>
      )}
      <Space>
        <WriteButton
          size="small"
          type="primary"
          loading={update.isPending}
          onClick={() => {
            save();
          }}
          data-testid={`inc-save-${field}`}
        >
          {t('actions.save')}
        </WriteButton>
        <Button size="small" onClick={close}>
          {t('actions.cancel')}
        </Button>
      </Space>
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(name) => t(`work_item.field.${name}`)}
        onReload={() => {
          setConflict(null);
          void reload().then(close);
        }}
        onKeepMine={() => {
          // Keep mine = save mine on top of theirs, as the dialog says (QA BUG-09).
          setConflict(null);
          void reload().then((fresh) => {
            if (isIncident(fresh)) save(fresh.version);
          });
        }}
      />
    </Space>
  );
}

function isIncident(value: unknown): value is Incident {
  return typeof value === 'object' && value !== null && 'version' in value;
}

function Description({
  item,
  canEdit,
  reload,
  onEditing,
}: {
  item: Incident;
  canEdit: boolean;
  reload: () => Promise<unknown>;
  onEditing: (delta: number) => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateIncident(item.id);
  const [editing, setEditing] = useState(false);
  const [html, setHtml] = useState(item.description ?? '');
  const [conflict, setConflict] = useState<unknown>(null);
  const save = (version: number) => {
    update.mutate(
      { changes: { description: html }, version },
      {
        onSuccess: () => {
          void message.success(t('incidents.saved'));
          setEditing(false);
          onEditing(-1);
        },
        onError: (failure) => {
          if (failure instanceof ApiError && failure.code === 'version_conflict')
            setConflict(failure);
          else reportError(failure);
        },
      },
    );
  };
  if (!editing) {
    return (
      <Space direction="vertical" style={{ width: '100%' }}>
        {item.description === null ? (
          <Typography.Text type="secondary">{t('incidents.no_description')}</Typography.Text>
        ) : (
          <RichTextView html={item.description} testId="inc-description" />
        )}
        {canEdit && (
          <WriteButton
            size="small"
            icon={<EditOutlined />}
            data-testid="inc-edit-description"
            onClick={() => {
              setHtml(item.description ?? '');
              setEditing(true);
              onEditing(1);
            }}
          >
            {t('actions.edit')}
          </WriteButton>
        )}
      </Space>
    );
  }
  const done = () => {
    setEditing(false);
    onEditing(-1);
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <RichTextField
        label={t('work_item.field.description')}
        value={html}
        onChange={setHtml}
        testId="inc-description-editor"
      />
      <Space>
        <WriteButton
          type="primary"
          loading={update.isPending}
          data-testid="inc-save-description"
          onClick={() => {
            save(item.version);
          }}
        >
          {t('actions.save')}
        </WriteButton>
        <Button onClick={done}>{t('actions.cancel')}</Button>
      </Space>
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(name) => t(`work_item.field.${name}`)}
        onReload={() => {
          setConflict(null);
          void reload().then(done);
        }}
        onKeepMine={() => {
          setConflict(null);
          void reload().then((fresh) => {
            if (isIncident(fresh)) save(fresh.version);
          });
        }}
      />
    </Space>
  );
}
