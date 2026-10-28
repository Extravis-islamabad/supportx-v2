import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AppearanceProvider } from './AppearanceProvider';

// Dropdown options wrap only between words (product owner, 2026-10-28: "tab / le / sta / ck" in
// narrow lists). The layout itself is measured by e2e/tests/dropdown-wrap.spec.ts; these checks
// keep the rules that cause it out of the code.

function pageCss(): string {
  const { container } = render(
    <AppearanceProvider initialMode="light">
      <span />
    </AppearanceProvider>,
  );
  return [...container.ownerDocument.querySelectorAll('style')]
    .map((s) => s.textContent)
    .join('\n');
}

function optionRule(css: string): string {
  const match = /\.ant-select-item-option-content\s*\{([^}]*)\}/.exec(css);
  expect(match, 'a rule for option text').not.toBeNull();
  return match?.[1] ?? '';
}

describe('dropdown options never break inside a word', () => {
  it('option text wraps only between words', () => {
    const rule = optionRule(pageCss());
    expect(rule).not.toMatch(/overflow-wrap:\s*(anywhere|break-word)/);
    expect(rule).not.toMatch(/word-break:\s*(break-all|break-word)/);
    expect(rule).toMatch(/word-break:\s*normal/);
    expect(rule).toMatch(/overflow-wrap:\s*normal/);
    expect(rule).toMatch(/text-overflow:\s*ellipsis/); // a single word too long: ellipsis
  });

  it('popups may grow past their field, up to 360 px and never past the screen', () => {
    const css = pageCss();
    const popup = /\.ant-select-dropdown\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(popup).toMatch(/width:\s*max-content\s*!important/);
    expect(popup).toMatch(/max-width:\s*min\(360px,\s*calc\(100vw - 16px\)\)/);
  });

  it('no dropdown or menu rule in the apps or packages breaks words anywhere', () => {
    const root = resolve(__dirname, '../../..');
    const offenders: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        if (name === 'node_modules' || name === 'dist' || name.startsWith('.')) continue;
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (/\.(tsx?|css)$/.test(name) && !name.endsWith('.test.tsx')) {
          // Hashes and pasted URLs in text may break anywhere; dropdowns and menus never.
          const text = readFileSync(path, 'utf8');
          const breaking = /overflow-?[wW]rap:?\s*['"]?anywhere|word-?[bB]reak:?\s*['"]?break-all/g;
          for (const found of text.matchAll(breaking)) {
            const before = text.slice(Math.max(0, found.index - 300), found.index);
            if (/select|dropdown|option|menu/i.test(before))
              offenders.push(path.slice(root.length + 1));
          }
        }
      }
    };
    for (const top of ['apps', 'packages']) walk(join(root, top));
    expect(offenders).toEqual([]);
  });
});
