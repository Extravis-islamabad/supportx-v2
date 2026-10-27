import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Input,
  Modal,
  Popconfirm,
  Result,
  Skeleton,
  Space,
  Tabs,
  Tooltip,
  Typography,
} from 'antd';
import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  ApiError,
  queryKeys,
  useAnnouncement,
  useAnnouncementAction,
  useDeleteAnnouncement,
  useSession,
  useUpdateAnnouncement,
  type Announcement,
  type AnnouncementAction,
} from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import { useRecordChannel, useTenantChannel, type PresenceMember } from '@supportx/realtime';
import {
  ConflictDialog,
  describeError,
  PresenceAvatars,
  reportError,
  useLabel,
  useRefetchAfter,
  WriteButton,
  lengthLimit,
} from '@supportx/ui';

import { AnnouncementFields } from './AnnouncementForm';
import { bodyOf, FIELDS, schema, valuesOf, type Field, type Values } from './form';
import { AnnouncementHistory } from './AnnouncementHistory';
import { SeverityTag, StatusTag, VisibilityTag } from './tags';

const REASON_ACTIONS = new Set<AnnouncementAction>(['unpublish', 'archive']);
const REASON_MAX = 500;

/** One announcement for staff: status actions, the edit form, its history. Live (WP-011). */
export function AnnouncementPage() {
  const t = useLabel();
  const { id } = useParams();
  const announcement = useAnnouncement(id);
  const queryClient = useQueryClient();
  // The clock: a scheduled start or an end changes what this page shows (WP-012).
  useRefetchAfter(
    announcement.data?.next_change_in_seconds,
    announcement.dataUpdatedAt,
    () => void announcement.refetch(),
  );
  // Who may publish changed (the four-eyes setting): the action buttons follow.
  useTenantChannel((message) => {
    if (message.type === 'announcements.settings_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.detail(id ?? '') });
    }
  });

  if (announcement.isError) {
    const error = announcement.error;
    const gone = error instanceof ApiError && error.status === 404;
    return (
      <Result
        status={gone ? '404' : 'warning'}
        title={gone ? t('errors.announcement_not_found') : describeError(error, t).title}
      />
    );
  }
  const item = announcement.data;
  if (item === undefined) return <Skeleton active />;
  if (item.kind !== 'staff') {
    // Not staff for this one: the audience view lives in the banners and the portal.
    return <Result status="404" title={t('errors.announcement_not_found')} />;
  }
  return (
    <AnnouncementDetail
      key={item.id}
      item={item}
      reload={async () => (await announcement.refetch()).data}
    />
  );
}

function AnnouncementDetail({
  item,
  reload,
}: {
  item: Announcement;
  reload: () => Promise<unknown>;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const others = useRef<PresenceMember[]>([]);
  const [changedBy, setChangedBy] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(editing);
  useEffect(() => {
    editingRef.current = editing;
  }, [editing]);

  const viewers = useRecordChannel('announcement', item.id, (event) => {
    if (event.type === 'refresh') {
      void reload();
      return;
    }
    const cached = queryClient.getQueryData<Announcement>(queryKeys.announcements.detail(item.id));
    if (event.version !== undefined && cached !== undefined && event.version <= cached.version) {
      return; // our own save, already shown
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.announcements.history(item.id) });
    if (!editingRef.current) {
      void reload(); // nothing of mine to lose: just show the latest
      return;
    }
    const by = others.current.find((v) => v.userId === event.by)?.name ?? t('live.someone');
    setChangedBy(by);
  });
  useEffect(() => {
    others.current = viewers;
  }, [viewers]);

  const remove = useDeleteAnnouncement(item.id);
  const canEdit = item.can_manage;
  const me = useSession().data?.user.id;

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%', maxWidth: 960 }}>
      <Flex justify="space-between" align="start" wrap gap={12}>
        <Space direction="vertical" size={4}>
          <Typography.Text type="secondary">{item.display_id}</Typography.Text>
          <Typography.Title level={1} style={{ margin: 0 }} data-testid="ann-heading">
            {item.title}
          </Typography.Title>
          <Space size={4} wrap>
            <StatusTag status={item.status} />
            {item.status === 'published' && <VisibilityTag visibility={item.visibility} />}
            <SeverityTag severity={item.severity} />
          </Space>
        </Space>
        <PresenceAvatars viewers={viewers} selfUserId={me ?? null} />
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
                setChangedBy(null);
                setEditing(false);
                void reload();
              }}
            >
              {t('live.reload')}
            </Button>
          }
        />
      )}
      <StatusActions item={item} />
      <Tabs
        items={[
          {
            key: 'details',
            label: t('announcements.tab.details'),
            children: editing ? (
              <EditForm
                item={item}
                reload={reload}
                onDone={() => {
                  setEditing(false);
                  setChangedBy(null);
                }}
              />
            ) : (
              <Card>
                <Typography.Paragraph
                  style={{ whiteSpace: 'pre-line' }}
                  data-testid="ann-body-view"
                >
                  {item.body}
                </Typography.Paragraph>
                <Typography.Text type="secondary">
                  {t(`announcement_audience.${item.audience}`)}
                  {item.show_as_banner ? ` · ${t('announcement.field.show_as_banner')}` : ''}
                </Typography.Text>
                <Window item={item} />
                <Flex gap={8} style={{ marginTop: 16 }}>
                  {canEdit && (
                    <WriteButton
                      onClick={() => {
                        setEditing(true);
                      }}
                      data-testid="ann-edit"
                    >
                      {t('actions.edit')}
                    </WriteButton>
                  )}
                  {canEdit && (
                    <Popconfirm
                      title={t('announcements.delete_confirm')}
                      okText={t('announcements.delete')}
                      cancelText={t('actions.cancel')}
                      onConfirm={() => {
                        remove.mutate(item.version, {
                          onSuccess: () => {
                            void message.success(t('announcements.deleted'));
                            void navigate('/announcements');
                          },
                          onError: reportError,
                        });
                      }}
                    >
                      <WriteButton danger loading={remove.isPending} data-testid="ann-delete">
                        {t('announcements.delete')}
                      </WriteButton>
                    </Popconfirm>
                  )}
                </Flex>
              </Card>
            ),
          },
          {
            key: 'history',
            label: t('announcements.tab.history', { count: item.history_count }),
            children: <AnnouncementHistory id={item.id} />,
          },
        ]}
      />
    </Space>
  );
}

function Window({ item }: { item: Announcement }) {
  const t = useLabel();
  if (item.publish_from === null && item.publish_until === null) return null;
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <Typography.Paragraph
      type="secondary"
      style={{ marginTop: 8, marginBottom: 0 }}
      data-testid="ann-window"
    >
      {item.publish_from !== null &&
        t('announcements.from', { time: format.format(new Date(item.publish_from)) })}{' '}
      {item.publish_until !== null &&
        t('announcements.until', { time: format.format(new Date(item.publish_until)) })}
    </Typography.Paragraph>
  );
}

/** Every action, always in the same order; the ones not possible now are disabled with why. */
function StatusActions({ item }: { item: Announcement }) {
  const t = useLabel();
  const { message } = App.useApp();
  const act = useAnnouncementAction(item.id);
  const [asking, setAsking] = useState<AnnouncementAction | null>(null);
  const [reason, setReason] = useState('');
  const run = (action: AnnouncementAction, why?: string) => {
    act.mutate(
      { action, version: item.version, reason: why },
      {
        onSuccess: () => {
          setAsking(null);
          setReason('');
          void message.success(t(`announcements.done.${action}`));
        },
        onError: reportError,
      },
    );
  };
  return (
    <Flex gap={8} wrap data-testid="ann-actions">
      {item.actions.map((state) => {
        const button = (
          <WriteButton
            key={state.action}
            type={state.action === 'publish' ? 'primary' : 'default'}
            disabled={!state.allowed}
            loading={act.isPending && act.variables.action === state.action}
            data-testid={`ann-action-${state.action}`}
            onClick={() => {
              if (REASON_ACTIONS.has(state.action)) setAsking(state.action);
              else run(state.action);
            }}
          >
            {t(`announcement_action.${state.action}`)}
          </WriteButton>
        );
        return state.allowed || state.reason == null ? (
          button
        ) : (
          <Tooltip key={state.action} title={t(`action_reason.${state.reason}`)}>
            <span data-testid={`ann-action-${state.action}-reason`} data-reason={state.reason}>
              {button}
            </span>
          </Tooltip>
        );
      })}
      <Modal
        open={asking !== null}
        title={asking === null ? '' : t(`announcement_action.${asking}`)}
        okText={asking === null ? '' : t(`announcement_action.${asking}`)}
        cancelText={t('actions.cancel')}
        confirmLoading={act.isPending}
        onOk={() => {
          if (asking !== null) run(asking, reason);
        }}
        onCancel={() => {
          setAsking(null);
          setReason('');
        }}
        destroyOnHidden
      >
        <label htmlFor="ann-reason">
          <Typography.Text>{t('announcements.reason')}</Typography.Text>
        </label>
        <Input.TextArea
          id="ann-reason"
          rows={3}
          count={lengthLimit(REASON_MAX, true)}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
          data-testid="ann-reason"
        />
      </Modal>
    </Flex>
  );
}

function EditForm({
  item,
  reload,
  onDone,
}: {
  item: Announcement;
  reload: () => Promise<unknown>;
  onDone: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateAnnouncement(item.id);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: valuesOf(item) });
  // The version these values are based on: sent as If-Match.
  const [baseVersion, setBaseVersion] = useState(item.version);
  const [conflict, setConflict] = useState<unknown>(null);
  const dirty = (): Field[] => FIELDS.filter((name) => form.getFieldState(name).isDirty);
  const save = (values: Values, version: number, fields: readonly Field[]) => {
    update.mutate(
      { changes: bodyOf(values, fields), version },
      {
        onSuccess: () => {
          void message.success(t('announcements.saved'));
          onDone();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) setConflict(error);
          else if (!applyServerErrors(error, form.setError, FIELDS)) reportError(error);
        },
      },
    );
  };
  return (
    <Card>
      <AnnouncementFields
        form={form}
        footer={
          <Space>
            <WriteButton
              type="primary"
              loading={update.isPending}
              data-testid="ann-save"
              onClick={() =>
                void form.handleSubmit((values) => {
                  save(values, baseVersion, dirty());
                })()
              }
            >
              {t('actions.save')}
            </WriteButton>
            <Button onClick={onDone}>{t('actions.cancel')}</Button>
          </Space>
        }
      />
      <ConflictDialog
        open={conflict !== null}
        error={conflict}
        fieldLabel={(field) => t(`announcement.field.${field}`)}
        onReload={() => {
          setConflict(null);
          void reload().then(onDone);
        }}
        onKeepMine={() => {
          setConflict(null);
          // My changed fields laid over the latest version; everything else is theirs.
          const fields = dirty();
          const mine = form.getValues();
          void reload().then((latest) => {
            const fresh = latest as Announcement | undefined;
            if (fresh === undefined) return;
            form.reset(valuesOf(fresh));
            for (const name of fields) form.setValue(name, mine[name], { shouldDirty: true });
            setBaseVersion(fresh.version);
            save(form.getValues(), fresh.version, fields);
          });
        }}
      />
    </Card>
  );
}
