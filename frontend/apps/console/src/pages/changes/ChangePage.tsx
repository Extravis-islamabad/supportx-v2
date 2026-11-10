import { useQueryClient } from '@tanstack/react-query';
import { DownOutlined, SwapOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { Button, Card, Dropdown, Flex, Result, Skeleton, Space, Tabs, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router';

import {
  changeKeys,
  useChange,
  useChangeDetails,
  useStagedApprovals,
  useStagedPanel,
  type StageMove,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  RecordHeader,
  RecordPage,
  StageRail,
  ToneTag,
  WriteButton,
  reportError,
  useDateTime,
  useLabel,
  usePageCrumbs,
  SPACE,
} from '@supportx/ui';

import { IncidentHistory } from '../incidents/IncidentHistory';
import { personName } from '../incidents/labels';
import { stageName, statusName } from '../releases/labels';
import { StagedMoveDialog } from '../staged/MoveDialog';
import { ChangeProperties } from './ChangeProperties';
import {
  DetailsPart,
  DowntimePart,
  PlanPart,
  RiskPart,
  RolesPart,
  SchedulePart,
} from './ChangeParts';
import { EMERGENCY_PATH, riskTone } from './labels';

const CANCELED = 'closure_canceled';
const TABS = ['details', 'risk', 'roles', 'plan', 'schedule', 'downtime', 'history'] as const;
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
  const approvals = useStagedApprovals('changes', id);
  const details = useChangeDetails(id).data;
  const dates = useDateTime();
  const pending = (approvals.data?.items ?? []).filter((a) => a.state === 'pending').length;
  const [moving, setMoving] = useState<StageMove>();
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
  // One clear primary action, the next stage (D-155); every other move is under "More".
  const next = positive.find((m) => m.to_stage !== c.stage) ?? positive[0];
  const overflow = [...positive.filter((m) => m !== next), ...allowed.filter(ending)];
  const unavailable = moves.filter((m) => !m.allowed);
  const moveLabel = (m: StageMove) =>
    m.to_stage !== c.stage
      ? t('releases.move.to_stage', { stage: stageName(t, m.to_stage) })
      : t('releases.move.to', { status: statusName(t, m.to_status) });
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
      {(overflow.length > 0 || unavailable.length > 0) && (
        <Dropdown
          trigger={['click']}
          menu={{
            items: [
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
                      label: t('releases.move.unavailable'),
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
    </Flex>
  );
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
                  {t('releases.risk_chip', { risk: t(`risk_level.${details.risk}`) })}
                </ToneTag>
              )}
              {pending > 0 && (
                <ToneTag tone="warning" testId="change-awaiting-approval">
                  {t('releases.awaiting_approval', { count: pending })}
                </ToneTag>
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
          onClose={() => {
            setMoving(undefined);
          }}
        />
      )}
      <Tabs
        data-testid="change-tabs"
        destroyOnHidden
        activeKey={tab}
        onChange={(key) => {
          setParams(key === 'details' ? {} : { tab: key }, { replace: true });
        }}
        items={[
          { key: 'details', label: t('releases.tab.details'), children: <DetailsPart id={c.id} /> },
          { key: 'risk', label: t('changes.tab.risk'), children: <RiskPart id={c.id} /> },
          { key: 'roles', label: t('releases.tab.roles'), children: <RolesPart id={c.id} /> },
          { key: 'plan', label: t('changes.tab.plans'), children: <PlanPart id={c.id} /> },
          {
            key: 'schedule',
            label: t('releases.tab.schedule'),
            children: <SchedulePart id={c.id} />,
          },
          {
            key: 'downtime',
            label: t('releases.tab.downtime'),
            children: <DowntimePart id={c.id} />,
          },
          {
            key: 'history',
            label: t('changes.tab.history'),
            children: <IncidentHistory id={c.id} base="changes" />,
          },
        ]}
      />
    </RecordPage>
  );
}
