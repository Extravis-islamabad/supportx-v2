import { Alert, Empty, List, Space, Typography } from 'antd';
import { useState } from 'react';

import { useIncidentAutomation, type AutomationRunOut } from '@supportx/api-client';
import { ToneTag, useDateTime, useLabel, type Tone } from '@supportx/ui';

import { useFieldName } from '../admin/automation/rules';

const SHOWN = new Set(['trigger', 'loop_guard']);
const LOOP_SHOWN_MS = 24 * 60 * 60 * 1000;
const TONE: Record<string, Tone> = {
  applied: 'success',
  partial: 'warning',
  failed: 'error',
  no_change: 'default',
  own_change: 'default',
  chain_depth: 'error',
  per_minute: 'error',
};

interface ActionOutcome {
  kind?: string;
  field?: string | null;
  outcome?: string;
  reason?: string;
}

/** Why an action did not apply, in words: its own reasons, a field check or an API error. */
function reasonKey(reason: string): string {
  if (reason === 'has_value' || reason === 'not_supported') return `automation.reason.${reason}`;
  if (reason === 'invalid_value' || reason.endsWith('_not_found')) return `errors.field.${reason}`;
  return `errors.${reason}`;
}

/** A recent loop stop on this record (REQ-RUL-028 AC1): named triggers, shown above the tabs. */
export function LoopWarning({ id }: { id: string }) {
  const t = useLabel();
  const runs = useIncidentAutomation(id);
  // When the record was opened: a stop older than a day there is history, not a warning.
  const [openedAt] = useState(() => Date.now());
  const stop = (runs.data ?? []).find(
    (r) => r.kind === 'loop_guard' && openedAt - Date.parse(r.occurred_at) < LOOP_SHOWN_MS,
  );
  if (stop === undefined) return null;
  const names = Array.isArray(stop.detail.triggers) ? (stop.detail.triggers as string[]) : [];
  return (
    <Alert
      type="warning"
      showIcon
      data-testid="inc-loop-warning"
      message={t('automation.loop.title')}
      description={t(`automation.loop.${stop.outcome}`, {
        triggers: names.join(t('list.separator')),
      })}
    />
  );
}

/**
 * What triggers and a move's "after" actions did on this record, each action with its outcome
 * (REQ-RUL-010), and loops the guard stopped (REQ-RUL-028). Live with the record's history.
 */
export function IncidentAutomation({ id }: { id: string }) {
  const t = useLabel();
  const field = useFieldName();
  const dates = useDateTime();
  const runs = useIncidentAutomation(id);
  const shown = (runs.data ?? []).filter((r) => SHOWN.has(r.kind) && r.outcome !== 'own_change');
  const title = (run: AutomationRunOut) => {
    if (run.kind === 'loop_guard') return t('automation.loop.title');
    if (run.detail.source === 'transition' && run.automation_name !== null) {
      return t('automation.after_move', {
        action: t(`work_item_action.${run.automation_name}`),
      });
    }
    return run.automation_name ?? t('automation.someone');
  };
  if (!runs.isPending && shown.length === 0) {
    return <Empty description={t('automation.panel.none')} data-testid="inc-automation-empty" />;
  }
  return (
    <List<AutomationRunOut>
      loading={runs.isPending}
      dataSource={shown}
      data-testid="inc-automation"
      renderItem={(run) => {
        const actions = Array.isArray(run.detail.actions)
          ? (run.detail.actions as ActionOutcome[])
          : [];
        return (
          <List.Item data-testid={`inc-automation-${run.id}`}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space wrap>
                <Typography.Text strong>
                  <bdi>{title(run)}</bdi>
                </Typography.Text>
                <ToneTag tone={TONE[run.outcome] ?? 'default'}>
                  {t(`automation_outcome.${run.outcome}`)}
                </ToneTag>
                <Typography.Text type="secondary">{dates.format(run.occurred_at)}</Typography.Text>
              </Space>
              {actions.map((action, index) => (
                <Typography.Text
                  // Outcomes have no ID; their order is the actions' order.
                  key={index}
                  type={action.outcome === 'failed' ? 'danger' : 'secondary'}
                  data-testid={`inc-automation-action-${String(index)}`}
                >
                  {action.kind === 'note'
                    ? t('automation.panel.note')
                    : t('automation.panel.set', { field: field(action.field ?? '') })}
                  {': '}
                  {t(`automation_outcome.${action.outcome ?? 'failed'}`)}
                  {action.reason !== undefined && ` (${t(reasonKey(action.reason))})`}
                </Typography.Text>
              ))}
            </Space>
          </List.Item>
        );
      }}
    />
  );
}
