import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-030 s3: approve or reject from an e-mail link; the token travels only in the body.

const TOKEN = 'A'.repeat(21) + '-_' + 'z'.repeat(20);
const RECORD = '01a1a2b3-0000-7000-8000-00000000c501';

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function api(peek: unknown) {
  const fake = consoleApi({
    routes: {
      'POST /api/v1/action-links/peek': peek as never,
      'POST /api/v1/action-links/use': { body: { state: 'approved', record_id: RECORD } },
    },
  });
  restore = fake.restore;
  return fake;
}

const opened = {
  body: {
    action: 'service_request.approval',
    object_type: 'work_item_approval',
    object_id: '01a1a2b3-0000-7000-8000-00000000a001',
    expires_at: '2026-11-07T08:00:00Z',
    summary: {
      record_id: RECORD,
      display_id: 'SR-7',
      subject: 'Laptop for Sara',
      comments_required: false,
      can_decide: true,
    },
  },
};

describe('console: approval by link', () => {
  it('reads the token from the fragment, hides it, and approves only on a click', async () => {
    window.history.pushState({}, '', `/requests/approval-link#${TOKEN}`);
    const fake = api(opened);
    render(<App />);
    expect((await screen.findByTestId('action-link-summary')).textContent).toContain('SR-7');
    expect(window.location.hash).toBe(''); // gone from the address bar and history
    const [peeked] = fake.find('POST', '/api/v1/action-links/peek');
    expect(peeked?.body).toEqual({ token: TOKEN });
    expect(peeked?.url.toString()).not.toContain(TOKEN);
    expect(fake.find('POST', '/api/v1/action-links/use')).toHaveLength(0); // opening never acts
    fireEvent.click(screen.getByTestId('action-link-approve'));
    await screen.findByTestId('action-link-done');
    const [used] = fake.find('POST', '/api/v1/action-links/use');
    expect(used?.body).toEqual({
      token: TOKEN,
      body: { decision: 'approve', comment: null, private: false },
    });
  });

  it('says in words why a link does nothing', async () => {
    window.history.pushState({}, '', `/requests/approval-link#${TOKEN}`);
    api({
      status: 409,
      body: {
        type: 'about:blank',
        title: 'Conflict',
        status: 409,
        code: 'action_link_revoked',
        message_key: 'errors.action_link_revoked',
        params: {},
        errors: [],
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('action-link-refused').textContent).toContain(
        'This is no longer needed',
      );
    });
  });
});
