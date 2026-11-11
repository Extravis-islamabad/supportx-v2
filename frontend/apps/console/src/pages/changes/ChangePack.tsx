import { PrinterOutlined } from '@ant-design/icons';
import { Button, Descriptions, Flex, Result, Skeleton, Table, Typography } from 'antd';
import { useEffect, type ReactNode } from 'react';
import { Link, useParams } from 'react-router';

import {
  useChange,
  useChangeConflicts,
  useChangeDetails,
  useStagedApprovals,
  useStagedDowntimes,
  useStagedPlan,
  useStagedSchedule,
  useStagedSettings,
  type StageSchedule,
} from '@supportx/api-client';
import {
  EmptyText,
  RichTextView,
  ToneTag,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { personName } from '../incidents/labels';
import { listValueName, stageName, statusName } from '../staged/labels';
import { ConflictsPanel } from './ChangeSchedule';
import { riskTone } from './labels';

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`pack-${id}`} data-testid={`pack-${id}`}>
      <Typography.Title level={2} id={`pack-${id}`} style={{ fontSize: 18 }}>
        {title}
      </Typography.Title>
      {children}
    </section>
  );
}

/**
 * The CAB pack (REQ-CHG-102): one page with what a board needs to decide, ready for the
 * browser's print or "Save as PDF". The summary, the risk with its score, the plans, the
 * schedule, its conflicts, the downtime (the impact), and the approvals so far, all in the reader's language
 * and direction. The app's print rules leave out the navigation and the print button.
 */
export function ChangePack() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { format } = useDateTime();
  const { id = '' } = useParams();
  const record = useChange(id);
  const details = useChangeDetails(id).data;
  const plan = useStagedPlan('changes', id).data ?? [];
  const schedule = useStagedSchedule('changes', id).data ?? [];
  const downtimes = useStagedDowntimes('changes', id).data ?? [];
  const approvals = useStagedApprovals('changes', id).data;
  const settings = useStagedSettings('changes');
  const conflicts = useChangeConflicts(id).data?.items ?? [];
  const c = record.data;
  usePageCrumbs([
    { label: t('nav.changes'), path: '/changes' },
    ...(c ? [{ label: c.display_id, path: `/changes/${c.id}` }] : []),
    { label: t('changes.pack.title') },
  ]);
  useEffect(() => {
    if (record.error) reportError(record.error);
  }, [record.error]);
  if (record.isLoading) return <Skeleton active />;
  if (c === undefined) {
    return <Result status="404" title={t('changes.not_found')} />;
  }
  const own = (list: string, code: string | null | undefined) =>
    code
      ? listValueName(
          t,
          locale,
          list,
          settings.data?.own_lists?.[list]?.find((v) => v.code === code),
          code,
        )
      : t('changes.pack.not_set');
  const risk = details?.risk_chosen ?? details?.risk ?? null;
  // A person's own words for setting the risk by hand (free text, REQ-CHG-060).
  const handReason = details?.risk_chosen ? (details.risk_reason ?? '') : '';
  const when = (value: string | null | undefined) => (value ? format(value) : '');
  const written = plan.filter((s) => Boolean(s.content));
  const people = approvals?.people ?? {};
  return (
    <Flex vertical gap={24} data-testid="change-pack" style={{ maxWidth: 960 }}>
      <Flex justify="space-between" align="flex-start" gap={16} wrap>
        <div>
          <Typography.Text type="secondary">{t('changes.pack.title')}</Typography.Text>
          <Typography.Title level={1} style={{ fontSize: 24, marginTop: 4 }}>
            <bdi dir="ltr">{c.display_id}</bdi> {c.subject}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t('changes.pack.printed', { at: format(new Date().toISOString()) })}
          </Typography.Text>
        </div>
        <Flex gap={8} data-sx-no-print>
          <Link to={`/changes/${c.id}`}>{t('changes.pack.back')}</Link>
          <Button
            type="primary"
            icon={<PrinterOutlined aria-hidden />}
            onClick={() => {
              window.print();
            }}
            data-testid="pack-print"
          >
            {t('changes.pack.print')}
          </Button>
        </Flex>
      </Flex>

      <Section id="summary" title={t('changes.pack.summary')}>
        <Descriptions size="small" column={{ xs: 1, md: 2 }} bordered>
          <Descriptions.Item label={t('work_item.field.change_type')}>
            {own('change_type', details?.change_type)}
          </Descriptions.Item>
          <Descriptions.Item label={t('changes.col.path')}>
            {c.stage_path ? t(`stage_path.${c.stage_path}`) : ''}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item.field.stage')}>
            {stageName(t, c.stage)}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item.field.status')}>
            {statusName(t, c.status)}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item_role.change_owner')}>
            {c.technician_id ? personName(c.people, c.technician_id) : t('changes.pack.not_set')}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item.field.requester_id')}>
            {personName(c.people, c.requester_id)}
          </Descriptions.Item>
          <Descriptions.Item label={t('work_item.field.change_reason')}>
            {own('change_reason', details?.change_reason)}
          </Descriptions.Item>
        </Descriptions>
        {c.description ? (
          <div style={{ marginTop: 12 }}>
            <RichTextView html={c.description} testId="pack-description" />
          </div>
        ) : null}
      </Section>

      <Section id="risk" title={t('changes.pack.risk')}>
        <Flex gap={12} align="center" wrap>
          {risk ? (
            <ToneTag tone={riskTone(risk)} testId="pack-risk-level">
              {t('staged.risk_chip', { risk: t(`risk_level.${risk}`) })}
            </ToneTag>
          ) : (
            <Typography.Text type="secondary">{t('changes.pack.not_set')}</Typography.Text>
          )}
          {details?.risk_score !== null && details?.risk_score !== undefined && (
            <Typography.Text data-testid="pack-risk-score">
              {t('changes.risk.score', { score: details.risk_score })}
            </Typography.Text>
          )}
        </Flex>
        {handReason ? (
          <Typography.Paragraph style={{ marginTop: 8 }} data-testid="pack-risk-reason">
            {t('changes.pack.risk_reason', { reason: handReason })}
          </Typography.Paragraph>
        ) : null}
      </Section>

      <Section id="plans" title={t('changes.tab.plans')}>
        {written.length === 0 ? (
          <EmptyText>{t('staged.plan.none_yet')}</EmptyText>
        ) : (
          written.map((s) => (
            <div
              key={s.section}
              data-testid={`pack-plan-${s.section}`}
              style={{ marginBottom: 16 }}
            >
              <Typography.Title level={3} style={{ fontSize: 15 }}>
                {t(`plan_section.${s.section}`)}
              </Typography.Title>
              <RichTextView html={s.content ?? ''} />
            </div>
          ))
        )}
      </Section>

      <Section id="schedule" title={t('staged.tab.schedule')}>
        <Table<StageSchedule>
          rowKey="stage"
          size="small"
          pagination={false}
          dataSource={schedule}
          locale={{ emptyText: <EmptyText>{t('changes.pack.no_schedule')}</EmptyText> }}
          columns={[
            {
              key: 'stage',
              title: t('work_item.field.stage'),
              render: (_, r) => stageName(t, r.stage),
            },
            {
              key: 'planned',
              title: t('staged.schedule.planned'),
              render: (_, r) =>
                [when(r.scheduled_start), when(r.scheduled_end)].filter(Boolean).join(' – '),
            },
            {
              key: 'actual',
              title: t('staged.schedule.actual'),
              render: (_, r) =>
                [when(r.actual_start), when(r.actual_end)].filter(Boolean).join(' – '),
            },
            {
              key: 'outcome',
              title: t('staged.schedule.outcome'),
              render: (_, r) => (r.outcome ? t(`stage_outcome.${r.outcome}`) : ''),
            },
          ]}
        />
      </Section>

      <Section id="conflicts" title={t('changes.pack.conflicts')}>
        {conflicts.length === 0 ? (
          <EmptyText>{t('changes.pack.no_conflicts')}</EmptyText>
        ) : (
          <ConflictsPanel id={c.id} />
        )}
      </Section>

      <Section id="impact" title={t('changes.pack.impact')}>
        {downtimes.length === 0 ? (
          <EmptyText>{t('staged.downtime.none')}</EmptyText>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 20 }}>
            {downtimes.map((d) => (
              <li key={d.id} data-testid={`pack-downtime-${d.id}`}>
                {own('downtime_kind', d.kind)}: {when(d.starts_at)} – {when(d.ends_at)}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section id="approvals" title={t('staged.tab.approvals')}>
        {(approvals?.items ?? []).length === 0 ? (
          <EmptyText>{t('changes.pack.no_approvals')}</EmptyText>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 20 }}>
            {(approvals?.items ?? []).map((a) => (
              <li key={a.id} data-testid={`pack-approval-${a.id}`}>
                {stageName(t, a.record_stage)} ·{' '}
                {a.approver_id
                  ? personName(people, a.approver_id)
                  : t('changes.approvals.administrators')}{' '}
                · {t(`approval_state.${a.state}`)}
                {a.decided_at ? ` · ${format(a.decided_at)}` : ''}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </Flex>
  );
}
