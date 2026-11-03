import { describe, expect, it } from 'vitest';

import { ar, arByModule } from './ar';
import { en, enByModule } from './en';
import { ur, urByModule } from './ur';
import urMissing from './ur-missing.json';

// Each module keeps its labels in <module>/<lang>.ts (README.md). The language files spread them
// into one dictionary, where a key in two modules would silently win once: never allowed.

const PLURAL = /_(zero|one|two|few|many|other)$/;
const base = (key: string) => key.replace(PLURAL, '');
type ByModule = Record<string, Record<string, unknown>>;

/** English keys (a plural family counts once) with no translation at all in `resource`. */
function missing(resource: Record<string, string | undefined>): string[] {
  const present = new Set(Object.keys(resource).map(base));
  return [
    ...new Set(
      Object.keys(en)
        .filter((key) => !(key in resource) && !present.has(base(key)))
        .map(base),
    ),
  ].sort();
}

describe('label modules', () => {
  it.each([
    ['en', enByModule],
    ['ar', arByModule],
    ['ur', urByModule],
  ] as const)('no %s key is in two modules', (_lang, byModule) => {
    const seen = new Map<string, string>();
    const twice: string[] = [];
    for (const [module, labels] of Object.entries(byModule as ByModule)) {
      for (const key of Object.keys(labels)) {
        const first = seen.get(key);
        if (first !== undefined) twice.push(`${key} (${first} and ${module})`);
        seen.set(key, module);
      }
    }
    expect(twice).toEqual([]);
  });

  it('a key lives in the same module in every language', () => {
    const home = new Map<string, string>();
    for (const [module, labels] of Object.entries(enByModule)) {
      for (const key of Object.keys(labels)) home.set(base(key), module);
    }
    const strays: string[] = [];
    for (const [lang, byModule] of [
      ['ar', arByModule],
      ['ur', urByModule],
    ] as const) {
      for (const [module, labels] of Object.entries(byModule as ByModule)) {
        for (const key of Object.keys(labels)) {
          const owner = home.get(base(key));
          if (owner !== undefined && owner !== module) {
            strays.push(`${lang}: ${key} in ${module}, English has it in ${owner}`);
          }
        }
      }
    }
    expect(strays).toEqual([]);
  });

  it('every English key has Arabic', () => {
    expect(missing(ar)).toEqual([]);
  });

  it('Urdu misses only the frozen list, which only shrinks (translate, then delete the line)', () => {
    // New keys always need Urdu. The 370 older ones are translated before the pilot (D-006).
    expect(missing(ur)).toEqual([...urMissing].sort());
  });
});
