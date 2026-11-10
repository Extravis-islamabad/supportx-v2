import { NotificationOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  Alert,
  App,
  Button,
  Flex,
  Input,
  Modal,
  Popconfirm,
  Result,
  Skeleton,
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
  useUnits,
  useUpdateAnnouncement,
  type Announcement,
  type AnnouncementAction,
} from '@supportx/api-client';
import { applyServerErrors, useForm, zodResolver } from '@supportx/forms';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel, useTenantChannel, type PresenceMember } from '@supportx/realtime';
import {
  useConflictRetry,
  ConflictDialog,
  FormFooter,
  PropertiesPanel,
  PropertyList,
  RecordHeader,
  RecordPage,
  describeError,
  FormProblem,
  PresenceAvatars,
  reportError,
  useConflict,
  useFormProblem,
  useLabel,
  useAccess,
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
  // Changed by someone after it was shown (409): the shared dialog (QA WP-029 BUG-05).
  const removeConflict = useConflictRetry();
  const removeIt = (version: number) => {
    remove.mutate(version, {
      onSuccess: () => {
        void message.success(t('announcements.deleted'));
        void navigate('/announcements');
      },
      onError: (error) => {
        if (!removeConflict.take(error, removeIt)) reportError(error);
      },
    });
  };
  const canEdit = item.can_manage;
  const me = useSession().data?.user.id;

  // Template A (D-147): the header and every action in one card, the live notice, the tabs, and
  // the audience and publishing window in the properties panel.
  return (
    <>
      <RecordPage
        testId="ann-record"
        header={
          <RecordHeader
            icon={<NotificationOutlined />}
            kind="announcement"
            typeLabel={t('announcements.one')}
            displayId={item.display_id}
            title={item.title}
            testIds={{ title: 'ann-heading' }}
            tags={
              <>
                <StatusTag status={item.status} />
                {item.status === 'published' && <VisibilityTag visibility={item.visibility} />}
                <SeverityTag severity={item.severity} />
              </>
            }
            extra={<PresenceAvatars viewers={viewers} selfUserId={me ?? null} />}
          />
        }
        actions={
          <Flex gap={8} wrap justify="end">
            <StatusActions item={item} />
            {canEdit && !editing && (
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
                  removeIt(item.version);
                }}
              >
                <WriteButton danger loading={remove.isPending} data-testid="ann-delete">
                  {t('announcements.delete')}
                </WriteButton>
              </Popconfirm>
            )}
          </Flex>
        }
        alerts={
          changedBy !== null && (
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
          )
        }
        panel={
          <PropertiesPanel
            testId="ann-panel"
            sections={[
              {
                key: 'properties',
                title: t('layout.properties'),
                children: (
                  <PropertyList
                    items={[
                      {
                        key: 'audience',
                        label: t('announcement.field.audience'),
                        content: <Audience item={item} />,
                        filled: true,
                      },
                      {
                        key: 'banner',
                        label: t('announcement.field.show_as_banner'),
                        content: t(item.show_as_banner ? 'history.yes' : 'history.no'),
                        filled: true,
                      },
                      {
                        key: 'window',
                        label: t('announcements.window'),
                        content: <Window item={item} />,
                        filled: item.publish_from !== null || item.publish_until !== null,
                      },
                    ]}
                  />
                ),
              },
            ]}
          />
        }
      >
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
                <Typography.Paragraph
                  // The message reads in its own direction (QA10-P4-36: an English message in
                  // the Arabic screen kept its full stop at the end).
                  dir="auto"
                  style={{ whiteSpace: 'pre-line', padding: '8px 4px' }}
                  data-testid="ann-body-view"
                >
                  {item.body}
                </Typography.Paragraph>
              ),
            },
            {
              key: 'history',
              label: t('announcements.tab.history', { count: item.history_count }),
              children: <AnnouncementHistory id={item.id} />,
            },
          ]}
        />
      </RecordPage>
      <ConflictDialog
        {...removeConflict.dialog}
        fieldLabel={(field) => t(`announcement.field.${field}`)}
      />
    </>
  );
}

/** The audience, naming the chosen sites or groups (QA10-P4-13: "Selected support groups" alone). */
function Audience({ item }: { item: Announcement }) {
  const t = useLabel();
  const list = useListFormat();
  const { can } = useAccess();
  const kind = item.audience === 'sites' ? 'sites' : 'groups';
  const ids = item.audience === 'sites' ? item.site_ids : item.group_ids;
  const units = useUnits(
    kind,
    (item.audience === 'sites' || item.audience === 'groups') && can(`${kind}.view`),
  );
  const named = new Map((units.data ?? []).map((unit) => [unit.id, unit.name]));
  const names = ids.map((id) => named.get(id)).filter((name) => name !== undefined);
  return (
    <span data-testid="ann-audience">
      {t(`announcement_audience.${item.audience}`)}
      {names.length > 0 && `: ${list(names, 'conjunction')}`}
    </span>
  );
}

function Window({ item }: { item: Announcement }) {
  const t = useLabel();
  if (item.publish_from === null && item.publish_until === null) return null;
  const format = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <Typography.Paragraph type="secondary" style={{ margin: 0 }} data-testid="ann-window">
      {item.publish_from !== null &&
        t('announcements.from', { time: format.format(new Date(item.publish_from)) })}{' '}
      {item.publish_until !== null &&
        t('announcements.until', { time: format.format(new Date(item.publish_until)) })}
    </Typography.Paragraph>
  );
}

// What a person sees of an announcement, for the conflict dialog (QA WP-029 BUG-05).
const VIEWED = [
  'title',
  'body',
  'severity',
  'audience',
  'site_ids',
  'group_ids',
  'show_as_banner',
  'publish_from',
  'publish_until',
  'owner_id',
  'status',
] as const;
const announcementView = (item: Announcement | undefined) =>
  item && Object.fromEntries(VIEWED.map((field) => [field, item[field]]));

/** Every action, always in the same order; the ones not possible now are disabled with why. */
function StatusActions({ item }: { item: Announcement }) {
  const t = useLabel();
  const { message } = App.useApp();
  const act = useAnnouncementAction(item.id);
  const [asking, setAsking] = useState<AnnouncementAction | null>(null);
  const [reason, setReason] = useState('');
  // With the reason dialog open, its refusal is shown there (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // Moved or changed by someone after it was shown (409): the shared dialog (BUG-05).
  const conflict = useConflict();
  const [tried, setTried] = useState<{
    action: AnnouncementAction;
    why?: string;
    opened: Announcement;
  }>();
  const run = (action: AnnouncementAction, why?: string, version = item.version) => {
    problem.clear();
    act.mutate(
      { action, version, reason: why },
      {
        onSuccess: () => {
          setAsking(null);
          setReason('');
          void message.success(t(`announcements.done.${action}`));
        },
        onError: (error) => {
          if (conflict.take(error)) setTried({ action, why, opened: item });
          else if (asking !== null) problem.show(error);
          else reportError(error);
        },
      },
    );
  };
  return (
    <Flex gap={8} wrap data-testid="ann-actions">
      {/* Only the moves its status allows (template A); a greyed one says why, such as who
          may publish (QA10-P4-13). */}
      {item.actions
        .filter((state) => state.allowed || state.reason !== 'not_from_status')
        .map((state) => {
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
          problem.clear();
        }}
        destroyOnHidden
      >
        <FormProblem problem={problem} />
        <label htmlFor="ann-reason">
          <Typography.Text>{t('announcements.reason')}</Typography.Text>
        </label>
        <Input.TextArea
          id="ann-reason"
          rows={3}
          count={lengthLimit(REASON_MAX, true)}
          // Room for the "0 / 500" counter under the box, above the dialog's buttons (QA10-P4-18).
          style={{ marginBottom: 24 }}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
          data-testid="ann-reason"
        />
      </Modal>
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => t(`announcement.field.${field}`)}
        opened={announcementView(tried?.opened)}
        latest={announcementView(item)}
        onReload={() => {
          conflict.clear();
          setTried(undefined);
          setAsking(null);
          setReason('');
        }}
        onKeepMine={() => {
          conflict.clear();
          if (tried !== undefined) {
            run(tried.action, tried.why, conflict.latestVersion ?? item.version);
          }
          setTried(undefined);
        }}
      />
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
  // A refusal with no field to point at is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const dirty = (): Field[] => FIELDS.filter((name) => form.getFieldState(name).isDirty);
  const save = (values: Values, version: number, fields: readonly Field[]) => {
    problem.clear();
    update.mutate(
      { changes: bodyOf(values, fields), version },
      {
        onSuccess: () => {
          void message.success(t('announcements.saved'));
          onDone();
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) setConflict(error);
          else if (!applyServerErrors(error, form.setError, FIELDS)) problem.show(error);
        },
      },
    );
  };
  return (
    <div>
      <AnnouncementFields
        form={form}
        // Template B's sticky footer (D-147, QA10-P4-14): the refusal, then Cancel before Save,
        // always in view while the form is longer than the window.
        footer={
          <FormFooter
            testId="ann-edit-footer"
            notice={<FormProblem problem={problem} />}
            cancel={<Button onClick={onDone}>{t('actions.cancel')}</Button>}
            primary={
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
            }
          />
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
    </div>
  );
}
