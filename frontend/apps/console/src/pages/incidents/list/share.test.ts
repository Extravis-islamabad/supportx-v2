import { describe, expect, it } from 'vitest';

import type { Unit } from '@supportx/api-client';
import { contrastRatio } from '@supportx/ui';

import { MARK_CONTRAST, readableMark, shareAudiences, type HeldPermission } from './model';

// D-176: who may share a saved view with whom (the server checks the same on save).
const ME = 'me';
const group = (id: string, members: string[], lead: string | null = null): Unit => ({
  id,
  name: id,
  member_ids: members,
  disabled: false,
  version: 1,
  lead_id: lead,
});
const GROUPS = [
  group('mine', [ME]), // a member, not its lead
  group('led', ['someone'], ME), // its lead, not a member
  group('other', ['someone']), // neither
];
const held = (...grants: [string, HeldPermission['scope']][]): HeldPermission[] =>
  grants.map(([key, scope]) => ({ key, scope }));
const shown = (permissions: HeldPermission[]) => {
  const found = shareAudiences(permissions, 'incidents', ME, GROUPS);
  return { everyone: found.everyone, groups: [...found.groupIds].sort() };
};

describe('D-176: share audiences', () => {
  it('a technician shares with the groups they are in, never everyone', () => {
    expect(shown(held(['incidents.share_views', 'group']))).toEqual({
      everyone: false,
      groups: ['mine'],
    });
  });

  it('a team lead adds the groups they lead (member or lead OK, neither not, never everyone)', () => {
    expect(
      shown(held(['incidents.share_views', 'group'], ['incidents.share_views_wide', 'group'])),
    ).toEqual({ everyone: false, groups: ['led', 'mine'] });
  });

  it('a service desk manager shares with everyone and every group', () => {
    expect(shown(held(['incidents.share_views_wide', 'all']))).toEqual({
      everyone: true,
      groups: ['led', 'mine', 'other'],
    });
  });

  it('a requester, or another type’s right, gives nothing', () => {
    expect(shown([])).toEqual({ everyone: false, groups: [] });
    expect(shown(held(['changes.share_views_wide', 'all']))).toEqual({
      everyone: false,
      groups: [],
    });
  });

  it('a disabled group is never offered', () => {
    const found = shareAudiences(held(['incidents.share_views_wide', 'all']), 'incidents', ME, [
      { ...group('gone', [ME]), disabled: true },
    ]);
    expect([...found.groupIds]).toEqual([]);
  });
});

describe('REQ-INC-115 AC1: a row colour reads against the row', () => {
  it('keeps a colour that already reads, and darkens one that does not', () => {
    expect(readableMark('#cf1322', '#ffffff', contrastRatio)).toBe('#cf1322'); // P1 red
    const gold = readableMark('#fadb14', '#ffffff', contrastRatio);
    expect(gold).not.toBe('#fadb14');
    expect(gold).toBeDefined();
    expect(contrastRatio(gold ?? '', '#ffffff')).toBeGreaterThanOrEqual(MARK_CONTRAST);
  });

  it('gives no mark for a colour that is not #rrggbb', () => {
    expect(readableMark('gold', '#ffffff', contrastRatio)).toBeUndefined();
    expect(readableMark('#fff', '#ffffff', contrastRatio)).toBeUndefined();
  });

  it('lightens instead in dark mode', () => {
    const navy = readableMark('#10239e', '#141414', contrastRatio, true);
    expect(navy).toBeDefined();
    expect(contrastRatio(navy ?? '', '#141414')).toBeGreaterThanOrEqual(MARK_CONTRAST);
  });
});
