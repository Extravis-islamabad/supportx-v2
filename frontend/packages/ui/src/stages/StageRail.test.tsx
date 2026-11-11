import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { RailStage } from '@supportx/api-client';

import { renderUi } from '../test/render';
import { StageRail } from './StageRail';

// One rail for releases and changes (the coordinator, 2026-11-11): stage names from the labels,
// the current stage marked, rounds and optional stages said, each stage's state.

const RAIL: RailStage[] = [
  {
    stage: 'submission',
    state: 'done',
    optional: false,
    entries: [
      { entered_at: '2026-11-01T09:00:00Z', left_at: '2026-11-02T09:00:00Z' },
      { entered_at: '2026-11-03T09:00:00Z', left_at: '2026-11-04T09:00:00Z' },
    ],
  },
  { stage: 'planning', state: 'current', optional: false, entries: [] },
  { stage: 'build', state: 'skipped', optional: true, entries: [] },
  { stage: 'testing', state: 'future', optional: false, entries: [] },
];

describe('StageRail', () => {
  it('names each stage, marks the current one and says rounds, skips and optional stages', () => {
    renderUi(<StageRail rail={RAIL} testId="rail" />);
    expect(screen.getByTestId('rail').getAttribute('data-current')).toBe('planning');
    expect(screen.getByTestId('rail-planning').textContent).toBe('Planning');
    expect(screen.getByTestId('rail-submission-state').textContent).toContain('2 rounds');
    expect(screen.getByTestId('rail-build-state').textContent).toBe('Skipped');
    expect(screen.getByText('Optional')).toBeTruthy();
    expect(screen.queryByText(/^(work_item_stage|stage_rail|rail_state)\./)).toBeNull(); // rule d
  });
});
