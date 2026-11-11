import { Tooltip } from 'antd';
import { useRef, useState, type ReactNode } from 'react';

/**
 * A list cell's text, cut with an ellipsis at its own logical end (Haider's 2026-11-10 recheck:
 * in Arabic, English names lost their start because the cell cut in the page's direction).
 * It reads in its own direction (`dir="auto"`) and keeps the column's alignment.
 *
 * Cut text shows the whole of it in a tooltip on hover or focus (the QA fix-round: a `title`
 * attribute alone was not seen); text that fits shows none. `title` is the whole text when the
 * cell holds more than a string.
 */
export function CellText({ children, title }: { children: ReactNode; title?: string }) {
  const ref = useRef<HTMLElement>(null);
  const [cut, setCut] = useState(false);
  const whole = title ?? (typeof children === 'string' ? children : undefined);
  const measure = () => {
    const element = ref.current;
    setCut(element !== null && element.scrollWidth > element.clientWidth);
  };
  return (
    <Tooltip title={cut ? <bdi dir="auto">{whole}</bdi> : undefined} mouseEnterDelay={0.4}>
      <bdi
        ref={ref}
        dir="auto"
        className="sx-cell-text"
        // No `title` too: it would be a second tooltip; screen readers read the whole text, as
        // the cut is only drawn.
        onMouseEnter={measure}
        onFocus={measure}
      >
        {children}
      </bdi>
    </Tooltip>
  );
}
