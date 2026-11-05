import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { AiSettings, AiSummary } from '@supportx/api-client';
import { fakeIncident, fakeIncidentCatalogue } from '@supportx/api-client/testing';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router';

import { AppearanceProvider } from '@supportx/ui';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';
import { DuplicatesPanel } from './DuplicatesPanel';
import { rememberTab } from './tabs';

// WP-038 screens: the conversation summary card (REQ-INC-137) and possible duplicates
// (REQ-INC-022, D-134).

const SESSION_USER = '01900000-0000-7000-8000-000000000101';
const ADMIN = fakeSession({ roles: ['tenant_admin', 'technician'] });
const ITEM = fakeIncident();
const settings = (summaryOn: boolean): AiSettings => ({
  enabled: true,
  disabled_features: summaryOn ? [] : ['conversation_summary'],
  mask_local: false,
  log_retention_days: 30,
  summary_sources: ['description', 'replies', 'public_notes'],
  version: 1,
  features: [{ code: 'conversation_summary', area: 'summaries', enabled: summaryOn }],
  provider: { name: 'fake', model: 'qwen3-4b', external: false },
});
const NONE: AiSummary = {
  summary: null,
  model: null,
  made_at: null,
  stale: false,
  includes_private: false,
  call_id: null,
  version: null,
};
const MADE: AiSummary = {
  summary: '- Outlook asks for the password since Monday.',
  model: 'qwen3-4b',
  made_at: '2026-11-04T10:00:00Z',
  stale: true,
  includes_private: false,
  call_id: '01900000-0000-7000-8000-00000000c001',
  version: 2,
};

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function record(summaryOn: boolean, summary: AiSummary, extra = {}) {
  window.history.pushState({}, '', `/incidents/${ITEM.id}`);
  rememberTab(SESSION_USER, 'details');
  const fake = consoleApi({
    me: ADMIN,
    routes: {
      'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() },
      'GET /api/v1/incidents/categories': { body: [] },
      [`GET /api/v1/incidents/${ITEM.id}`]: { body: ITEM, headers: { ETag: '"1"' } },
      'GET /api/v1/ai/settings': { body: settings(summaryOn) },
      [`GET /api/v1/ai/summaries/incident/${ITEM.id}`]: { body: summary },
      ...extra,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('the conversation summary card', () => {
  it('REQ-INC-137: offers to summarise, then shows the answer marked as AI-written', async () => {
    const fake = record(true, NONE, {
      [`POST /api/v1/ai/summaries/incident/${ITEM.id}/refresh`]: {
        body: { ...MADE, stale: false },
      },
    });
    render(<App />);
    expect((await screen.findByTestId('ai-summary-empty')).textContent).toContain('No summary yet');
    fireEvent.click(screen.getByTestId('ai-summary-refresh'));
    await waitFor(() => {
      expect(screen.getByTestId('ai-summary-text').textContent).toContain('Outlook asks');
    });
    expect(fake.find('POST', `/api/v1/ai/summaries/incident/${ITEM.id}/refresh`)).toHaveLength(1);
    expect(screen.getByTestId('ai-summary').textContent).toContain('Written by AI (qwen3-4b)');
    expect(screen.queryByTestId('ai-summary-stale')).toBeNull();
  });

  it('says when it is out of date, and is absent while the feature is off', async () => {
    record(true, MADE);
    render(<App />);
    expect((await screen.findByTestId('ai-summary-stale')).textContent).toBe(
      'Out of date: newer replies or notes',
    );
    restore();
    record(false, MADE);
    render(<App />);
    await screen.findAllByTestId('inc-heading');
    await waitFor(() => {
      expect(screen.queryAllByTestId('ai-summary')).toHaveLength(1); // the first render's only
    });
  });
});

function wrap(node: ReactNode) {
  return (
    <AppearanceProvider>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>
    </AppearanceProvider>
  );
}

describe('possible duplicates', () => {
  it('REQ-INC-022: lists them with labelled reasons and says how they were found', () => {
    consoleApi({
      me: ADMIN,
      routes: { 'GET /api/v1/incidents/settings': { body: fakeIncidentCatalogue() } },
    });
    render(
      wrap(
        <DuplicatesPanel
          found={{
            method: 'text',
            people: {},
            items: [
              {
                item: { ...ITEM, display_id: 'INC-7', subject: 'Outlook asks for a password' },
                score: 0.62,
                reasons: ['similar_subject', 'same_requester'],
              },
            ] as never,
          }}
        />,
      ),
    );
    const card = screen.getByTestId('inc-duplicates');
    expect(card.textContent).toContain('Possible duplicates');
    expect(card.textContent).toContain('Found by subject');
    expect(card.textContent).toContain('Similar subject');
    expect(card.textContent).toContain('Same requester in the last hour');
    expect(card.textContent).not.toMatch(/similar_subject|same_requester|text\b/);
    expect(screen.getByTestId('inc-duplicate-INC-7').textContent).toContain('INC-7');
  });

  it('shows nothing when nothing looks alike', () => {
    render(wrap(<DuplicatesPanel found={{ method: 'meaning', people: {}, items: [] }} />));
    expect(screen.queryByTestId('inc-duplicates')).toBeNull();
  });
});
