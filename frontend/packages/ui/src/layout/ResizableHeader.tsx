import {
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ThHTMLAttributes,
} from 'react';

/** The widths the server accepts for a list column (work_items domain/lists.py). */
export const COLUMN_MIN_WIDTH = 60;
export const COLUMN_MAX_WIDTH = 800;
const KEY_STEP = 16;
const KEY_STEP_LARGE = 64;

export type ResizableHeaderProps = ThHTMLAttributes<HTMLTableCellElement> & {
  /** The column's width now; without it, the cell's width as drawn (an automatic column). */
  width?: number;
  /** The column's own width, which Home and a double click return to. */
  defaultWidth?: number;
  /** Never narrower than this (the subject keeps room to read, Haider 2026-11-10). */
  minWidth?: number;
  /** A finished change: the drag released, or one key press. Without it the cell is plain. */
  onResize?: (width: number) => void;
  /** Home and a double click: back to the column's own width (else to `defaultWidth`). */
  onReset?: () => void;
  /** While dragging, the width to show now (null when the drag ends); the page sizes the column. */
  onPreview?: (width: number | null) => void;
  /** The separator's name for screen readers, e.g. "Resize the Subject column". */
  resizeLabel?: string;
};

/**
 * A list header cell whose end edge (the left edge in RTL) drags to resize (D-147 template C).
 *
 * The width follows the pointer while dragging and is handed on once, on release, so a drag is
 * one save through the list's per-view settings chain. The handle is a focusable separator:
 * the arrow keys change the width (Shift for bigger steps, mirrored in RTL), Home and a double
 * click go back to the column's own width.
 */
export function ResizableHeader({
  width,
  defaultWidth,
  minWidth = COLUMN_MIN_WIDTH,
  onResize,
  onReset,
  onPreview,
  resizeLabel,
  children,
  ...rest
}: ResizableHeaderProps) {
  const start = useRef<{ x: number; width: number } | null>(null);
  const cell = useRef<HTMLTableCellElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  // The width an automatic column is drawn at, so the separator always has a value
  // (QA10V-04, axe aria-required-attr: a separator that can be focused needs aria-valuenow).
  const [drawn, setDrawn] = useState<number | null>(null);
  const resizable = onResize !== undefined;
  useLayoutEffect(() => {
    const element = cell.current;
    if (element === null) return;
    const read = () => {
      if (element.offsetWidth > 0) setDrawn(element.offsetWidth);
    };
    read();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(read);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
    // Again when resizing turns on: lists enable it once their views load (useColumnWidths).
  }, [resizable]);
  if (!resizable) return <th {...rest}>{children}</th>;
  const least = Math.max(COLUMN_MIN_WIDTH, minWidth);
  const clamp = (value: number) => Math.min(COLUMN_MAX_WIDTH, Math.max(least, Math.round(value)));
  // An automatic column has no number yet: it starts from the width it is drawn at.
  const now = () => clamp(width ?? cell.current?.offsetWidth ?? least);
  const shown = dragging ?? clamp(width ?? drawn ?? defaultWidth ?? least);
  const reset = () => {
    if (onReset !== undefined) onReset();
    else if (defaultWidth !== undefined) commit(clamp(defaultWidth));
  };
  const rtl = () => document.documentElement.dir === 'rtl';
  const commit = (next: number) => {
    if (width === undefined || next !== clamp(width)) onResize(next);
  };
  const onMouseDown = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation(); // never a sort click
    start.current = { x: event.clientX, width: now() };
    let last = now();
    const moved = (move: globalThis.MouseEvent) => {
      if (start.current === null) return;
      const delta = (move.clientX - start.current.x) * (rtl() ? -1 : 1);
      last = clamp(start.current.width + delta);
      setDragging(last);
      onPreview?.(last);
    };
    const up = () => {
      start.current = null;
      window.removeEventListener('mousemove', moved);
      window.removeEventListener('mouseup', up);
      setDragging(null);
      onPreview?.(null);
      commit(last);
    };
    window.addEventListener('mousemove', moved);
    window.addEventListener('mouseup', up);
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Home') {
      event.preventDefault();
      event.stopPropagation();
      reset();
      return;
    }
    const wider = rtl() ? 'ArrowLeft' : 'ArrowRight';
    const narrower = rtl() ? 'ArrowRight' : 'ArrowLeft';
    if (event.key !== wider && event.key !== narrower) return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.shiftKey ? KEY_STEP_LARGE : KEY_STEP;
    commit(clamp(now() + (event.key === wider ? step : -step)));
  };
  return (
    <th
      {...rest}
      ref={cell}
      style={{
        ...rest.style,
        position: 'relative',
        // While dragging, the cell shows the width it will get (the table follows on release).
        ...(dragging === null ? {} : { width: dragging, minWidth: dragging }),
      }}
    >
      {children}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={resizeLabel}
        aria-valuenow={shown}
        aria-valuemin={least}
        aria-valuemax={COLUMN_MAX_WIDTH}
        tabIndex={0}
        data-testid="column-resize"
        onMouseDown={onMouseDown}
        onKeyDown={onKeyDown}
        onDoubleClick={(event) => {
          event.stopPropagation();
          reset();
        }}
        onClick={(event) => {
          event.stopPropagation();
        }}
        style={{
          position: 'absolute',
          insetBlock: 0,
          insetInlineEnd: -4,
          width: 8,
          cursor: 'col-resize',
          zIndex: 1,
        }}
      />
    </th>
  );
}
