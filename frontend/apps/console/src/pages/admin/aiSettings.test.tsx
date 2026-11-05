import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AiSettings } from '@supportx/api-client';
import { fakeSession, type FakeRoute } from '@supportx/api-client/testing';
import { inertClientFactory, setDefaultClientFactory } from '@supportx/realtime';
import { scriptedRealtime } from '@supportx/realtime/testing';

import { App } from '../../App';
import { consoleApi } from '../../test/api';

// WP-037: Admin › AI (REQ-AI-027, 018, 031).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  setDefaultClientFactory(inertClientFactory);
});

const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const SETTINGS: AiSettings = {
  enabled: true,
  disabled_features: [],
  mask_local: false,
  log_retention_days: 30,
  summary_sources: ['description', 'replies', 'public_notes'],
  version: 4,
  features: [
    { code: 'reply_draft', area: 'writing', enabled: true },
    { code: 'text_improve', area: 'writing', enabled: true },
    { code: 'conversation_summary', area: 'summaries', enabled: true },
    { code: 'possible_duplicates', area: 'predictions', enabled: true },
  ],
  provider: { name: 'fake', model: 'qwen3-4b', external: false },
};

function api(routes: Record<string, FakeRoute> = {}, me = ADMIN) {
  const fake = consoleApi({
    me,
    routes: { 'GET /api/v1/ai/settings': { body: SETTINGS }, ...routes },
  });
  restore = fake.restore;
  return fake;
}

describe('Admin › AI', () => {
  it('lists the features by area in labels, with the model and where it runs', async () => {
    window.history.pushState({}, '', '/admin/ai');
    api();
    render(<App />);
    const page = await screen.findByTestId('ai-settings');
    expect(within(page).getByRole('heading', { name: 'Writing' })).toBeDefined();
    expect(within(page).getByText('Conversation summary')).toBeDefined();
    expect(within(page).getByTestId('ai-model').textContent).toContain(
      'qwen3-4b (in your installation)',
    );
    expect(page.textContent).not.toMatch(/reply_draft|conversation_summary|summaries/);
  });

  it('switching a feature off asks first, says what happens, then saves with If-Match', async () => {
    window.history.pushState({}, '', '/admin/ai');
    const fake = api({
      'PATCH /api/v1/ai/settings': {
        body: { ...SETTINGS, disabled_features: ['conversation_summary'], version: 5 },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByTestId('ai-feature-conversation_summary'));
    const dialog = await screen.findByRole('dialog', {
      name: /Switch off “Conversation summary”\?/,
    });
    expect(dialog.textContent).toContain('Results already made stay in the history');
    expect(fake.find('PATCH', '/api/v1/ai/settings')).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Switch off' }));
    await waitFor(() => {
      expect(fake.find('PATCH', '/api/v1/ai/settings')).toHaveLength(1);
    });
    const [call] = fake.find('PATCH', '/api/v1/ai/settings');
    expect(call?.body).toEqual({ disabled_features: ['conversation_summary'] });
    expect(call?.headers.get('If-Match')).toBe('"4"');
  });

  it('follows another admin’s change live', async () => {
    const realtime = scriptedRealtime();
    setDefaultClientFactory(realtime.factory);
    window.history.pushState({}, '', '/admin/ai');
    const fake = api();
    render(<App />);
    await screen.findByTestId('ai-settings');
    await waitFor(() => {
      expect(realtime.channels().some((name) => name.endsWith(':broadcast'))).toBe(true);
    });
    const before = fake.find('GET', '/api/v1/ai/settings').length;
    act(() => {
      realtime.publish(':broadcast', { type: 'ai.settings_changed', ids: [] });
    });
    await waitFor(() => {
      expect(fake.find('GET', '/api/v1/ai/settings').length).toBeGreaterThan(before);
    });
  });

  it('is not offered to a technician', async () => {
    window.history.pushState({}, '', '/admin/ai');
    api({}, fakeSession());
    render(<App />);
    expect(await screen.findByText(/You do not have permission to do this\./)).toBeDefined();
  });
});
