import { describe, expect, it } from 'vitest';

import { buildTheme } from './theme';

// Full QA 2026-11-06, polish minors (shared UI).

describe('QA6S-SHELL-09: checkboxes are square, radios round', () => {
  it('gives checkboxes their own small radius', () => {
    const theme = buildTheme('light');
    expect(theme.components?.Checkbox?.borderRadiusSM).toBe(4);
  });
});
