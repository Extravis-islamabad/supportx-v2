import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AiSettings } from '@supportx/api-client';
import { AppearanceProvider } from '@supportx/ui';

import { consoleApi, fakeSession } from '../../test/api';
import { WritingHelp } from './WritingHelp';
import { asParagraphs, plainText } from './writingText';

// WP-038 writing help (REQ-INC-136): a draft or the typed text improved, reviewed in a panel
// with Insert, Replace and Discard; nothing is sent from there.

const RECORD = '01900000-0000-7000-8000-00000000a001';
const CALL = '01900000-0000-7000-8000-00000000c001';
const settings = (off: string[] = []): AiSettings => ({
  enabled: true,
  disabled_features: off,
  mask_local: false,
  log_retention_days: 30,
  summary_sources: ['description', 'replies', 'public_notes'],
  version: 1,
  features: ['reply_draft', 'text_improve'].map((code) => ({
    code,
    area: 'writing' as const,
    enabled: !off.includes(code),
  })),
  provider: { name: 'fake', model: 'qwen3-4b', external: false },
});

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

function wrap(node: ReactNode) {
  return (
    <AppearanceProvider>
      <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>
    </AppearanceProvider>
  );
}

function api(off: string[] = []) {
  const fake = consoleApi({
    me: fakeSession({ roles: ['technician'] }),
    routes: {
      'GET /api/v1/ai/settings': { body: settings(off) },
      [`POST /api/v1/ai/writing/incident/${RECORD}`]: {
        body: {
          text: 'We are testing the fix.\n\nPlease try <again> tomorrow.',
          model: 'qwen3-4b',
          call_id: CALL,
        },
      },
      [`POST /api/v1/ai/calls/${CALL}/outcome`]: { status: 204 },
    },
  });
  restore = fake.restore;
  return fake;
}

describe('writing help', () => {
  it('turns HTML into text and text into safe paragraphs', () => {
    expect(plainText('<p>Hello <b>there</b></p>')).toBe('Hello there');
    // QA-2026-11-11 V-16: paragraphs and list items never run together ("device.Still").
    expect(
      plainText('<p>New MFA device.</p><p>Still stuck?</p><ul><li>One</li><li>Two</li></ul>'),
    ).toBe('New MFA device. Still stuck? One Two');
    expect(asParagraphs('One <b>\nline\n\nTwo')).toBe('<p>One &lt;b&gt;<br>line</p><p>Two</p>');
  });

  it('REQ-INC-136: a draft from an instruction, inserted after review, and the outcome kept', async () => {
    const fake = api();
    const insert = vi.fn();
    const replace = vi.fn();
    render(
      wrap(
        <WritingHelp recordId={RECORD} kind="reply" html="" insert={insert} replace={replace} />,
      ),
    );
    fireEvent.click(await screen.findByTestId('writing-help-open'));
    fireEvent.change(await screen.findByTestId('writing-help-instruction'), {
      target: { value: 'Say we are testing the fix' },
    });
    fireEvent.click(screen.getByTestId('writing-help-ask'));
    expect((await screen.findByTestId('writing-help-text')).textContent).toContain(
      'We are testing the fix.',
    );
    const [call] = fake.find('POST', `/api/v1/ai/writing/incident/${RECORD}`);
    expect(call?.body).toEqual({
      mode: 'draft',
      kind: 'reply',
      instruction: 'Say we are testing the fix',
    });
    fireEvent.click(screen.getByTestId('writing-help-insert'));
    expect(insert).toHaveBeenCalledWith(
      '<p>We are testing the fix.</p><p>Please try &lt;again&gt; tomorrow.</p>',
    );
    expect(replace).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/ai/calls/${CALL}/outcome`)[0]?.body).toEqual({
        outcome: 'accepted',
      });
    });
  });

  it('improving the typed text: translate needs a language; Discard is recorded', async () => {
    const fake = api(['reply_draft']); // only improving is on: no mode switch shown
    render(
      wrap(
        <WritingHelp
          recordId={RECORD}
          kind="note"
          html="<p>we fix it soon</p>"
          insert={vi.fn()}
          replace={vi.fn()}
        />,
      ),
    );
    fireEvent.click(await screen.findByTestId('writing-help-open'));
    expect(screen.queryByTestId('writing-help-mode')).toBeNull();
    fireEvent.click(screen.getByTestId('writing-help-ask'));
    await screen.findByTestId('writing-help-text');
    expect(fake.find('POST', `/api/v1/ai/writing/incident/${RECORD}`)[0]?.body).toEqual({
      mode: 'improve',
      kind: 'note',
      text: 'we fix it soon',
      style: 'correct',
    });
    fireEvent.click(screen.getByTestId('writing-help-discard'));
    await waitFor(() => {
      expect(fake.find('POST', `/api/v1/ai/calls/${CALL}/outcome`)[0]?.body).toEqual({
        outcome: 'discarded',
      });
    });
    expect(screen.queryByTestId('writing-help-answer')).toBeNull();
  });

  it('is absent while both writing features are off', async () => {
    api(['reply_draft', 'text_improve']);
    render(
      wrap(
        <WritingHelp recordId={RECORD} kind="reply" html="" insert={vi.fn()} replace={vi.fn()} />,
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByTestId('writing-help-open')).toBeNull();
  });
});
