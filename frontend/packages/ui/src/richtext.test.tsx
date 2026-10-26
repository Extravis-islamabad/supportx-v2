import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { cleanPastedHtml, RichTextField } from './richtext';
import { renderUi } from './test/render';

// WP-020b: the richer editor and the paste cleaner (Word, Outlook, the web).

// jsdom has no layout: ProseMirror measures the caret when it scrolls to an insertion.
beforeAll(() => {
  const empty = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] });
  for (const proto of [Range.prototype, Element.prototype, Text.prototype] as object[]) {
    Object.assign(proto, {
      getClientRects: empty,
      getBoundingClientRect: () => new DOMRect(0, 0, 0, 0),
    });
  }
});

const WORD_LIST = `<html xmlns:o="urn:schemas-microsoft-com:office:office"><head>
<style>p.MsoNormal {font-family: Calibri}</style></head><body>
<!--[if gte mso 9]><xml><o:OfficeDocumentSettings/></xml><![endif]-->
<p class="MsoNormal" style="text-align:center"><b><span style="font-size:18pt;font-family:Arial;color:red">Outage report</span></b><o:p></o:p></p>
<p class="MsoListParagraphCxSpFirst" style="mso-list:l0 level1 lfo1"><span style="font-family:Symbol;mso-list:Ignore">·<span style="font:7.0pt">&nbsp;&nbsp;</span></span>Mail server down<o:p></o:p></p>
<p class="MsoListParagraphCxSpMiddle" style="mso-list:l0 level2 lfo1"><span style="mso-list:Ignore">o<span>&nbsp;</span></span>Since 9:00</p>
<p class="MsoListParagraphCxSpLast" style="mso-list:l0 level1 lfo1"><span style="mso-list:Ignore">·<span>&nbsp;</span></span>VPN slow</p>
<p class="MsoNormal">&nbsp;</p>
<p class="MsoListParagraph" style="mso-list:l1 level1 lfo2"><span style="mso-list:Ignore">1.<span>&nbsp;</span></span>Restart</p>
<p class="MsoListParagraph" style="mso-list:l1 level1 lfo2"><span style="mso-list:Ignore">2.<span>&nbsp;</span></span>Check</p>
<h1>Big title</h1><p><img src="cid:image001.png"><a href="https://example.com" style="color:blue" class="x">link</a></p>
</body></html>`;

describe('Pasting from Word, Outlook and the web', () => {
  it('keeps structure, drops fonts, sizes, colours, styles and Office tags', () => {
    const clean = cleanPastedHtml(WORD_LIST);
    expect(clean).not.toMatch(/style=|class=|font-family|<o:p|mso-|<img|<span|<b>/i);
    expect(clean).toContain('<p data-align="center"><strong>Outage report</strong></p>');
    expect(clean).toContain('<h2>Big title</h2>');
    expect(clean).toContain('<a href="https://example.com">link</a>');
  });

  it('turns Word bullet paragraphs into real, nested lists', () => {
    const doc = new DOMParser().parseFromString(cleanPastedHtml(WORD_LIST), 'text/html');
    const [bullets, numbers] = Array.from(doc.body.querySelectorAll(':scope > ul, :scope > ol'));
    expect(bullets?.tagName).toBe('UL');
    expect(
      Array.from(bullets?.querySelectorAll(':scope > li > p') ?? []).map((p) => p.textContent),
    ).toEqual(['Mail server down', 'VPN slow']);
    expect(bullets?.querySelector('li ul li')?.textContent).toBe('Since 9:00');
    expect(numbers?.tagName).toBe('OL');
    expect(Array.from(numbers?.querySelectorAll('li') ?? []).map((li) => li.textContent)).toEqual([
      'Restart',
      'Check',
    ]);
    // The spacing paragraph of non-breaking spaces is gone.
    expect(
      Array.from(doc.body.querySelectorAll('p')).every((p) => p.textContent.trim() !== ''),
    ).toBe(true);
  });

  it('cleans web pages too (divs, fonts, scripts)', () => {
    const clean = cleanPastedHtml(
      '<div style="color:red"><font size="7">Big</font> <i>it</i><script>alert(1)</script></div>',
    );
    expect(clean).toBe('Big <em>it</em>');
  });
});

describe('The rich-text editor (WP-020b)', () => {
  it('formats with codes: heading size, palette colour, highlight, alignment, indent', async () => {
    const changed = vi.fn<(html: string) => void>();
    renderUi(<RichTextField label="Note" value="<p>Hello</p>" onChange={changed} testId="ed" />);
    const area = await screen.findByTestId('ed');
    act(() => {
      area.focus(); // the caret is in the only paragraph: block formatting applies to it
    });
    fireEvent.click(screen.getByTestId('rt-align-center'));
    await waitFor(() => {
      expect(changed.mock.lastCall?.[0]).toContain('data-align="center"');
    });
    fireEvent.click(screen.getByTestId('rt-indent'));
    await waitFor(() => {
      expect(changed.mock.lastCall?.[0]).toContain('data-indent="1"');
    });
    // No free font, size or colour exists: only the fixed palette and three heading sizes.
    expect(screen.queryByLabelText(/font size|font family/i)).toBeNull();
    for (const tool of [
      'rt-undo',
      'rt-redo',
      'rt-style',
      'rt-colour',
      'rt-highlight',
      'rt-quote',
      'rt-code-block',
      'rt-hr',
      'rt-clear',
      'rt-full-screen',
    ]) {
      expect(screen.getByTestId(tool)).toBeDefined();
    }
  });

  it('opens full screen and leaves it with Escape', async () => {
    renderUi(<RichTextField label="Note" testId="ed" />);
    await screen.findByTestId('ed');
    fireEvent.click(screen.getByTestId('rt-full-screen'));
    const frame = screen.getByTestId('ed-frame');
    expect(frame.className).toContain('sx-richtext-fullscreen');
    expect(frame.getAttribute('role')).toBe('dialog');
    fireEvent.keyDown(frame, { key: 'Escape' });
    expect(frame.className).not.toContain('sx-richtext-fullscreen');
  });

  it('draws "align to start" on the right in Arabic (logical alignment, RTL)', async () => {
    renderUi(<RichTextField label="ملاحظة" testId="ed" />, { locale: 'ar' });
    await screen.findByTestId('ed');
    const start = screen.getByTestId('rt-align-start');
    expect(start.querySelector('[aria-label="align-right"]')).not.toBeNull();
    const indent = screen.getByTestId('rt-indent');
    expect(indent.querySelector('[aria-label="menu-fold"]')).not.toBeNull();
  });

  it('offers reply templates and inserts the chosen one', async () => {
    const changed = vi.fn<(html: string) => void>();
    renderUi(
      <RichTextField
        label="Reply"
        onChange={changed}
        templates={[{ id: 't1', name: 'Greeting', body: '<p>Hello there</p>' }]}
        testId="ed"
      />,
    );
    await screen.findByTestId('ed');
    fireEvent.click(screen.getByTestId('rt-templates'));
    fireEvent.click(await screen.findByText('Greeting'));
    await waitFor(() => {
      expect(changed.mock.lastCall?.[0]).toContain('Hello there');
    });
  });
});
