import { AlertOutlined, EditOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  App,
  Button,
  Card,
  Flex,
  Input,
  Result,
  Select,
  Skeleton,
  Space,
  Tooltip,
  Typography,
} from 'antd';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  ApiError,
  checklistKeys,
  queryKeys,
  useCausingProblem,
  useDeleteIncident,
  useIncident,
  useIncidentTasks,
  useAutoStartTimer,
  useIncidentCatalogue,
  useIncidentCategories,
  attachDrafts,
  useIncidentTemplates,
  useSession,
  useStructure,
  useUnits,
  useCustomFields,
  useUpdateIncident,
  type Incident,
  type IncidentActionState,
  type CustomField,
  type ReplyMode,
  recordAssetKeys,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useRecordChannel, type PresenceMember } from '@supportx/realtime';
import {
  ActionBar,
  AlertStrip,
  ChannelTag,
  ConflictDialog,
  describeError,
  EditableValue,
  FormProblem,
  inlineImageIds,
  lengthLimit,
  markHandled,
  PresenceAvatars,
  PropertiesPanel,
  PropertyList,
  PropertyRow,
  type RecordAction,
  RecordHeader,
  RecordPage,
  reportError,
  RichTextField,
  RichTextView,
  SPACE,
  useAppearance,
  useConflictRetry,
  useDateTime,
  useFormProblem,
  useLabel,
  useAccess,
  useLicence,
  usePageCrumbs,
  WriteButton,
  Tabs,
} from '@supportx/ui';

import { CopyDialog } from './CopyDialog';
import { RecordWorkflows } from '../workflows/RecordWorkflows';
import { CustomFieldControl, CustomFieldValue } from '../customFields/fields';
import { fieldName } from '../customFields/values';
import { AssignDialog } from './assign';
import { useTakeAction } from './take';
import { useActionReason } from './actionReason';
import { useIncidentFieldName } from './conflict';
import { IncidentConversation, type Typing } from './IncidentConversation';
import { IncidentFiles } from './IncidentFiles';
import { rememberIncident } from './recent';
import { DEFAULT_TAB, lastTab, RECORD_TABS, rememberTab } from './tabs';
import { TYPING_SHOWN_MS } from './typing';
import { FollowButton, FollowersCard } from './IncidentFollowers';
import { KnowledgeCard } from '../knowledge/KnowledgeCard';
import { SummaryCard } from './SummaryCard';
import { KnowledgePicker } from '../knowledge/KnowledgePicker';
import { KnownErrorTool } from '../problems/KnownErrorTool';
import { KnowledgeSlotContext, type KnowledgeSlot } from './knowledgeSlot';
import { IncidentSla } from './IncidentSla';
import { IncidentLinks, IncidentTasks, IncidentTime, IncidentWorklogs } from './IncidentParts';
import { AutoCloseNote } from './autoClose';
import { IncidentAutomation, LoopWarning } from './IncidentAutomation';
import { IncidentHistory } from './IncidentHistory';
import { RecordAllFiles } from './RecordAllFiles';
import { RecordChecklists } from './RecordChecklists';
import { RecordReminders } from './RecordReminders';
import { CategoryCascade } from './CategoryCascade';
import {
  categoryPath,
  closureCodeLabel,
  labelled,
  levelLabel,
  listValueLabel,
  personName,
  reasonValueLabel,
  scaleLabel,
  templateLabel,
} from './labels';
import { DepartmentPicker, SitePicker, UserPicker } from './pickers';
import { IMPACT_DETAILS_MAX, SUBJECT_MAX } from './form';
import { useStatusActions } from './StatusActions';
import { PriorityTag, SlaTag, StatusTag } from './tags';
import { TagsInput } from './TagsInput';
import { CausingProblemCard } from './CausingProblemCard';
import { RecordAssets } from './RecordAssets';

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
    <>
      <IncidentCrumbs item={item} />
      <IncidentDetail
        key={item.id}
        item={item}
        reload={async () => (await incident.refetch()).data}
      />
    </>
  );
}

function IncidentDetail({ item, reload }: { item: Incident; reload: () => Promise<unknown> }) {
  const t = useLabel();
  const dates = useDateTime();
  const navigate = useNavigate();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const catalogue = useIncidentCatalogue();
  const { locale } = useAppearance();
  const groups = useUnits('groups');
  const others = useRef<PresenceMember[]>([]);
  const editing = useRef(0);
  const [changedBy, setChangedBy] = useState<string | null>(null);
  const behind = useRef(false); // a change arrived while someone here was editing
  const [assigning, setAssigning] = useState(false);
  const [copying, setCopying] = useState(false);
  const [typing, setTyping] = useState<Typing>({});
  const typingTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const me = useSession().data?.user.id ?? null;
  // The causing problem, narrowly (WP-044c D14); live on its channel for who may open it.
  const cause = useCausingProblem(item.id);
  useRecordChannel('wi', cause.data?.may_open ? cause.data.id : undefined, () => {
    void queryClient.invalidateQueries({
      queryKey: [...queryKeys.incidents.links(item.id), 'cause'],
    });
  });
  // A record just made opens on Conversation, whatever tab was used last (QA6-INC-04).
  const justMade = (useLocation().state as { justMade?: boolean } | null)?.justMade === true;
  // A link to a tab (`?tab=tasks`) opens on it, as changes do (QA 2026-11-12 F-10); then a
  // record just made opens on Conversation; otherwise the tab this user used last.
  const [params] = useSearchParams();
  const asked = params.get('tab');
  const known = asked !== null && (RECORD_TABS as readonly string[]).includes(asked);
  const [tab, setTab] = useState<string>(() =>
    known ? asked : justMade ? DEFAULT_TAB : lastTab(me),
  );
  const [replyRequest, setReplyRequest] = useState(0);
  // A composer is open: its Send is the one primary action, so the header's buttons go quiet.
  const [composing, setComposing] = useState(false);
  const [replyMode, setReplyMode] = useState<ReplyMode>('reply');
  // Tasks, worklogs and links follow the record's edit permission (WP-020e).
  const canEditParts = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const canEditSubject = canEditParts;
  // Offered first in quick search and record pickers (REQ-INC-085).
  useEffect(() => {
    rememberIncident(me, item.id);
  }, [me, item.id]);
  // WP-046a S3 (REQ-INC-069): with the type's auto-start on, opening your own record starts
  // your timer, once ever (the server decides and keeps it to once).
  const { mutate: autoStartTimer } = useAutoStartTimer(item.id);
  const autoStart = catalogue.data?.closure.timer_auto_start === true;
  const mine = me !== null && item.technician_id === me && canEditParts;
  useEffect(() => {
    if (autoStart && mine) autoStartTimer();
  }, [autoStart, mine, item.id, autoStartTimer]);
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
    // The summary was made, or a newer entry made it stale (WP-038): refetch it only.
    if (event.type === 'ai.summary_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.ai.summary('incident', item.id) });
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
    // A task, worklog or link changed (WP-020e): that part's list refetches.
    if (event.type === 'work_items.part_changed') {
      const part = event.fields?.[0];
      if (part === 'task') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.tasks(item.id) });
      } else if (part === 'worklog') {
        void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.worklogs(item.id) });
      } else if (part === 'checklist') {
        // WP-046a S2: a checklist added, ticked or removed.
        void queryClient.invalidateQueries({ queryKey: checklistKeys.of('incidents', item.id) });
      } else if (part === 'asset') {
        // REQ-AST-025: an asset linked or unlinked.
        void queryClient.invalidateQueries({
          queryKey: recordAssetKeys.of('incidents', item.id),
        });
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.links(item.id) });
      }
      return;
    }
    if (event.type === 'work_items.followers_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.incidents.followers(item.id) });
      if (editing.current === 0) void reload();
      return;
    }
    // A file was added, checked, blocked or removed (WP-022): refetch the record's files.
    if (event.type === 'files.changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.files.record('incident', item.id) });
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
  // Changed by someone after it was shown (409): the shared dialog (QA WP-029 BUG-05).
  const removeConflict = useConflictRetry();
  const incidentField = useIncidentFieldName();
  const removeIt = (version: number) => {
    remove.mutate(version, {
      onSuccess: () => {
        void message.success(t('incidents.deleted'));
        void navigate('/incidents');
      },
      onError: (error) => {
        if (!removeConflict.take(error, removeIt)) reportError(error);
      },
    });
  };
  const op = (name: string): IncidentActionState | undefined =>
    item.operations.find((o) => o.action === name);
  const deleteOp = op('delete');
  const reasonText = useActionReason();
  const status = useStatusActions(item, catalogue.data);
  const take = useTakeAction(item, op('take'));
  const { has } = useLicence();
  const { can } = useAccess();
  const groupName =
    item.group_id === null ? '' : (groups.data?.find((g) => g.id === item.group_id)?.name ?? '');

  const onEditing = (delta: number) => {
    editing.current = Math.max(0, editing.current + delta);
    // Nobody edits any more: catch up with what changed meanwhile (QA BUG-09).
    if (editing.current === 0 && behind.current) {
      behind.current = false;
      setChangedBy(null);
      void reload();
    }
  };
  const actionOf = (
    name: string,
    label: string,
    testId: string,
    onClick: () => void,
    rank: number,
  ): RecordAction | null => {
    const state = op(name);
    if (state === undefined) return null;
    return {
      key: name,
      label,
      allowed: state.allowed,
      whyNot: !state.allowed && state.reason != null ? reasonText(state) : undefined,
      primary: true,
      rank,
      testId,
      onClick,
    };
  };
  const replyAction = (): RecordAction | null => {
    const state = item.conversation_actions.find((a) => a.action === 'reply');
    if (state === undefined) return null;
    return {
      key: 'reply',
      label: t('reply_mode.reply'),
      allowed: state.allowed,
      whyNot: !state.allowed && state.reason != null ? reasonText(state) : undefined,
      primary: true,
      rank: 0,
      testId: 'inc-op-reply',
      onClick: () => {
        answer('reply');
      },
      // D-155: the record's one Reply; reply to all and forward in its dropdown.
      variants: (['reply_all', 'forward'] as const).map((mode) => ({
        key: mode,
        label: t(`reply_mode.${mode}`),
        testId: `inc-op-${mode}`,
        onClick: () => {
          answer(mode);
        },
      })),
    };
  };
  function answer(mode: ReplyMode) {
    setTab('conversation');
    rememberTab(me, 'conversation');
    setReplyMode(mode);
    setReplyRequest((n) => n + 1);
  }
  // Every action in its one fixed order (REQ-WI-010, D-124): assign, take, the status moves,
  // then delete apart from the rest.
  const actions = [
    // Reply first and as the primary button (UI pass 2): it opens the composer on Conversation.
    // Its right comes from the conversation's actions (a reply is not a record operation).
    replyAction(),
    actionOf(
      'assign',
      t('work_item_operation.assign'),
      'inc-op-assign',
      () => {
        setAssigning(true);
      },
      4,
    ),
    take.action,
    ...status.actions,
    // WP-044a (REQ-PRB-011): a problem prefilled from this incident and linked "caused by".
    has('problem') && can('problems.create')
      ? {
          key: 'create_problem',
          label: t('problems.create_from_incident'),
          allowed: true,
          testId: 'inc-op-create-problem',
          onClick: () => void navigate(`/problems/new?incident=${item.id}`),
        }
      : null,
    // WP-046a S5c (REQ-INC-033): copy it one or more times.
    can('incidents.create')
      ? {
          key: 'copy',
          label: t('incidents.copy.open'),
          allowed: true,
          testId: 'inc-op-copy',
          onClick: () => {
            setCopying(true);
          },
        }
      : null,
    deleteOp !== undefined && deleteOp.reason !== 'no_permission'
      ? {
          key: 'delete',
          label: t('work_item_operation.delete'),
          allowed: deleteOp.allowed,
          whyNot: !deleteOp.allowed && deleteOp.reason != null ? reasonText(deleteOp) : undefined,
          danger: true,
          confirm: t('incidents.delete_confirm', { id: item.display_id }),
          loading: remove.isPending,
          testId: 'inc-op-delete',
          onClick: () => {
            removeIt(item.version);
          },
        }
      : null,
  ].filter((action): action is RecordAction => action !== null);

  const statusReason =
    item.status_reason_code !== null || item.status_reason_text !== null ? (
      <span data-testid="inc-status-reason">
        {t('incidents.status_reason')}:{' '}
        {item.status_reason_code === null
          ? ''
          : reasonValueLabel(t, catalogue.data, item.status_reason_code, locale)}
        {item.status_reason_text === null ? (
          ''
        ) : (
          <>
            {' — '}
            <bdi dir="auto">{item.status_reason_text}</bdi>
          </>
        )}
      </span>
    ) : null;

  // Knowledge in this record's editors (D-121): the picker, for replies, notes and the resolution.
  // Known errors join it (WP-044b, REQ-PRB-038) where problems are licensed and seen.
  const knowledgeSlot: KnowledgeSlot = (insert, audience) => (
    <>
      <KnowledgePicker
        recordType="incident"
        recordId={item.id}
        subject={item.subject}
        audience={audience}
        insert={insert}
      />
      {has('problem') && can('problems.view') && (
        <KnownErrorTool incidentId={item.id} insert={insert} />
      )}
    </>
  );

  return (
    <KnowledgeSlotContext.Provider value={knowledgeSlot}>
      <RecordPage
        testId="inc-record"
        header={
          <RecordHeader
            icon={<AlertOutlined />}
            kind="incident"
            badge={<ChannelTag channel={item.channel} />}
            typeLabel={t('incidents.record_type')}
            displayId={item.display_id}
            title={item.subject}
            testIds={{ id: 'inc-display-id', title: 'inc-heading' }}
            // The subject is edited here, in place (D-147: no second Subject in Properties).
            renderTitle={(shown) =>
              canEditSubject ? (
                <InlineEdit
                  item={item}
                  field="subject"
                  label={t('work_item.field.subject')}
                  spec={{ kind: 'text', value: item.subject }}
                  reload={reload}
                  onEditing={onEditing}
                >
                  {shown}
                </InlineEdit>
              ) : (
                shown
              )
            }
            tags={
              <>
                <StatusTag status={item.status} catalogue={catalogue.data} />
                <PriorityTag priority={item.priority} source={item.priority_source} />
                <SlaTag
                  policyId={item.sla_policy_id}
                  dueAt={item.resolution_due_at}
                  state={item.resolution_sla_state}
                  resolvedAt={item.resolved_at}
                  format={dates.format}
                />
              </>
            }
            meta={[
              // Names are isolated, so a mixed Arabic and English line keeps its order (QA C6).
              <span key="people" data-testid="inc-people">
                {t('incidents.requested_by', { name: personName(item.people, item.requester_id) })}
              </span>,
              <span key="created">
                {t('incidents.created_on', { date: dates.format(item.created_at) })}
              </span>,
              ...(statusReason === null ? [] : [statusReason]),
            ]}
          />
        }
        // One row (D-147 template A): who else is here, Follow, then at most three buttons and
        // More actions (UI pass 2).
        actions={
          <ActionBar
            actions={actions}
            max={3}
            quiet={composing}
            testId="inc-operations"
            lead={
              <>
                <PresenceAvatars viewers={viewers} selfUserId={me} />
                <FollowButton item={item} me={me} />
              </>
            }
          />
        }
        alerts={
          <>
            <AlertStrip
              testId="inc-alerts"
              alerts={
                changedBy === null
                  ? []
                  : [
                      {
                        key: 'live',
                        type: 'warning',
                        dismissible: false,
                        testId: 'live-change-notice',
                        message: t('live.changed_by', { name: changedBy }),
                        action: (
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
                        ),
                      },
                    ]
              }
            />
            <LoopWarning id={item.id} />
          </>
        }
        panel={
          <PropertiesPanel
            testId="inc-panel"
            sections={[
              // The conversation summary first, where a technician picking it up looks
              // (WP-038, REQ-INC-137); only while the feature is on.
              {
                key: 'summary',
                title: t('ai.summary.title'),
                bare: true, // its own card, with Refresh
                children: <SummaryCard recordId={item.id} />,
              },
              {
                key: 'properties',
                title: t('incidents.properties'),
                children: (
                  <Details item={item} reload={reload} onEditing={onEditing} part="properties" />
                ),
              },
              {
                key: 'sla',
                title: t('incidents.panel.sla'),
                testId: 'inc-panel-sla',
                // Lane A's SLA card (WP-025, #152) in the panel section kept for it.
                children: (
                  <div data-testid="inc-sla-card">
                    <IncidentSla item={item} />
                  </div>
                ),
              },
              // The causing problem, narrowly, for every technician (WP-044c D14).
              ...(cause.data
                ? [
                    {
                      key: 'cause',
                      title: t('incidents.causing_problem.title'),
                      testId: 'inc-panel-cause',
                      children: <CausingProblemCard cause={cause.data} />,
                    },
                  ]
                : []),
              {
                key: 'assignment',
                title: t('incidents.panel.assignment'),
                testId: 'inc-panel-assignment',
                children: (
                  <>
                    <PropertyRow label={t('work_item.field.group_id')}>
                      <bdi>{groupName}</bdi>
                    </PropertyRow>
                    <PropertyRow label={t('work_item.field.technician_id')}>
                      {item.technician_id === null ? (
                        <Typography.Text type="secondary">
                          {t('incidents.unassigned')}
                        </Typography.Text>
                      ) : (
                        <bdi>{personName(item.people, item.technician_id)}</bdi>
                      )}
                    </PropertyRow>
                  </>
                ),
              },
              // REQ-AST-025: the assets this incident is about (the assets feature).
              ...(has('assets')
                ? [
                    {
                      key: 'assets',
                      title: t('assets.link.title'),
                      testId: 'inc-panel-assets',
                      children: (
                        <RecordAssets
                          base="incidents"
                          recordId={item.id}
                          canEdit={canEditParts}
                          requesterId={item.requester_id}
                        />
                      ),
                    },
                  ]
                : []),
              // Your own reminders on it (WP-046a S2, REQ-INC-082): yours only.
              {
                key: 'reminders',
                title: t('reminders.title'),
                bare: true,
                children: <RecordReminders recordId={item.id} />,
              },
              {
                key: 'followers',
                title: t('incidents.panel.followers'),
                bare: true, // its own card, with the count and the add field
                children: <FollowersCard item={item} me={me} />,
              },
              // Linked articles you may read, and how many others (WP-033 s4, D-121).
              {
                key: 'knowledge',
                title: t('knowledge.card.title'),
                bare: true, // its own card, with Link an article
                children: (
                  <KnowledgeCard
                    recordType="incident"
                    recordId={item.id}
                    subject={item.subject}
                    hasResolution={item.resolution !== null}
                    userId={me ?? ''}
                  />
                ),
              },
            ]}
          />
        }
      >
        <ConflictDialog {...removeConflict.dialog} fieldLabel={incidentField} />
        <CopyDialog
          open={copying}
          recordId={item.id}
          displayId={item.display_id}
          onClose={() => {
            setCopying(false);
          }}
        />
        <AssignDialog
          item={item}
          open={assigning}
          refresh={reload}
          onClose={() => {
            setAssigning(false);
          }}
        />
        {status.dialogs}
        {take.dialogs}
        <Tabs
          data-testid="inc-tabs"
          // The tab this user used last, Conversation the first time (D-081).
          activeKey={tab}
          onChange={(key) => {
            setTab(key);
            rememberTab(me, key);
            // Leaving Conversation ends a pending Reply: coming back must not reopen it.
            if (key !== 'conversation') setReplyRequest(0);
          }}
          items={[
            {
              key: 'conversation',
              // What the tab lists (Haider, 2026-11-10): the description, then the replies and
              // notes. System lines are history, counted on their own tab.
              label: t('incidents.tab.conversation', { count: item.conversation_count + 1 }),
              children: (
                <IncidentConversation
                  item={item}
                  typing={typing}
                  replyRequest={replyRequest}
                  replyMode={replyMode}
                  onComposingChange={setComposing}
                />
              ),
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
                  part="main"
                />
              ),
            },
            {
              key: 'tasks',
              label: <TasksTabLabel id={item.id} />,
              children: <IncidentTasks item={item} canEdit={canEditParts} />,
            },
            {
              key: 'checklists',
              label: t('checklists.tab'),
              children: <RecordChecklists recordId={item.id} canEdit={canEditParts} />,
            },
            {
              key: 'files',
              label: t('files.all.tab'),
              children: <RecordAllFiles recordType="incident" recordId={item.id} />,
            },
            {
              key: 'worklogs',
              label: t('incidents.tab.worklogs'),
              children: <IncidentWorklogs item={item} canEdit={canEditParts} />,
            },
            {
              key: 'links',
              label: t('incidents.tab.links'),
              children: <IncidentLinks item={item} canEdit={canEditParts} />,
            },
            // WP-048b S4d: the workflows running on it (REQ-WF-023); lane A placed it, 2026-11-11.
            ...(can('workflows.run') || can('workflows.manage')
              ? [
                  {
                    key: 'workflows',
                    label: t('workflows.record.tab'),
                    children: <RecordWorkflows recordType="incident" recordId={item.id} />,
                  },
                ]
              : []),
            // WP-046a S3 (REQ-INC-071): where the time went.
            {
              key: 'time',
              label: t('incidents.tab.time'),
              children: <IncidentTime item={item} />,
            },
            {
              key: 'history',
              label: t('incidents.tab.history', { count: item.history_count }),
              children: <IncidentHistory id={item.id} />,
            },
            {
              key: 'automation',
              label: t('incidents.tab.automation'),
              children: <IncidentAutomation id={item.id} />,
            },
          ]}
        />
      </RecordPage>
    </KnowledgeSlotContext.Provider>
  );
}

/** "Tasks 1/3": done over total, live (REQ-INC-072 AC1). */
function TasksTabLabel({ id }: { id: string }) {
  const t = useLabel();
  const tasks = useIncidentTasks(id);
  return (
    <span data-testid="inc-tab-tasks">
      {tasks.data === undefined || tasks.data.total === 0
        ? t('incidents.tab.tasks')
        : t('incidents.tab.tasks_count', { done: tasks.data.done, total: tasks.data.total })}
    </span>
  );
}

/** The incident this one follows: its display ID, a link to it (REQ-INC-098). */
function FollowsLink({ id }: { id: string }) {
  const t = useLabel();
  const other = useIncident(id);
  return (
    <Link to={`/incidents/${id}`} data-testid="inc-follows">
      {other.data === undefined ? (
        t('incidents.closing.follows_earlier')
      ) : (
        <bdi dir="ltr">{other.data.display_id}</bdi>
      )}
    </Link>
  );
}

/**
 * The Details tab (`main`: description, files and resolution) and the properties edited in place
 * (`properties`, REQ-INC-123), which live in the record page's permanent panel (D-124).
 */
function Details({
  item,
  reload,
  onEditing,
  part,
}: {
  item: Incident;
  reload: () => Promise<unknown>;
  onEditing: (delta: number) => void;
  part: 'main' | 'properties';
}) {
  const t = useLabel();
  const listFormat = useListFormat();
  const { locale } = useAppearance();
  const dates = useDateTime();
  const categories = useIncidentCategories();
  const catalogue = useIncidentCatalogue();
  const templates = useIncidentTemplates();
  const customFields = useCustomFields('incident');
  const sites = useUnits('sites');
  const departments = useStructure('departments');
  const scale = (name: 'impact' | 'urgency', code: string) =>
    scaleLabel(t, catalogue.data, name, code, locale);
  const template = templates.data?.find((x) => x.id === item.template_id);
  // Retired values stay on the records that use them, marked as retired (QA C8).
  const retiredMark = (text: string, retired: boolean) =>
    retired && text !== '' ? t('categories.retired_value', { name: text }) : text;
  const levelOptions = (catalogue.data?.levels ?? [])
    .filter((v) => !v.disabled || v.code === item.level)
    .map((v) => ({
      value: v.code,
      label: v.disabled
        ? t('categories.retired_value', { name: listValueLabel(t, 'level', v, locale) })
        : listValueLabel(t, 'level', v, locale),
    }));
  const canEdit = item.operations.find((o) => o.action === 'edit')?.allowed === true;
  const canPriority = item.operations.find((o) => o.action === 'change_priority')?.allowed === true;
  const person = (id: string | null) =>
    id === null
      ? null
      : { id, name: item.people[id]?.display_name ?? '', email: item.people[id]?.email ?? '' };
  // The subject is the header's title (edited there) and the creation time is in its key facts:
  // neither repeats here (D-147: no duplicate Subject). `filled` decides what shows at once.
  const rows: {
    key: string;
    label: string;
    view: ReactNode;
    edit?: EditorSpec;
    filled: boolean;
  }[] = [
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
      filled: true,
    },
    {
      key: 'on_behalf_of_id',
      label: t('work_item.field.on_behalf_of_id'),
      view: <Person item={item} id={item.on_behalf_of_id} />,
      edit: { kind: 'user', value: item.on_behalf_of_id, current: person(item.on_behalf_of_id) },
      filled: item.on_behalf_of_id !== null,
    },
    {
      key: 'site_id',
      label: t('work_item.field.site_id'),
      view: sites.data?.find((s) => s.id === item.site_id)?.name ?? '',
      edit: { kind: 'site', value: item.site_id },
      filled: item.site_id !== null,
    },
    {
      key: 'department_id',
      label: t('work_item.field.department_id'),
      view: departments.data?.find((d) => d.id === item.department_id)?.name ?? '',
      edit: { kind: 'department', value: item.department_id },
      filled: item.department_id !== null,
    },
    {
      key: 'category_id',
      label: t('work_item.field.category_id'),
      view: retiredMark(
        categoryPath(t, categories.data ?? [], item.category_id, locale),
        categories.data?.find((n) => n.id === item.category_id)?.disabled === true,
      ),
      edit: { kind: 'category', value: item.category_id },
      filled: item.category_id !== null,
    },
    {
      key: 'level',
      label: t('work_item.field.level'),
      view: retiredMark(
        levelLabel(t, catalogue.data, item.level, locale),
        catalogue.data?.levels.find((v) => v.code === item.level)?.disabled === true,
      ),
      edit: { kind: 'choice', value: item.level, options: levelOptions },
      filled: item.level !== null,
    },
    {
      key: 'impact',
      label: t('work_item.field.impact'),
      view: item.impact === null ? '' : scale('impact', item.impact),
      edit: {
        kind: 'choice',
        value: item.impact,
        options: IMPACTS.map((v) => ({ value: v, label: scale('impact', v) })),
      },
      filled: item.impact !== null,
    },
    {
      key: 'impact_details',
      label: t('work_item.field.impact_details'),
      view: (
        <bdi dir="auto" style={{ whiteSpace: 'pre-wrap' }}>
          {item.impact_details ?? ''}
        </bdi>
      ),
      edit: { kind: 'longtext', value: item.impact_details ?? '' },
      filled: (item.impact_details ?? '') !== '',
    },
    {
      key: 'urgency',
      label: t('work_item.field.urgency'),
      view: item.urgency === null ? '' : scale('urgency', item.urgency),
      edit: {
        kind: 'choice',
        value: item.urgency,
        options: URGENCIES.map((v) => ({ value: v, label: scale('urgency', v) })),
      },
      filled: item.urgency !== null,
    },
    {
      key: 'priority',
      label: t('work_item.field.priority'),
      view: <PriorityTag priority={item.priority} source={item.priority_source} />,
      edit: canPriority ? { kind: 'priority', value: item.priority } : undefined,
      filled: true,
    },
    {
      key: 'channel',
      label: t('work_item.field.channel'),
      view: t(`work_item_channel.${item.channel}`),
      filled: true,
    },
    {
      key: 'tags',
      label: t('work_item.field.tags'),
      view: listFormat(item.tags),
      edit: { kind: 'tags', value: item.tags },
      filled: item.tags.length > 0,
    },
    // Custom fields (WP-026): the ones the template shows, and any other holding a value
    // (retired ones read-only, marked).
    ...(customFields.data ?? [])
      .filter((f) => {
        const value = item.custom[f.key];
        const held = value !== null && value !== undefined;
        return held || (!f.retired && (template?.custom_fields[f.key]?.shown ?? true));
      })
      .map((f) => {
        const label = fieldName(f, locale);
        const value = item.custom[f.key] ?? null;
        const current = typeof value === 'string' ? person(value) : null;
        return {
          key: `custom.${f.key}`,
          label: f.retired ? t('custom_fields.retired_value', { name: label }) : label,
          view: <CustomFieldValue field={f} value={value} people={item.people} />,
          edit: f.retired
            ? undefined
            : ({ kind: 'custom', value, field: f, current } satisfies EditorSpec),
          filled: value !== null && value !== '' && !(Array.isArray(value) && value.length === 0),
        };
      }),
    {
      key: 'template_id',
      label: t('work_item.field.template_id'),
      view:
        template === undefined ? (
          ''
        ) : (
          <>
            <bdi dir="auto">{templateLabel(t, template, locale)}</bdi>
            {template.disabled && <> ({t('templates.disabled')})</>}
          </>
        ),
      filled: item.template_id !== null,
    },
    {
      key: 'resolved_at',
      label: t('work_item.field.resolved_at'),
      view: dates.format(item.resolved_at),
      filled: item.resolved_at !== null,
    },
    // Only once closed; reopening clears it, and history keeps the time (WP-020f QA BUG-06).
    ...(item.closed_at === null
      ? []
      : [
          {
            key: 'closed_at',
            label: t('work_item.field.closed_at'),
            view: dates.format(item.closed_at),
            filled: true,
          },
        ]),
    {
      key: 'reopen_count',
      label: t('work_item.field.reopen_count'),
      view: String(item.reopen_count),
      filled: item.reopen_count > 0,
    },
    // A requester's late reply started this record (REQ-INC-098, D7).
    ...(item.follows_id === null
      ? []
      : [
          {
            key: 'follows_id',
            label: t('work_item.field.follows_id'),
            view: <FollowsLink id={item.follows_id} />,
            filled: true,
          },
        ]),
  ];
  if (part === 'properties') {
    // Filled fields first; the empty ones you may fill wait behind "Add details" (D-147).
    // An empty field nobody here may edit is left out: there is nothing to do with it.
    return (
      <PropertyList
        testId="inc-properties"
        items={rows
          .filter((row) => row.filled || (row.edit !== undefined && canEdit))
          .map((row) => ({
            key: row.key,
            label: row.label,
            filled: row.filled,
            content:
              row.edit !== undefined && canEdit ? (
                <InlineEdit
                  item={item}
                  field={row.key}
                  label={row.label}
                  spec={row.edit}
                  reload={reload}
                  onEditing={onEditing}
                  empty={!row.filled}
                >
                  {row.view}
                </InlineEdit>
              ) : (
                <span data-testid={`inc-prop-${row.key}`}>{row.view}</span>
              ),
          }))}
      />
    );
  }
  return (
    /* The description, and below it the resolution once there is one (REQ-INC-090). */
    <Flex vertical gap={SPACE.sm} style={{ minWidth: 0 }}>
      <Card size="small" title={t('work_item.field.description')}>
        <Description item={item} canEdit={canEdit} reload={reload} onEditing={onEditing} />
        <IncidentFiles item={item} canEdit={canEdit} />
      </Card>
      {(item.resolution !== null || item.closure_code !== null) && (
        <Card
          size="small"
          title={t('work_item.field.resolution')}
          data-testid="inc-resolution-card"
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            {item.resolution !== null && (
              <RichTextView html={item.resolution} testId="inc-resolution" />
            )}
            {item.closure_code !== null && (
              <Typography.Text data-testid="inc-closure-code-view">
                {t('incidents.closing.closure_code_shown', {
                  code: closureCodeLabel(t, catalogue.data, item.closure_code, locale),
                })}
              </Typography.Text>
            )}
            <AutoCloseNote item={item} catalogue={catalogue.data} />
          </Space>
        </Card>
      )}
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
  | { kind: 'longtext'; value: string }
  | {
      kind: 'user';
      value: string | null;
      current: { id: string; name: string; email: string } | null;
      required?: boolean;
    }
  | { kind: 'site'; value: string | null }
  | { kind: 'department'; value: string | null }
  | { kind: 'category'; value: string | null }
  | { kind: 'choice'; value: string | null; options: { value: string; label: string }[] }
  | { kind: 'priority'; value: string }
  | { kind: 'tags'; value: string[] }
  | {
      kind: 'custom';
      value: unknown;
      field: CustomField;
      current: { id: string; name: string; email: string } | null;
    };

/** One property in place: view, pencil, then the control with save / cancel (and its errors). */
function InlineEdit({
  item,
  field,
  label,
  spec,
  reload,
  onEditing,
  empty = false,
  children,
}: {
  item: Incident;
  field: string;
  label: string;
  spec: EditorSpec;
  reload: () => Promise<unknown>;
  onEditing: (delta: number) => void;
  /** Nothing saved yet: reads "Add". */
  empty?: boolean;
  children: ReactNode;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const update = useUpdateIncident(item.id);
  const catalogue = useIncidentCatalogue();
  const customFields = useCustomFields('incident', true);
  const { locale } = useAppearance();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState<unknown>(spec.value);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  // A refusal with no field to point at (a rule, a limit), shown here (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const [conflict, setConflict] = useState<unknown>(null);
  const close = () => {
    setOpen(false);
    setError(null);
    problem.clear();
    onEditing(-1);
  };
  const save = (version = item.version) => {
    const changes: Record<string, unknown> =
      spec.kind === 'priority'
        ? value === 'matrix'
          ? { priority: null }
          : { priority: value, priority_reason: reason }
        : spec.kind === 'custom'
          ? { custom: { [spec.field.key]: value } }
          : { [field]: value };
    problem.clear();
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
            markHandled(failure);
            setError(failure.fieldErrors.map((e) => t(e.message_key, e.params)).join(' '));
            return;
          }
          problem.show(failure);
        },
      },
    );
  };
  if (!open) {
    // The value itself is the control (D-147 template A): a click edits, no pencil per row.
    return (
      <EditableValue
        label={label}
        empty={empty}
        testId={`inc-edit-${field}`}
        onEdit={() => {
          setValue(spec.value);
          setReason('');
          setOpen(true);
          onEditing(1);
        }}
      >
        <span data-testid={`inc-prop-${field}`}>{children}</span>
      </EditableValue>
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
            count={lengthLimit(SUBJECT_MAX, true)}
            onChange={(event) => {
              setValue(event.target.value);
            }}
            onPressEnter={() => {
              save();
            }}
            data-testid={`inc-input-${field}`}
          />
        );
      case 'longtext':
        return (
          <Input.TextArea
            id={id}
            aria-label={label}
            dir="auto"
            autoFocus
            autoSize={{ minRows: 2, maxRows: 6 }}
            value={typeof value === 'string' ? value : ''}
            count={lengthLimit(IMPACT_DETAILS_MAX, true)}
            onChange={(event) => {
              setValue(event.target.value);
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
      case 'department':
        return (
          <DepartmentPicker
            id={id}
            value={(value as string | null) ?? null}
            onChange={setValue}
            testId={`inc-input-${field}`}
            ariaLabel={label}
          />
        );
      case 'category':
        return (
          <CategoryCascade
            id={id}
            value={(value as string | null) ?? null}
            onChange={setValue}
            testId={`inc-input-${field}`}
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
                ...PRIORITIES.map((p) => ({
                  value: p,
                  label: scaleLabel(t, catalogue.data, 'priority', p, locale),
                })),
              ]}
              style={{ width: '100%' }}
              data-testid="inc-input-priority"
            />
            {value !== 'matrix' && (
              <Input
                aria-label={t('work_item.field.priority_reason')}
                placeholder={t('work_item.field.priority_reason')}
                value={reason}
                count={lengthLimit(500)}
                onChange={(event) => {
                  setReason(event.target.value);
                }}
                data-testid="inc-input-priority-reason"
              />
            )}
          </Space>
        );
      case 'custom':
        return (
          <CustomFieldControl
            id={id}
            field={spec.field}
            value={value}
            saved={spec.value}
            current={spec.current}
            onChange={setValue}
            testId={`inc-input-${field}`}
            ariaLabel={label}
            autoFocus
          />
        );
      case 'tags':
        return (
          <TagsInput
            id={id}
            ariaLabel={label}
            value={value as string[]}
            onChange={setValue}
            testId={`inc-input-${field}`}
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
      <FormProblem problem={problem} />
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
        fieldLabel={(name) => {
          if (!name.startsWith('custom.')) return t(`work_item.field.${name}`);
          const found = customFields.data?.find((f) => `custom.${f.key}` === name);
          return found === undefined ? t('custom_fields.unknown_field') : fieldName(found, locale);
        }}
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
  const me = useSession().data?.user.id ?? null;
  const update = useUpdateIncident(item.id);
  const [editing, setEditing] = useState(false);
  const [html, setHtml] = useState(item.description ?? '');
  const [conflict, setConflict] = useState<unknown>(null);
  const problem = useFormProblem();
  const save = (version: number) => {
    problem.clear();
    update.mutate(
      { changes: { description: html }, version },
      {
        onSuccess: () => {
          // Images pasted into the description were the author's drafts: attach them (WP-022).
          attachDrafts('work_item', item.id, inlineImageIds(html)).catch(reportError);
          void message.success(t('incidents.saved'));
          setEditing(false);
          onEditing(-1);
        },
        onError: (failure) => {
          if (failure instanceof ApiError && failure.code === 'version_conflict')
            setConflict(failure);
          else problem.show(failure);
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
    problem.clear();
    onEditing(-1);
  };
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <RichTextField
        label={t('work_item.field.description')}
        value={html}
        onChange={setHtml}
        testId="inc-description-editor"
        imageOwnerId={me ?? undefined}
      />
      <FormProblem problem={problem} />
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

/**
 * Where the user is: "IT Service Desk › Incidents › INC-42" (the desk only with ESM; product
 * owner, 2026-10-28), in the header and the browser tab.
 */
function IncidentCrumbs({ item }: { item: Incident }) {
  const t = useLabel();
  const { locale } = useAppearance();
  const esm = useLicence().has('esm');
  const desks = useStructure('desks', esm, true);
  const desk = esm ? desks.data?.find((d) => d.id === item.desk_id) : undefined;
  usePageCrumbs([
    ...(desk ? [{ label: labelled(desk.labels, locale, () => t(`desk.${desk.code}`)) }] : []),
    { label: t('nav.incidents'), path: '/incidents' },
    { label: item.display_id },
  ]);
  return null;
}
