import { useQueryClient } from '@tanstack/react-query';
import {
  DownOutlined,
  PrinterOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { Button, Card, Dropdown, Flex, Result, Skeleton, Space, Tabs, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';

import {
  changeKeys,
  useChange,
  useChangeDetails,
  useStagedApprovals,
  useStagedPanel,
  useStagedSettings,
  type StageMove,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  RecordHeader,
  RecordPage,
  StageRail,
  useAccess,
  ToneTag,
  WriteButton,
  reportError,
  useDateTime,
  useLabel,
  usePageCrumbs,
  SPACE,
} from '@supportx/ui';

import { IncidentConversation, type Typing } from '../incidents/IncidentConversation';
import { IncidentFiles } from '../incidents/IncidentFiles';
import { RecordWorkflows } from '../workflows/RecordWorkflows';
import { IncidentHistory } from '../incidents/IncidentHistory';
import { IncidentTasks } from '../incidents/IncidentParts';
import { personName } from '../incidents/labels';
import { SlaTag } from '../incidents/tags';
import { stageName, statusName } from '../staged/labels';
import { StagedMoveDialog } from '../staged/MoveDialog';
import { ApprovalPreview, ApprovalsPart } from './ChangeApprovals';
import { ChildrenPart } from './ChangeChildren';
import { ChangeProperties } from './ChangeProperties';
import { ChangeScheduleTab } from './ChangeSchedule';
import { EmergencyOverrideDialog } from './EmergencyOverride';
import { DetailsPart, PlanPart, RiskPart, RolesPart, SchedulePart } from './ChangeParts';
import { EMERGENCY_PATH, riskTone } from './labels';

const NO_TYPING: Typing = {};

const CANCELED = 'closure_canceled';
const TABS = [
  'details',
  'conversation',
  'risk',
  'approvals',
  'roles',
  'plan',
  'tasks',
  'schedule',
  'children',
  'workflows',
  'history',
] as const;
// The statuses that raise a stage's approval (acceptance, the plan, the CAB): their move shows
// who would approve and who is left out first (REQ-CHG-039).
const RAISING = new Set([
  'submission_awaiting_acceptance',
  'planning_awaiting_approval',
  'cab_awaiting',
]);
const OVERRIDE = 'emergency_override';
type Tab = (typeof TABS)[number];

/**
 * One change on template A (D-147; WP-045a/b): the header with its risk, window and what needs
 * attention; the stage rail and the moves offered from where it is (ADR-041 §7), one primary
 * (the next stage) and the rest under More, each unavailable one saying why (REQ-WI-010); the
 * properties on the end side; its parts as tabs. Live on the record channel: a move, a decision,
 * a role or a risk assessment shows at once.
 */
export function ChangePage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const asked = params.get('tab');
  const tab: Tab = TABS.includes(asked as Tab) ? (asked as Tab) : 'details';
  const queryClient = useQueryClient();
  const record = useChange(id);
  usePageCrumbs([
    { label: t('nav.changes'), path: '/changes' },
    ...(record.data ? [{ label: record.data.display_id }] : []),
  ]);
  const panel = useStagedPanel('changes', id);
  const settings = useStagedSettings('changes');
  const approvals = useStagedApprovals('changes', id);
  const details = useChangeDetails(id).data;
  const dates = useDateTime();
  const pending = (approvals.data?.items ?? []).filter((a) => a.state === 'pending').length;
  const [moving, setMoving] = useState<StageMove>();
  const [overriding, setOverriding] = useState(false);
  const { can } = useAccess();
  useRecordChannel('wi', id === '' ? undefined : id, () => {
    void queryClient.invalidateQueries({ queryKey: changeKeys.detail(id) });
  });
  useEffect(() => {
    if (record.error) reportError(record.error);
  }, [record.error]);
  if (record.isLoading) return <Skeleton active />;
  if (record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('changes.not_found')}
        extra={<Link to="/changes">{t('nav.changes')}</Link>}
      />
    );
  }
  const c = record.data;
  const moves = panel.data?.moves ?? [];
  const allowed = moves.filter((m) => m.allowed);
  // Canceling ends the change: never beside the positive moves, always in "More".
  const ending = (m: StageMove) => m.to_status === CANCELED;
  const positive = allowed.filter((m) => !ending(m));
  // One clear primary action (D-155): the next stage, else the step forward in this one; a move
  // into a paused status ("More information needed") is never the primary (QA-2026-11-11 F-09).
  const paused = new Set(
    (settings.data?.statuses ?? []).filter((s) => s.category === 'paused').map((s) => s.code),
  );
  const forward = positive.filter((m) => !paused.has(m.to_status));
  const next = positive.find((m) => m.to_stage !== c.stage) ?? forward[0] ?? positive[0];
  const overflow = [...positive.filter((m) => m !== next), ...allowed.filter(ending)];
  const unavailable = moves.filter((m) => !m.allowed);
  // Editing as the record allows it (a closed change is read-only, REQ-CHG-097).
  const mayEdit = c.operations.find((o) => o.action === 'edit')?.allowed === true;
  // D-144: only a change sent back for approval, and only with the permission (the server checks).
  const mayOverride = details?.sent_back === true && can('changes.emergency_override');
  const moveLabel = (m: StageMove) =>
    m.to_stage !== c.stage
      ? t('staged.move.to_stage', { stage: stageName(t, m.to_stage) })
      : t('staged.move.to', { status: statusName(t, m.to_status) });
  const actions = (
    <Flex
      gap={8}
      wrap
      justify="flex-end"
      data-testid="change-moves"
      style={{ marginBlock: SPACE.xs }}
    >
      {next && (
        <WriteButton
          type="primary"
          data-testid={`move-${next.to_status}`}
          onClick={() => {
            setMoving(next);
          }}
        >
          {moveLabel(next)}
        </WriteButton>
      )}
      {(overflow.length > 0 || unavailable.length > 0 || mayOverride) && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
              ...(mayOverride
                ? [
                    {
                      key: OVERRIDE,
                      danger: true,
                      label: (
                        <span data-testid="change-emergency-override">
                          {t('changes.override.action')}
                        </span>
                      ),
                      onClick: () => {
                        setOverriding(true);
                      },
                    },
                  ]
                : []),
              ...overflow.map((m) => ({
                key: m.to_status,
                danger: ending(m),
                label: <span data-testid={`move-${m.to_status}`}>{moveLabel(m)}</span>,
                onClick: () => {
                  setMoving(m);
                },
              })),
              ...(unavailable.length > 0
                ? [
                    {
                      type: 'group' as const,
                      key: 'unavailable',
                      label: t('staged.move.unavailable'),
                      children: unavailable.map((m) => ({
                        key: m.to_status,
                        disabled: true,
                        label: (
                          <span data-testid={`move-${m.to_status}`} aria-disabled="true">
                            {moveLabel(m)}
                            <Typography.Text type="secondary" style={{ display: 'block' }}>
                              {t(`action_reason.${m.reason ?? 'no_permission'}`)}
                            </Typography.Text>
                          </span>
                        ),
                      })),
                    },
                  ]
                : []),
            ],
          }}
        >
          <Button data-testid="change-more">
            {t('layout.more_actions')} <DownOutlined aria-hidden />
          </Button>
        </Dropdown>
      )}
      {/* The CAB pack (REQ-CHG-102): a printable page for the board, saved as PDF by the browser. */}
      <Button
        icon={<PrinterOutlined aria-hidden />}
        onClick={() => void navigate(`/changes/${c.id}/pack`)}
        data-testid="change-pack-link"
      >
        {t('changes.pack.open')}
      </Button>
    </Flex>
  );
  // The tabs this person sees; an address naming one they don't (a tab gated on a permission)
  // opens Details rather than an empty page.
  const tabItems = [
    {
      key: 'details',
      label: t('staged.tab.details'),
      children: (
        <>
          <DetailsPart id={c.id} />
          <IncidentFiles item={c} canEdit={mayEdit} recordType="change" />
        </>
      ),
    },
    {
      // REQ-CHG-100: the change's replies and notes, as on every other record.
      key: 'conversation',
      label: (
        <span data-testid="chg-tab-conversation">
          {t('incidents.tab.conversation', { count: c.conversation_count + 1 })}
        </span>
      ),
      children: <IncidentConversation item={c} typing={NO_TYPING} base="changes" />,
    },
    { key: 'risk', label: t('changes.tab.risk'), children: <RiskPart id={c.id} /> },
    {
      key: 'approvals',
      label: t('staged.tab.approvals'),
      children: <ApprovalsPart id={c.id} />,
    },
    { key: 'roles', label: t('staged.tab.roles'), children: <RolesPart id={c.id} /> },
    { key: 'plan', label: t('changes.tab.plans'), children: <PlanPart id={c.id} /> },
    {
      key: 'schedule',
      label: t('staged.tab.schedule'),
      children: <ChangeScheduleTab change={c} stages={<SchedulePart id={c.id} />} />,
    },
    {
      key: 'tasks',
      label: t('changes.tab.tasks'),
      children: <IncidentTasks item={c} canEdit={mayEdit} base="changes" />,
    },
    {
      key: 'children',
      label: t('changes.tab.children'),
      children: <ChildrenPart id={c.id} canEdit={mayEdit} />,
    },
    // Workflows stays last before History (agreed with lane C, #379).
    ...(can('workflows.run') || can('workflows.manage')
      ? [
          {
            key: 'workflows',
            label: t('workflows.record.tab'),
            children: <RecordWorkflows recordType="change" recordId={c.id} />,
          },
        ]
      : []),
    {
      key: 'history',
      label: t('changes.tab.history'),
      children: <IncidentHistory id={c.id} base="changes" />,
    },
  ];
  const shown = tabItems.some((item) => item.key === tab) ? tab : 'details';

  return (
    <RecordPage
      testId="change-page"
      header={
        <RecordHeader
          icon={<SwapOutlined />}
          kind="change"
          typeLabel={t('changes.record_type')}
          displayId={c.display_id}
          title={c.subject}
          meta={[
            <span key="people" data-testid="change-people">
              {t('incidents.requested_by', { name: personName(c.people, c.requester_id) })}
            </span>,
            <span key="created">
              {t('incidents.created_on', { date: dates.format(c.created_at) })}
            </span>,
          ]}
          tags={
            <Space wrap>
              {details?.risk && (
                <ToneTag tone={riskTone(details.risk)} testId="change-risk-chip">
                  {t('staged.risk_chip', { risk: t(`risk_level.${details.risk}`) })}
                </ToneTag>
              )}
              {pending > 0 && (
                // The status's own words ("Awaiting acceptance"), so the chip and the status
                // never name one state twice (QA-2026-11-11 F-09).
                <ToneTag tone="warning" testId="change-awaiting-approval">
                  {statusName(t, c.status)}
                </ToneTag>
              )}
              {/* REQ-CHG-107: its SLA's due time, once a policy gives it one. */}
              {c.resolution_due_at !== null && (
                <SlaTag
                  policyId={c.sla_policy_id}
                  dueAt={c.resolution_due_at}
                  state={c.resolution_sla_state}
                  resolvedAt={c.resolved_at}
                  format={dates.format}
                />
              )}
              {c.stage_path === EMERGENCY_PATH && (
                <ToneTag tone="error" icon={<ThunderboltOutlined />} testId="change-emergency">
                  {t('changes.emergency')}
                </ToneTag>
              )}
            </Space>
          }
        />
      }
      actions={actions}
      alerts={
        <Card size="small" data-testid="change-stages">
          {panel.data && <StageRail rail={panel.data.rail} testId="change-rail" />}
        </Card>
      }
      panel={<ChangeProperties change={c} />}
    >
      {moving && (
        <StagedMoveDialog
          path="changes"
          recordId={c.id}
          version={c.version}
          move={moving}
          notice={
            RAISING.has(moving.to_status) ? (
              <ApprovalPreview id={c.id} stage={moving.to_stage} />
            ) : undefined
          }
          onClose={() => {
            setMoving(undefined);
          }}
        />
      )}
      {overriding && (
        <EmergencyOverrideDialog
          id={c.id}
          version={c.version}
          onClose={() => {
            setOverriding(false);
          }}
        />
      )}
      <Tabs
        data-testid="change-tabs"
        destroyOnHidden
        activeKey={shown}
        onChange={(key) => {
          setParams(key === 'details' ? {} : { tab: key }, { replace: true });
        }}
        items={tabItems}
      />
    </RecordPage>
  );
}
