import { RocketOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Card, Flex, Result, Skeleton, Space, Tabs, Tooltip } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import { releaseKeys, useRelease, useStagePanel, type StageMove } from '@supportx/api-client';
import { useRecordChannel } from '@supportx/realtime';
import { RecordHeader, ToneTag, WriteButton, reportError, useLabel } from '@supportx/ui';

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
import { StageRail } from './StageRail';

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
  // The first allowed move is the page's one primary action (visual QA: one per screen).
  const primary = moves.find((m) => m.allowed)?.to_status;
  return (
    <Flex vertical gap={16} style={{ width: '100%' }} data-testid="release-page">
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
            {r.stage_path === EMERGENCY_PATH && (
              <ToneTag tone="error" icon={<ThunderboltOutlined />} testId="release-emergency">
                {t('releases.emergency')}
              </ToneTag>
            )}
          </Space>
        }
      />
      <Card size="small" data-testid="release-stages">
        {panel.data && <StageRail rail={panel.data.rail} />}
        <Flex gap={8} wrap style={{ marginTop: 12 }} data-testid="release-moves">
          {moves.map((m) => {
            const Write = m.to_status === primary ? WriteButton : Button;
            return (
              <Tooltip
                key={m.to_status}
                title={m.allowed ? undefined : t(`action_reason.${m.reason ?? 'no_permission'}`)}
              >
                <Write
                  type={m.to_status === primary ? 'primary' : 'default'}
                  danger={m.to_status === 'closure_canceled'}
                  disabled={!m.allowed}
                  data-testid={`move-${m.to_status}`}
                  onClick={() => {
                    setMoving(m);
                  }}
                >
                  {statusName(t, m.to_status)}
                </Write>
              </Tooltip>
            );
          })}
        </Flex>
      </Card>
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
    </Flex>
  );
}
