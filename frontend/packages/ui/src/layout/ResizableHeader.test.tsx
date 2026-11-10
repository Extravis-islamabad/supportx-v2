import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { renderUi } from '../test/render';
import { ResizableHeader } from './ResizableHeader';

// Haider, 2026-11-10: every list's columns resize by dragging and by keyboard, in RTL too, and
// never below a minimum; a drag is one save.

function header(props: Partial<Parameters<typeof ResizableHeader>[0]> = {}) {
  const onResize = vi.fn();
  const onPreview = vi.fn();
  renderUi(
    <table>
      <thead>
        <tr>
          <ResizableHeader
            width={200}
            defaultWidth={160}
            onResize={onResize}
            onPreview={onPreview}
            resizeLabel="Width of Subject"
            {...props}
          >
            Subject
          </ResizableHeader>
        </tr>
      </thead>
    </table>,
  );
  return {
    onResize,
    onPreview,
    handle: screen.getByRole('separator', { name: 'Width of Subject' }),
  };
}

afterEach(() => {
  document.documentElement.dir = 'ltr';
});

describe('ResizableHeader', () => {
  it('drags to a width, previews it live and saves once on release', () => {
    const { onResize, onPreview, handle } = header();
    fireEvent.mouseDown(handle, { clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 130 });
    fireEvent.mouseMove(window, { clientX: 150 });
    expect(onResize).not.toHaveBeenCalled();
    expect(onPreview).toHaveBeenLastCalledWith(250);
    fireEvent.mouseUp(window);
    expect(onResize).toHaveBeenCalledTimes(1);
    expect(onResize).toHaveBeenCalledWith(250);
    expect(onPreview).toHaveBeenLastCalledWith(null);
  });

  it('resizes by keyboard, with bigger steps on Shift and Home for the default', () => {
    const { onResize, handle } = header();
    fireEvent.keyDown(handle, { key: 'ArrowRight' });
    expect(onResize).toHaveBeenLastCalledWith(216);
    fireEvent.keyDown(handle, { key: 'ArrowLeft', shiftKey: true });
    expect(onResize).toHaveBeenLastCalledWith(136);
    fireEvent.keyDown(handle, { key: 'Home' });
    expect(onResize).toHaveBeenLastCalledWith(160);
  });

  it('mirrors the arrows and the drag in RTL', () => {
    const { onResize, handle } = header();
    document.documentElement.dir = 'rtl'; // after rendering: the provider sets it from the language
    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(onResize).toHaveBeenLastCalledWith(216);
    fireEvent.mouseDown(handle, { clientX: 300 });
    fireEvent.mouseMove(window, { clientX: 260 });
    fireEvent.mouseUp(window);
    expect(onResize).toHaveBeenLastCalledWith(240);
  });

  it('never goes below its minimum, and says so to screen readers', () => {
    const { onResize, handle } = header({ width: 190, minWidth: 180 });
    expect(handle.getAttribute('aria-valuemin')).toBe('180');
    fireEvent.keyDown(handle, { key: 'ArrowLeft', shiftKey: true });
    expect(onResize).toHaveBeenLastCalledWith(180);
    onResize.mockClear();
    fireEvent.mouseDown(handle, { clientX: 100 });
    fireEvent.mouseMove(window, { clientX: 0 });
    fireEvent.mouseUp(window);
    expect(onResize).toHaveBeenCalledWith(180); // dragged far past it: stops at the minimum
  });
});
