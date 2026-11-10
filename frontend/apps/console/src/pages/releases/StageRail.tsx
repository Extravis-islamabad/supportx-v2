import { Steps, Tag } from 'antd';

import type { RailStage } from '@supportx/api-client';
import { useDateTime, useLabel } from '@supportx/ui';

import { stageName } from './labels';

const STATUS = {
  done: 'finish',
  current: 'process',
  skipped: 'wait',
  future: 'wait',
} as const;

/**
 * The release's stages on its path, in order (ADR-041 §7): done, current, skipped or not yet,
 * with when each was entered. Computed by the server, never stored; live through the record.
 */
export function StageRail({ rail }: { rail: RailStage[] }) {
  const t = useLabel();
  const { format } = useDateTime();
  const current = rail.findIndex((s) => s.state === 'current');
  return (
    <Steps
      size="small"
      current={current < 0 ? 0 : current}
      // Labels under each stage, wrapping between words: "Acceptance testing" is never cut
      // mid-word (D-155; the coordinator's check of #338's shots).
      labelPlacement="vertical"
      responsive
      data-testid="release-rail"
      // The current stage, for tests and tools (the header's stage chip is gone, D2).
      data-current={rail[current]?.stage}
      items={rail.map((stage) => {
        const last = stage.entries.at(-1);
        return {
          title: (
            <span
              data-testid={`rail-${stage.stage}`}
              title={stageName(t, stage.stage)}
              style={{ whiteSpace: 'normal', overflowWrap: 'normal', wordBreak: 'normal' }}
            >
              {stageName(t, stage.stage)}
            </span>
          ),
          status: STATUS[stage.state],
          subTitle: stage.optional ? <Tag>{t('releases.rail.optional')}</Tag> : undefined,
          description: (
            <span data-testid={`rail-${stage.stage}-state`}>
              {stage.state === 'skipped'
                ? t('rail_state.skipped')
                : last !== undefined
                  ? format(last.entered_at)
                  : t(`rail_state.${stage.state}`)}
              {stage.entries.length > 1 &&
                ` · ${t('releases.rail.rounds', { count: stage.entries.length })}`}
            </span>
          ),
        };
      })}
    />
  );
}
