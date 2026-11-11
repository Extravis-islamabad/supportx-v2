import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { LabelsProvider } from '@supportx/labels';
import { useLabel } from '@supportx/ui';

import { restoredStanding } from './slaWords';

describe('a restore says where the SLA stands (Haider, 2026-11-10)', () => {
  it('names each open target overdue, with time left, or paused; never met or stopped ones', () => {
    const { result } = renderHook(() => useLabel(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <LabelsProvider locale="en">{children}</LabelsProvider>
      ),
    });
    const now = Date.parse('2026-11-10T12:00:00Z');
    expect(
      restoredStanding(
        result.current,
        {
          first_response_sla_state: 'breached',
          first_response_due_at: '2026-11-10T09:00:00Z',
          resolution_sla_state: 'running',
          resolution_due_at: '2026-11-10T14:30:00Z',
        },
        now,
      ),
    ).toEqual(['First response overdue by 3 h 0 min', 'Resolution: 2 h 30 min left']);
    expect(
      restoredStanding(
        result.current,
        { first_response_sla_state: 'met', resolution_sla_state: 'paused' },
        now,
      ),
    ).toEqual(['Resolution paused']);
  });
});
