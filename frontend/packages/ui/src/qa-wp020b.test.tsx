import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { RealtimeContext, type RealtimeConnection } from '@supportx/realtime';

import { ConnectivityBanner } from './errors';
import { REALTIME_GRACE_MS } from './errors/ConnectivityBanner';
import { RichTextField, RichTextView } from './richtext';
import { renderUi } from './test/render';

// WP-020b QA findings in the shared UI (Desktop/qa-wp020b/QA-REPORT.md). Each test is named
// after its finding and failed before the fix.

type Editable = HTMLElement & {
  editor: {
    commands: { setContent: (html: string) => void; focus: (at?: string) => void };
    getHTML: () => string;
    view: { pasteHTML: (html: string) => void };
  };
};

describe('QA WP-020b', () => {
  it('BUG-02: live updates never stop silently: a paused channel shows a banner', () => {
    vi.useFakeTimers();
    try {
      const connection = {
        currentStatus: 'limited',
        onStatus: () => () => undefined,
      } as unknown as RealtimeConnection;
      renderUi(
        <RealtimeContext.Provider value={{ connection, tenantId: 't', userId: 'u' }}>
          <ConnectivityBanner />
        </RealtimeContext.Provider>,
      );
      act(() => {
        vi.advanceTimersByTime(REALTIME_GRACE_MS + 10);
      });
      expect(screen.getByTestId('realtime-limited-banner').textContent).toContain(
        'Some live updates are paused',
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('BUG-03: each list item reads in its own direction, so the bullet sits beside its text', () => {
    renderUi(
      <RichTextView
        testId="view"
        html={
          '<ul><li><p>إعادة تشغيل خدمة الطباعة</p></li><li><p>Driver 7.1.3 installed</p></li></ul>' +
          '<ul dir="auto"><li dir="auto"><p dir="auto">مرحبا</p></li></ul>'
        }
      />,
    );
    const items = [...screen.getByTestId('view').querySelectorAll('li')];
    expect(items.map((li) => li.getAttribute('dir'))).toEqual(['rtl', 'ltr', 'rtl']);
  });

  it('BUG-03: the editor gives each list item its own direction too', async () => {
    renderUi(<RichTextField label="Note" testId="ed" />, { locale: 'ar' });
    const area = await screen.findByTestId<Editable>('ed');
    act(() => {
      area.editor.commands.setContent(
        '<ul><li><p>إعادة تشغيل</p></li><li><p>Driver 7.1.3</p></li></ul>',
      );
    });
    await waitFor(() => {
      expect([...area.querySelectorAll('li')].map((li) => li.getAttribute('dir'))).toEqual([
        'rtl',
        'ltr',
      ]);
    });
  });

  it('BUG-05: full screen edits the whole window and Escape leaves it from anywhere', async () => {
    renderUi(<RichTextField label="Note" testId="ed" minHeight={180} />);
    const area = await screen.findByTestId('ed');
    fireEvent.click(screen.getByTestId('rt-full-screen'));
    const frame = screen.getByTestId('ed-frame');
    expect(frame.className).toContain('sx-richtext-fullscreen');
    // The composer's own minimum height must not limit the full-screen editing area.
    expect(frame.style.getPropertyValue('--sx-editor-min-height')).toBe('');
    // A click on the empty area below the text puts the caret in the editor.
    const scroll = frame.querySelector('.sx-richtext-scroll');
    if (scroll === null) throw new Error('no scroll area');
    fireEvent.mouseDown(scroll);
    await waitFor(() => {
      expect(document.activeElement).toBe(area);
    });
    // Escape works wherever the focus is.
    act(() => {
      (document.activeElement as HTMLElement | null)?.blur();
    });
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(frame.className).not.toContain('sx-richtext-fullscreen');
    expect(frame.style.getPropertyValue('--sx-editor-min-height')).toBe('180px');
  });

  it('C7: pasting into an empty line keeps the alignment of the first pasted paragraph', async () => {
    // jsdom has no ClipboardEvent; ProseMirror's pasteHTML creates one for its handlers.
    vi.stubGlobal(
      'ClipboardEvent',
      class extends Event {
        clipboardData = null;
      },
    );
    renderUi(<RichTextField label="Note" testId="ed" />);
    const area = await screen.findByTestId<Editable>('ed');
    act(() => {
      area.editor.commands.focus('end');
      area.editor.view.pasteHTML(
        '<p class="MsoNormal" style="text-align:center"><b>Word title</b></p><p>Body</p>',
      );
    });
    expect(area.editor.getHTML()).toMatch(/^<p[^>]*data-align="center"[^>]*><strong>Word title/);
  });
});
