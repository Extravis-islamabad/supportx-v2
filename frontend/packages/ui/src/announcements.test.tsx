import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@supportx/api-client';
import { fakeApi, problem } from '@supportx/api-client/testing';

import { AnnouncementBanners } from './announcements';
import { ConflictDialog, describeError } from './errors';
import { renderUi } from './test/render';

const item = (id: string, overrides: Record<string, unknown> = {}) => ({
  kind: 'public',
  id,
  display_id: `ANN-${id}`,
  title: `Title ${id}`,
  body: 'Line one\nLine two',
  severity: 'warning',
  show_as_banner: true,
  published_at: '2026-10-23T10:00:00Z',
  publish_until: null,
  visibility: 'live',
  next_change_in_seconds: null,
  ...overrides,
});

describe('conflict dialog', () => {
  it('says who changed which fields, in words, never codes', () => {
    const conflict = new ApiError(
      409,
      problem(409, 'version_conflict', {
        params: {
          expected_version: 1,
          current_version: 2,
          changed_by: 'Aisha Tech',
          changed_fields: 'title,severity',
          changed_at: '2026-10-23T10:15:00Z',
        },
      }),
      null,
    );
    renderUi(
      <ConflictDialog
        open
        error={conflict}
        fieldLabel={(field) => (field === 'title' ? 'Title' : 'Severity')}
        onReload={() => undefined}
        onKeepMine={() => undefined}
      />,
    );
    const who = screen.getByTestId('conflict-who').textContent;
    expect(who).toContain('Aisha Tech saved it at');
    expect(who).toContain('Changed: Title, Severity.');
    expect(who).not.toContain('title,severity');
  });

  it('without details (an older record) it still explains the conflict', () => {
    renderUi(
      <ConflictDialog
        open
        error={new ApiError(409, problem(409, 'version_conflict'), null)}
        onReload={() => undefined}
        onKeepMine={() => undefined}
      />,
    );
    expect(screen.queryByTestId('conflict-who')).toBeNull();
    expect(screen.getByText('Someone else changed this')).toBeDefined();
  });
});

describe('publish refusals', () => {
  it('explain the reason, not the code', () => {
    const t = (key: string) => key;
    const fourEyes = new ApiError(
      403,
      problem(403, 'permission_denied', { params: { reason: 'four_eyes' } }),
      null,
    );
    expect(describeError(fourEyes, t).detail).toBe('action_reason.four_eyes');
    const empty = new ApiError(
      409,
      problem(409, 'cannot_publish', { params: { reason: 'audience_empty' } }),
      null,
    );
    expect(describeError(empty, t)).toMatchObject({
      title: 'errors.cannot_publish',
      detail: 'action_reason.audience_empty',
    });
  });
});

describe('announcement banners', () => {
  let feed: { items: ReturnType<typeof item>[]; next_change_in_seconds: number | null };
  let api: ReturnType<typeof fakeApi>;
  beforeEach(() => {
    feed = {
      items: [item('1'), item('2', { show_as_banner: false })],
      next_change_in_seconds: null,
    };
    api = fakeApi({ 'GET /api/v1/announcements/feed': () => ({ body: feed }) });
  });
  afterEach(() => {
    api.restore();
    localStorage.clear();
    vi.useRealTimers();
  });

  it('shows live banners only, with the severity in words, and can be dismissed', async () => {
    renderUi(<AnnouncementBanners />);
    expect(await screen.findByTestId('announcement-banner-1')).toBeDefined();
    expect(screen.queryByTestId('announcement-banner-2')).toBeNull(); // not marked as banner
    expect(screen.getByText('Warning: Title 1')).toBeDefined();
    fireEvent.click(screen.getByRole('button', { name: /close/i }));
    await waitFor(() => {
      expect(screen.queryByTestId('announcement-banner-1')).toBeNull();
    });
    expect(localStorage.getItem('supportx.announcements.dismissed')).toContain('1@');
  });

  it('refetches when the server says the feed changes (a scheduled start), with no reload', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    feed = { items: [], next_change_in_seconds: 60 };
    renderUi(<AnnouncementBanners />);
    await waitFor(() => {
      expect(api.find('GET', '/api/v1/announcements/feed')).toHaveLength(1);
    });
    expect(screen.queryByTestId('announcement-banners')).toBeNull();
    feed = { items: [item('3', { severity: 'critical' })], next_change_in_seconds: null };
    await act(async () => {
      await vi.advanceTimersByTimeAsync(61_000);
    });
    expect(await screen.findByText('Critical: Title 3')).toBeDefined();
    expect(api.find('GET', '/api/v1/announcements/feed')).toHaveLength(2);
  });

  it('makes no call when the plan does not include it', () => {
    renderUi(<AnnouncementBanners enabled={false} />);
    expect(api.find('GET', '/api/v1/announcements/feed')).toHaveLength(0);
  });
});
