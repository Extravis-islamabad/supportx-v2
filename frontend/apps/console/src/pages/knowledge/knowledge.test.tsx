import { render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { KbVersion } from '@supportx/api-client';
import { fakeKbArticle } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession, problem } from '../../test/api';

// WP-033 session 3a: knowledge home and the article page, through the whole app.

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const ADMIN = fakeSession({ display_name: 'Amal Admin', roles: ['tenant_admin', 'technician'] });
const ARTICLE = fakeKbArticle();
const EN = (ARTICLE.published.en ?? {}) as KbVersion;
const TOPIC = {
  id: ARTICLE.topic_id,
  parent_id: null,
  depth: 1,
  sort_order: 0,
  names: { en: 'Network', ar: 'الشبكة' },
  description: null,
  icon: null,
  owner_id: null,
  tech_all: true,
  tech_groups: [],
  requesters: 'none',
  req_groups: [],
  req_sites: [],
  req_departments: [],
  version: 1,
};
const TYPES = [{ code: 'how_to', names: {}, builtin: true, retired: false, review_months: 12 }];
const COMMON = {
  'GET /api/v1/knowledge/topics': { body: [TOPIC] },
  'GET /api/v1/knowledge/types': { body: TYPES },
  'GET /api/v1/knowledge/approvals/count': { body: { count: 3 } },
  'GET /api/v1/organization/groups': { body: [] },
  'GET /api/v1/organization/sites': { body: [] },
  'GET /api/v1/organization/departments': { body: [] },
};

function api(me: ReturnType<typeof fakeSession>, routes: Record<string, unknown>) {
  const fake = consoleApi({ me, routes: { ...COMMON, ...routes } });
  restore = fake.restore;
  return fake;
}

describe('Knowledge home (REQ-KB-077)', () => {
  it('lists articles with labels, never codes, beside the topic tree', async () => {
    window.history.pushState({}, '', '/knowledge');
    api(ADMIN, {
      'GET /api/v1/knowledge/articles': {
        body: [
          {
            id: ARTICLE.id,
            display_id: 'KB-1',
            topic_id: TOPIC.id,
            type_code: 'how_to',
            language: 'en',
            title: 'Reset your VPN token',
            status: 'in_review',
            review_on: '2026-10-29',
            updated_at: '2026-10-29T08:00:00Z',
            owner_id: ARTICLE.owner_id,
            expired: false,
            withdrawn: true,
            review_due: true,
          },
        ],
      },
    });
    render(<App />);
    const table = await screen.findByTestId('kb-table');
    const row = await within(table).findByText('Reset your VPN token');
    const line = row.closest('tr');
    expect(line).not.toBeNull();
    const cells = within(line as HTMLElement);
    expect(cells.getByText('In review')).toBeDefined();
    expect(cells.getByText('How-to')).toBeDefined();
    expect(cells.getByText('Withdrawn')).toBeDefined();
    expect(cells.getByText('Network')).toBeDefined();
    // A withdrawn article is never marked "review due" as well.
    expect(cells.queryByText('Review due')).toBeNull();
    expect(line?.textContent).not.toMatch(/in_review|how_to/);
    expect(within(await screen.findByTestId('kb-tree')).getByText('Network')).toBeDefined();
  });
});

describe('The article page', () => {
  const page = (article: ReturnType<typeof fakeKbArticle>) => {
    window.history.pushState({}, '', `/knowledge/articles/${article.id}`);
    return {
      [`GET /api/v1/knowledge/articles/${article.id}`]: { body: article },
      [`GET /api/v1/knowledge/articles/${article.id}/versions`]: {
        body: Object.values(article.published),
      },
      [`GET /api/v1/knowledge/articles/${article.id}/history`]: {
        body: { items: [], next_cursor: null },
      },
    };
  };

  it('shows the body with contents, the audience in words and the owner', async () => {
    api(fakeSession(), page(ARTICLE));
    render(<App />);
    expect((await screen.findByTestId('kb-heading')).textContent).toBe('Reset your VPN token');
    expect(within(await screen.findByTestId('kb-toc')).getByText('Steps')).toBeDefined();
    const panel = await screen.findByTestId('kb-panel');
    expect(within(panel).getByText('Tariq Technician')).toBeDefined();
    expect((await screen.findByTestId('kb-audience')).textContent).toContain('All technicians');
    expect(screen.getByTestId('kb-path').textContent).toContain('Network');
  });

  it('keeps buttons the author may not use, saying why', async () => {
    api(fakeSession(), page(ARTICLE));
    render(<App />);
    const approve = await screen.findByTestId('kb-action-approve');
    expect(approve.hasAttribute('disabled')).toBe(true);
    expect(
      screen.getByLabelText(/Approve and publish: Only the topic owner or an approver can decide/),
    ).toBeDefined();
    expect(screen.getByTestId('kb-action-still_correct').hasAttribute('disabled')).toBe(false);
  });

  it('reads an Arabic article right to left, whatever the screen language', async () => {
    const arabic = fakeKbArticle({
      default_language: 'ar',
      published: {
        ar: {
          ...EN,
          language: 'ar',
          title: 'إعادة تعيين رمز VPN',
          body_html: '<p>افتح البوابة.</p>',
        },
      },
    });
    api(fakeSession(), page(arabic));
    render(<App />);
    const heading = await screen.findByTestId('kb-heading');
    expect(heading.getAttribute('dir')).toBe('rtl');
    expect(screen.getByTestId('kb-body').closest('[dir="rtl"]')).not.toBeNull();
    // English was wanted (the screen language) but only Arabic exists: the page says so.
    expect(await screen.findByTestId('kb-fallback')).toBeDefined();
  });

  it('a withdrawn article on an old link: "no longer available"', async () => {
    window.history.pushState({}, '', `/knowledge/articles/${ARTICLE.id}`);
    api(fakeSession(), {
      [`GET /api/v1/knowledge/articles/${ARTICLE.id}`]: {
        status: 404,
        body: problem(404, 'kb_article_withdrawn'),
      },
    });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByTestId('kb-not-available').textContent).toContain(
        'This article is no longer available.',
      );
    });
  });
});
