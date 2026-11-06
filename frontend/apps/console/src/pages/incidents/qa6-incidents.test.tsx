import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';

import { AppearanceProvider } from '@supportx/ui';

import { SlaTag } from './tags';

// QA6 (2026-11-06) incident fixes, each test named after its bug.

const format = (iso: string | null) => iso ?? '';
const shown = (node: ReactNode) => render(<AppearanceProvider>{node}</AppearanceProvider>);
const POLICY = '01a1a2b3-0000-7000-8000-0000000051a1';
const DUE = '2026-11-10T12:00:00Z';

describe('QA6 incidents', () => {
  it('QA6-INC-03: a resolved incident says it was resolved on time, with no countdown', () => {
    shown(
      <SlaTag
        policyId={POLICY}
        dueAt={DUE}
        state="met"
        resolvedAt="2026-11-06T09:00:00Z"
        format={format}
      />,
    );
    const tag = screen.getByTestId('inc-due');
    expect(tag.textContent).toBe('Resolved on time');
    expect(tag.getAttribute('data-state')).toBe('resolved_on_time');
    expect(screen.queryByRole('timer')).toBeNull();
  });

  it('QA6-INC-03: resolved after the due moment reads as late', () => {
    shown(
      <SlaTag
        policyId={POLICY}
        dueAt={DUE}
        state="breached"
        resolvedAt="2026-11-11T09:00:00Z"
        format={format}
      />,
    );
    expect(screen.getByTestId('inc-due').textContent).toBe('Resolved late');
  });

  it('QA6-INC-03: an open incident still counts down', () => {
    shown(
      <SlaTag policyId={POLICY} dueAt="2999-01-01T00:00:00Z" state="running" format={format} />,
    );
    expect(screen.getByRole('timer').textContent).toMatch(/^Due in /);
  });
});
