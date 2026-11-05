import { QueryClient } from '@tanstack/react-query';
import { afterEach, describe, expect, it } from 'vitest';

import { fakeApi, fakeUser, problem } from './testing';
import { saveOwnPreference } from './users';

// QA 2026-11-05 V3: two preference saves at once (the start-up resends, a quick language and
// layout change) read the same version, and the second got a 409 shown as "someone else saved
// this item". Saves now run one after another, and a 409 reads the version again and retries.

const ID = '01900000-0000-7000-8000-000000000101';
const PATH = `/api/v1/users/${ID}`;

let restore: () => void = () => undefined;
afterEach(() => {
  restore();
});

/** A user record whose version moves on with each save, refusing a stale If-Match. */
function server(conflictsFirst = 0) {
  let version = 3;
  let conflicts = conflictsFirst;
  const fake = fakeApi({
    [`GET ${PATH}`]: () => ({ body: fakeUser({ version }) }),
    [`PATCH ${PATH}`]: (call) => {
      const sent = Number((call.headers.get('If-Match') ?? '').replaceAll('"', ''));
      if (sent !== version || conflicts > 0) {
        conflicts = Math.max(0, conflicts - 1);
        if (conflicts === 0 && sent === version) version += 1; // someone else saved meanwhile
        return { status: 409, body: problem(409, 'version_conflict') };
      }
      version += 1;
      return { body: fakeUser({ version }) };
    },
  });
  restore = fake.restore;
  return fake;
}

describe('saving one person preference at a time', () => {
  it('runs saves made at once one after another, each with the version it read', async () => {
    const fake = server();
    const client = new QueryClient();
    await Promise.all([
      saveOwnPreference(client, ID, { ui_locale: 'ar' }),
      saveOwnPreference(client, ID, { nav_layout: 'top' }),
    ]);
    const patches = fake.find('PATCH', PATH);
    expect(patches.map((c) => c.headers.get('If-Match'))).toEqual(['"3"', '"4"']);
    expect(patches.map((c) => c.body)).toEqual([{ ui_locale: 'ar' }, { nav_layout: 'top' }]);
  });

  it('reads the version again after a conflict and sends the same field once more', async () => {
    const fake = server(1);
    const client = new QueryClient();
    const saved = await saveOwnPreference(client, ID, { theme_mode: 'dark' });
    expect(saved.version).toBe(5);
    const patches = fake.find('PATCH', PATH);
    expect(patches).toHaveLength(2);
    expect(patches.every((c) => JSON.stringify(c.body) === '{"theme_mode":"dark"}')).toBe(true);
  });

  it('gives up after its retries, so a real refusal still reaches the person', async () => {
    server(10);
    const client = new QueryClient();
    await expect(saveOwnPreference(client, ID, { theme_mode: 'dark' })).rejects.toMatchObject({
      status: 409,
    });
  });
});
