import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { consoleApi, fakeSession } from './test/api';

// Must-fix before the pilot (2026-10-28): administrators see when event delivery is stalled.

let restore: () => void = () => undefined;
const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });

function ready(eventDelivery: 'ok' | 'stalled') {
  return {
    status: 'ready',
    failed: [],
    degraded: eventDelivery === 'stalled' ? ['outbox_relay'] : [],
    event_delivery: eventDelivery,
    checks: {
      postgres: { status: 'ok', critical: true },
      nats: { status: 'ok', critical: true },
      outbox_relay: {
        status: eventDelivery === 'stalled' ? 'failed' : 'ok',
        reason: eventDelivery === 'stalled' ? 'disconnected' : null,
        critical: false,
      },
    },
  };
}

describe('event delivery stalled', () => {
  afterEach(() => {
    restore();
  });

  it('tells administrators which worker and why', async () => {
    const fake = consoleApi({
      me: ADMIN,
      routes: { 'GET /api/v1/ready': { body: ready('stalled') } },
    });
    restore = fake.restore;
    window.history.pushState({}, '', '/');
    render(<App />);
    const banner = await screen.findByTestId('event-delivery-banner');
    expect(banner.textContent).toContain('Event delivery is stalled');
    expect(banner.textContent).toContain(
      'Event relay: Cannot reach the database or the message bus',
    );
  });

  it('says nothing when delivery is fine, and nothing to technicians', async () => {
    let fake = consoleApi({ me: ADMIN, routes: { 'GET /api/v1/ready': { body: ready('ok') } } });
    restore = fake.restore;
    window.history.pushState({}, '', '/');
    const { unmount } = render(<App />);
    await screen.findByTestId('user-menu');
    expect(screen.queryByTestId('event-delivery-banner')).toBeNull();
    unmount();
    restore();
    fake = consoleApi({ routes: { 'GET /api/v1/ready': { body: ready('stalled') } } });
    restore = fake.restore;
    render(<App />);
    await screen.findByTestId('user-menu');
    expect(screen.queryByTestId('event-delivery-banner')).toBeNull();
    expect(fake.find('GET', '/api/v1/ready')).toHaveLength(0);
  });
});
