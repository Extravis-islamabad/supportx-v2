import { renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { LabelsProvider } from '@supportx/labels';

import { useAutomationWhy } from './automationWhy';

const BILAL = '01900000-0000-7000-8000-0000000003c2';
const people = { [BILAL]: { display_name: 'Bilal Ahmed', email: 'bilal@demo.test' } };

describe('the why-line of an automated change', () => {
  it('D-154 rules: a step that could not assign its person says who and why', () => {
    const { result } = renderHook(() => useAutomationWhy(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <LabelsProvider locale="en">{children}</LabelsProvider>
      ),
    });
    const why = result.current(
      {
        kind: 'sla_escalation',
        target: 'resolution',
        level: 2,
        unavailable: 'away',
        person_id: BILAL,
      },
      people,
    );
    expect(why).toContain('level 2');
    expect(why).toContain('Bilal Ahmed is Away, so it went to the group with nobody on it');
    const rule = result.current(
      {
        kind: 'business_rule',
        rule: 'Send to Bilal',
        unavailable: 'not_in_group',
        person_id: BILAL,
      },
      people,
    );
    expect(rule).toContain('Send to Bilal');
    expect(rule).toContain('not in that group any more');
    // A code the screen does not know is never shown.
    expect(
      result.current(
        { kind: 'business_rule', rule: 'R', unavailable: 'zzz', person_id: BILAL },
        people,
      ),
    ).not.toContain('zzz');
  });
});
