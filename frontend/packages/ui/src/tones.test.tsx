import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ToneTag } from './ToneTag';
import { contrastRatio, TAG_TONES, TONES, type Tone } from './tones';
import { renderUi } from './test/render';
import type { ThemeMode } from './theme';

// QA BUG-01 (WP-020b): coloured tags must pass WCAG AA (4.5:1 for normal text) in every theme.
// This is the automated contrast check for tag colours: a new tone or a palette change that
// drops below 4.5:1 fails here, without a browser.

const MODES: ThemeMode[] = ['light', 'dark', 'high_contrast'];

describe('BUG-01: tag colours', () => {
  it('computes WCAG contrast ratios', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0);
    expect(contrastRatio('#faad14', '#fffbe6')).toBeCloseTo(1.82, 1); // the failing QA pair
  });

  for (const mode of MODES) {
    it(`BUG-01: every tag tone passes WCAG AA in ${mode}`, () => {
      for (const tone of TONES) {
        const { color, background, border } = TAG_TONES[mode][tone];
        expect(contrastRatio(color, background), `${mode} ${tone} text`).toBeGreaterThanOrEqual(
          mode === 'high_contrast' ? 7 : 4.5,
        );
        // The border tells the tag apart from the page (WCAG 1.4.11: 3:1 for UI parts).
        expect(contrastRatio(border, background), `${mode} ${tone} border`).toBeGreaterThan(1);
      }
    });
  }

  it('BUG-01: ToneTag renders the readable colours of the current theme', () => {
    renderUi(
      <ToneTag tone="warning" testId="tag">
        Private note
      </ToneTag>,
    );
    const tag = screen.getByTestId('tag');
    expect(tag.getAttribute('data-tone')).toBe('warning');
    expect(tag.style.color).toBe('rgb(135, 77, 0)');
  });

  it('an unknown tone (a status the map does not know) falls back to the neutral one', () => {
    const fromData: Record<string, string> = {};
    renderUi(
      <ToneTag tone={fromData.new_status as Tone} testId="tag">
        New status
      </ToneTag>,
    );
    expect(screen.getByTestId('tag').style.color).toBe('rgb(38, 38, 38)');
  });
});
