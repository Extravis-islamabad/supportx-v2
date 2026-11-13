import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { fakeApi } from '@supportx/api-client/testing';
import { useForm } from '@supportx/forms';

import { useServerDraft } from './useServerDraft';

// WP-046a S5c (REQ-INC-019), lane C's #495 review: with no key on the server (503) the save is
// tried again when the wait is over, even if the person has stopped typing.

const PUT = 'PUT /api/v1/drafts/incident-new';
let restore: () => void = () => undefined;
afterEach(() => {
  restore();
  vi.useRealTimers();
});

function Harness() {
  const form = useForm<{ subject: string }>({ defaultValues: { subject: '' } });
  useServerDraft(form, 'incident-new', { localRestored: false });
  return (
    <>
      <input aria-label="subject" {...form.register('subject')} />
      <button
        type="button"
        onClick={() => {
          form.setValue('subject', 'From the template'); // what a template or rule does
        }}
      >
        template
      </button>
    </>
  );
}

function type(text: string) {
  fireEvent.change(screen.getByRole('textbox', { name: 'subject' }), { target: { value: text } });
}

describe('useServerDraft', () => {
  it('a refused save is tried again after its back-off, with no more typing', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const fake = fakeApi({
      'GET /api/v1/drafts/incident-new': {
        status: 404,
        body: { code: 'draft_not_found', message_key: 'errors.draft_not_found' },
      },
      [PUT]: {
        status: 503,
        body: { code: 'field_keys_unavailable', message_key: 'errors.field_keys_unavailable' },
      },
    });
    restore = fake.restore;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    act(() => {
      type('Printer on fire');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100); // the pause after typing
    });
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_500); // the first back-off, nothing typed
    });
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(2);
  });

  it('after a conflict the typing is saved once more on the read version, never in a loop', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const fake = fakeApi({
      'GET /api/v1/drafts/incident-new': {
        status: 404,
        body: { code: 'draft_not_found', message_key: 'errors.draft_not_found' },
      },
      [PUT]: {
        status: 409,
        body: { code: 'version_conflict', message_key: 'errors.version_conflict' },
      },
    });
    restore = fake.restore;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    act(() => {
      type('Printer on fire');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100);
    });
    // The first save, the read after its 409, then one more save; a second 409 stops there.
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(2);
  });

  it('values a template or rule sets are not kept until the person types', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    const fake = fakeApi({
      'GET /api/v1/drafts/incident-new': {
        status: 404,
        body: { code: 'draft_not_found', message_key: 'errors.draft_not_found' },
      },
      [PUT]: {
        status: 200,
        body: {
          form_key: 'incident-new',
          version: 1,
          updated_at: '2026-11-13T10:00:00Z',
          unreadable: false,
          values: null,
        },
      },
    });
    restore = fake.restore;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: 'template' }));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(0);
    act(() => {
      type('Printer on fire');
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_100);
    });
    expect(fake.find('PUT', '/api/v1/drafts/incident-new')).toHaveLength(1);
  });
});
