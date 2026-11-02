import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { KbVersion } from '@supportx/api-client';
import { fakeKbArticle, type FakeRoute } from '@supportx/api-client/testing';

import { App } from '../../App';
import { consoleApi, fakeSession } from '../../test/api';

// "Did this help?" and the Feedback tab (REQ-KB-069, WP-034 s1, D-125).

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

const READER = fakeArticle(false);
const EDITOR = fakeArticle(true);
const VERSION = (READER.published.en ?? {}) as KbVersion;
const VOTE = `/api/v1/knowledge/articles/${READER.id}/vote`;
const SCORES = `/api/v1/knowledge/articles/${READER.id}/votes`;

function fakeArticle(canEdit: boolean) {
  return fakeKbArticle({ can_edit: canEdit, can_approve: false, drafts: {} });
}

function open(article: ReturnType<typeof fakeKbArticle>, routes: Record<string, FakeRoute> = {}) {
  window.history.pushState({}, '', `/knowledge/articles/${article.id}`);
  const fake = consoleApi({
    me: fakeSession(),
    routes: {
      'GET /api/v1/knowledge/topics': { body: [] },
      'GET /api/v1/knowledge/types': { body: [] },
      'GET /api/v1/knowledge/approvals/count': { body: { count: 0 } },
      [`GET /api/v1/knowledge/articles/${article.id}`]: { body: article },
      [`GET /api/v1/knowledge/articles/${article.id}/versions`]: {
        body: Object.values(article.published),
      },
      [`PUT ${VOTE}`]: {
        body: {
          version_id: VERSION.id,
          helpful: true,
          reason: null,
          comment: null,
          updated_at: '2026-11-03T08:00:00Z',
        },
      },
      ...routes,
    },
  });
  restore = fake.restore;
  return fake;
}

describe('Did this help? (REQ-KB-069)', () => {
  it('a yes votes on the version shown', async () => {
    const fake = open(READER);
    render(<App />);
    fireEvent.click(await screen.findByTestId('kb-vote-yes'));
    await waitFor(() => {
      expect(fake.find('PUT', VOTE)).toHaveLength(1);
    });
    expect(fake.find('PUT', VOTE)[0]?.body).toEqual({
      version_id: VERSION.id,
      helpful: true,
      reason: null,
      comment: null,
    });
  });

  it('a no asks why, then sends the reason and the comment', async () => {
    const fake = open(READER);
    render(<App />);
    fireEvent.click(await screen.findByTestId('kb-vote-no'));
    const why = await screen.findByTestId('kb-vote-why');
    fireEvent.click(within(why).getByText('It is out of date'));
    fireEvent.change(screen.getByTestId('kb-vote-comment'), {
      target: { value: '  The menu moved.  ' },
    });
    fireEvent.click(screen.getByTestId('kb-vote-send'));
    await waitFor(() => {
      expect(fake.find('PUT', VOTE)).toHaveLength(1);
    });
    expect(fake.find('PUT', VOTE)[0]?.body).toEqual({
      version_id: VERSION.id,
      helpful: false,
      reason: 'out_of_date',
      comment: 'The menu moved.',
    });
  });

  it('a reader who voted sees their answer and may change it', async () => {
    open({
      ...READER,
      my_vote: {
        version_id: VERSION.id,
        helpful: true,
        reason: null,
        comment: null,
        updated_at: '2026-11-03T08:00:00Z',
      },
    });
    render(<App />);
    expect((await screen.findByTestId('kb-vote-done')).textContent).toContain(
      'You said this article helped',
    );
    fireEvent.click(screen.getByTestId('kb-vote-change'));
    expect(await screen.findByTestId('kb-vote-yes')).toBeDefined();
  });
});

describe('The Feedback tab', () => {
  it('editors see the score, each version and what readers said, never who', async () => {
    open(EDITOR, {
      [`GET ${SCORES}`]: {
        body: {
          helpful: 3,
          not_helpful: 1,
          versions: [
            { version_id: VERSION.id, language: 'en', number: 1, helpful: 3, not_helpful: 1 },
          ],
          feedback: [
            {
              version_number: 1,
              language: 'en',
              reason: 'steps_did_not_work',
              comment: 'Step 3 fails.',
              at: '2026-11-03T08:00:00Z',
            },
          ],
        },
      },
    });
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Feedback' }));
    expect((await screen.findByTestId('kb-feedback-score')).textContent).toBe(
      '3 of 4 readers found the current version helpful.',
    );
    const item = screen.getByTestId('kb-feedback-item');
    expect(item.textContent).toContain('The steps did not work');
    expect(item.textContent).toContain('Step 3 fails.');
  });

  it('readers who may not edit are told who sees scores, and nothing is fetched', async () => {
    const fake = open(READER);
    render(<App />);
    fireEvent.click(await screen.findByRole('tab', { name: 'Feedback' }));
    expect(
      await screen.findByText(
        'Scores and feedback are shown to those who edit or approve this article.',
      ),
    ).toBeDefined();
    expect(fake.find('GET', SCORES)).toHaveLength(0);
  });
});
