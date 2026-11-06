import { useQueryClient } from '@tanstack/react-query';
import { MoreOutlined, RocketOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { Button, Card, Dropdown, Flex, Result, Skeleton, Space, Tabs, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  releaseKeys,
  useRelease,
  useReleaseApprovals,
  useStagePanel,
  type StageMove,
} from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import {
  RecordHeader,
  RecordPage,
  ToneTag,
  WriteButton,
  reportError,
  useLabel,
} from '@supportx/ui';

import { EMERGENCY_PATH, stageName, statusName } from './labels';
import { MoveDialog } from './MoveDialog';
import {
  ApprovalsPart,
  DetailsPart,
  DowntimePart,
  PlanPart,
  RolesPart,
  SchedulePart,
  SubReleasesPart,
} from './ReleaseParts';
import { ReleaseProperties } from './ReleaseProperties';
import { StageRail } from './StageRail';

// Beside "More": the page's 4-action rule (UI pass 2; QA6-REL-01).
const MAX_SHOWN = 3;
const CANCELED = 'closure_canceled';

/**
 * One release (WP-058a s6): its stage rail and the moves offered from where it is (ADR-041 §7),
 * and its parts as tabs. Everything refreshes live on the record channel: a move, a decision, a
 * role or a sub-release's progress (REQ-REL-037 AC3). Disabled moves say why (REQ-WI-010).
 */
export function ReleasePage() {
  const t = useLabel();
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const record = useRelease(id);
  const panel = useStagePanel(id);
  const approvals = useReleaseApprovals(id);
  const pendingApprovals = (approvals.data?.items ?? []).filter(
    (a) => a.state === 'pending',
  ).length;
  const [moving, setMoving] = useState<StageMove>();
  useRecordChannel('wi', id === '' ? undefined : id, () => {
    void queryClient.invalidateQueries({ queryKey: releaseKeys.detail(id) });
  });
  // Once per error, not on every render (lane A's review of #219).
  useEffect(() => {
    if (record.error) reportError(record.error);
  }, [record.error]);
  if (record.isLoading) return <Skeleton active />;
  if (record.data === undefined) {
    return (
      <Result
        status="404"
        title={t('releases.not_found')}
        extra={<Link to="/releases">{t('nav.releases')}</Link>}
      />
    );
  }
  const r = record.data;
  const moves = panel.data?.moves ?? [];
  const allowed = moves.filter((m) => m.allowed);
  // Canceling ends the release: never beside the positive moves, always in "More" (QA6-REL-01).
  const ending = (m: StageMove) => m.to_status === CANCELED;
  const positive = allowed.filter((m) => !ending(m));
  const shown = positive.slice(0, MAX_SHOWN);
  const primary = shown[0]?.to_status;
  const overflow = [...positive.slice(MAX_SHOWN), ...allowed.filter(ending)];
  const unavailable = moves.filter((m) => !m.allowed);
  // A move reads as an action ("Move to: …"), never as the status it leads to (QA6-REL-02).
  const moveLabel = (m: StageMove) => t('releases.move.to', { status: statusName(t, m.to_status) });
  const actions = (
    <Flex gap={8} wrap justify="flex-end" data-testid="release-moves">
      {shown.map((m) => {
        const Write = m.to_status === primary ? WriteButton : Button;
        return (
          <Write
            key={m.to_status}
            type={m.to_status === primary ? 'primary' : 'default'}
            data-testid={`move-${m.to_status}`}
            onClick={() => {
              setMoving(m);
            }}
          >
            {moveLabel(m)}
          </Write>
        );
      })}
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
              // Moves not possible now, each saying why (REQ-WI-010), out of the way.
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
          <Button icon={<MoreOutlined />} data-testid="release-more">
            {t('actions.more')}
          </Button>
        </Dropdown>
      )}
    </Flex>
  );
  return (
    <RecordPage
      testId="release-page"
      header={
        <RecordHeader
          icon={<RocketOutlined />}
          typeLabel={t('nav.releases')}
          displayId={r.display_id}
          title={r.subject}
          tags={
            <Space wrap>
              <ToneTag tone="info" testId="release-stage">
                {stageName(t, r.stage)}
              </ToneTag>
              <ToneTag tone="default" testId="release-status">
                {statusName(t, r.status)}
              </ToneTag>
              {pendingApprovals > 0 && (
                <ToneTag tone="warning" testId="release-awaiting-approval">
                  {t('releases.awaiting_approval', { count: pendingApprovals })}
                </ToneTag>
              )}
              {r.stage_path === EMERGENCY_PATH && (
                <ToneTag tone="error" icon={<ThunderboltOutlined />} testId="release-emergency">
                  {t('releases.emergency')}
                </ToneTag>
              )}
            </Space>
          }
        />
      }
      actions={actions}
      alerts={
        // The rail has the page's full width, so all nine stages stay readable (QA6-REL-01).
        <Card size="small" data-testid="release-stages">
          {panel.data && <StageRail rail={panel.data.rail} />}
        </Card>
      }
      panel={<ReleaseProperties id={r.id} release={r} />}
    >
      {moving && (
        <MoveDialog
          releaseId={r.id}
          version={r.version}
          move={moving}
          onClose={() => {
            setMoving(undefined);
          }}
        />
      )}
      <Tabs
        data-testid="release-tabs"
        destroyOnHidden
        items={[
          { key: 'details', label: t('releases.tab.details'), children: <DetailsPart id={r.id} /> },
          { key: 'roles', label: t('releases.tab.roles'), children: <RolesPart id={r.id} /> },
          { key: 'plan', label: t('releases.tab.plan'), children: <PlanPart id={r.id} /> },
          {
            key: 'schedule',
            label: t('releases.tab.schedule'),
            children: <SchedulePart id={r.id} />,
          },
          {
            key: 'downtime',
            label: t('releases.tab.downtime'),
            children: <DowntimePart id={r.id} />,
          },
          {
            key: 'approvals',
            label: t('releases.tab.approvals'),
            children: <ApprovalsPart id={r.id} />,
          },
          {
            key: 'sub-releases',
            label: t('releases.tab.sub_releases'),
            children: <SubReleasesPart id={r.id} />,
          },
        ]}
      />
    </RecordPage>
  );
}
