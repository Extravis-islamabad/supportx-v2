import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeEntitlements, fakeSession } from '@supportx/api-client/testing';

import { App } from './App';

// WP-046a S5b (REQ-INC-037): the template's rules over the requester's own fields apply on the
// portal form too, with the evaluator the server runs on save.

const BASE = {
  'GET /api/v1/auth/me': { body: fakeSession({ user_type: 'requester', roles: ['requester'] }) },
  'GET /api/v1/entitlements': { body: fakeEntitlements() },
  'GET /api/v1/announcements/feed': { body: { items: [], next_change_in_seconds: null } },
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

describe('portal: form rules', () => {
  it('a rule makes the description required once the subject is written', async () => {
    window.history.pushState({}, '', '/requests/new');
    const fake = fakeApi({
      ...BASE,
      'GET /api/v1/portal/incidents/templates': {
        body: [
          {
            id: 't1',
            code: 'standard',
            labels: null,
            description: null,
            is_default: true,
            fields: [
              { name: 'subject', required: true },
              { name: 'description', required: false },
            ],
            form_rules: [
              {
                id: 'explain',
                when: { field: 'subject', op: 'is_not_null' },
                then: [{ do: 'require', field: 'description', value: null, keep_value: null }],
              },
            ],
          },
        ],
      },
    });
    restore = fake.restore;
    render(<App />);
    const subject = await screen.findByTestId('portal-report-subject');
    fireEvent.change(subject, { target: { value: 'Laptop will not start' } });
    await waitFor(() => {
      expect(screen.getByTestId('portal-report-why').textContent).toBe(
        'Describe the issue to send it.',
      );
    });
    expect(screen.getByTestId<HTMLButtonElement>('portal-report-send').disabled).toBe(true);
  });
});
