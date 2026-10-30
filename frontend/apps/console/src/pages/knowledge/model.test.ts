import { describe, expect, it } from 'vitest';

import { fakeKbArticle } from '@supportx/api-client/testing';
import type { KbTopic, KbVersion } from '@supportx/api-client';

import {
  articleLanguage,
  audienceWords,
  headings,
  historyField,
  shownLanguage,
  stepBlocked,
  subtreeIds,
  topicPath,
  topicTree,
  type UnitNames,
} from './model';

// WP-033 session 3a: the knowledge screens' rules, without rendering.

const topic = (id: string, parent: string | null, en: string, order = 0, ar?: string): KbTopic =>
  ({
    id,
    parent_id: parent,
    names: ar === undefined ? { en } : { en, ar },
    sort_order: order,
  }) as unknown as KbTopic;

const EN = (fakeKbArticle().published.en ?? {}) as KbVersion;

const TOPICS = [
  topic('net', null, 'Network', 1, 'الشبكة'),
  topic('mail', null, 'Mail', 0),
  topic('vpn', 'net', 'VPN', 0),
  topic('wifi', 'net', 'Wi-Fi', 1),
  topic('tokens', 'vpn', 'Tokens', 0),
];
const t = (key: string, params?: Record<string, string>) =>
  params === undefined ? key : `${key}(${Object.values(params).join('|')})`;
const list = (items: readonly string[]) => items.join(' & ');

describe('topics', () => {
  it('builds the tree in order, in the reader language, falling back to English', () => {
    const tree = topicTree(TOPICS, 'ar');
    expect(tree.map((n) => n.title)).toEqual(['Mail', 'الشبكة']);
    expect(tree[1]?.children.map((n) => n.title)).toEqual(['VPN', 'Wi-Fi']);
    expect(tree[1]?.children[0]?.children.map((n) => n.key)).toEqual(['tokens']);
  });

  it('names the path down to a topic and finds a subtree (never move under yourself)', () => {
    expect(topicPath(TOPICS, 'tokens', 'en')).toEqual(['Network', 'VPN', 'Tokens']);
    expect([...subtreeIds(TOPICS, 'net')].sort()).toEqual(['net', 'tokens', 'vpn', 'wifi']);
  });

  it('reads articles in Arabic on Arabic and Urdu screens', () => {
    expect(articleLanguage('ar')).toBe('ar');
    expect(articleLanguage('ur')).toBe('ar');
    expect(articleLanguage('en')).toBe('en');
  });
});

describe('REQ-KB-078: the audience in plain words', () => {
  const units: UnitNames = {
    groups: new Map([['g1', 'Network team']]),
    sites: new Map([['s1', 'Riyadh']]),
    departments: new Map([['d1', 'Finance']]),
  };

  it('says who reads it, by name, and leaves out units that are gone', () => {
    expect(
      audienceWords(
        {
          tech_all: false,
          tech_groups: ['g1', 'gone'],
          requesters: 'selected',
          req_sites: ['s1'],
          req_departments: ['d1'],
        },
        units,
        t,
        list,
      ),
    ).toEqual({
      technicians: 'knowledge.audience.groups(Network team)',
      requesters: 'knowledge.audience.requesters_in(Riyadh & Finance)',
    });
    expect(audienceWords({ tech_all: true, requesters: 'none' }, units, t, list)).toEqual({
      technicians: 'knowledge.audience.all_technicians',
      requesters: 'knowledge.audience.no_requesters',
    });
  });
});

describe('the article page', () => {
  it('shows the wanted language when it exists, else the default one', () => {
    const article = fakeKbArticle();
    expect(shownLanguage(article, 'ar')).toBe('en');
    const both = fakeKbArticle({
      drafts: { ar: { ...EN, language: 'ar', status: 'draft' } },
    });
    expect(shownLanguage(both, 'ar')).toBe('ar');
  });

  it('lists the headings for the table of contents', () => {
    expect(headings('<h2>One</h2><p>x</p><h3>Two</h3><h4>Three</h4>')).toEqual([
      { level: 2, text: 'One', index: 0 },
      { level: 3, text: 'Two', index: 1 },
      { level: 4, text: 'Three', index: 2 },
    ]);
  });

  it('labels history fields, version fields with their language', () => {
    expect(historyField('version.ar.status', t)).toBe(
      'knowledge.history.version_status(knowledge.language.ar)',
    );
    expect(historyField('review_on', t)).toBe('knowledge.field.review_on');
  });
});

describe('buttons never vanish: each says why it is off', () => {
  const published = fakeKbArticle();
  const inReview = fakeKbArticle({
    drafts: { en: { ...EN, number: 2, status: 'in_review' } },
  });

  it('a reader who may not edit', () => {
    const reader = fakeKbArticle({ can_edit: false });
    expect(stepBlocked('edit', reader, 'en')).toBe('knowledge.why.not_editor');
    expect(stepBlocked('approve', reader, 'en')).toBe('knowledge.why.not_approver');
    expect(stepBlocked('withdraw', reader, 'en')).toBe('knowledge.why.not_withdrawer');
  });

  it('the author: submit needs a draft, and a version in review is locked', () => {
    expect(stepBlocked('submit', published, 'en')).toBe('knowledge.why.no_draft');
    expect(stepBlocked('submit', inReview, 'en')).toBe('knowledge.why.already_in_review');
    expect(stepBlocked('still_correct', published, 'en')).toBeNull();
  });

  it('an approver decides only what is in review; withdraw needs something published', () => {
    const approver = { ...inReview, can_approve: true, can_withdraw: true };
    expect(stepBlocked('approve', approver, 'en')).toBeNull();
    expect(stepBlocked('reject', { ...published, can_approve: true }, 'en')).toBe(
      'knowledge.why.nothing_in_review',
    );
    expect(stepBlocked('withdraw', approver, 'ar')).toBe('knowledge.why.not_published');
    expect(stepBlocked('withdraw', { ...approver, withdrawn: true }, 'en')).toBe(
      'knowledge.why.already_withdrawn',
    );
  });
});
