import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Tabs as AntTabs, theme, type TabsProps } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useLabel } from '../appearance';

/**
 * Buttons that scroll a tab row that does not fit (QA 2026-11-11 F-06/V-04). Ant Design's own
 * overflow menu puts its button inside the tab list, which may hold only tabs (axe
 * aria-required-children), so it stays hidden (AppearanceProvider) and the row scrolls
 * instead. A row that scrolls with no visible control could not be reached by a mouse
 * (the designer's Test and Versions tabs), so these sit beside the list, outside it, on the
 * side there is more to see. The keyboard moves through the tabs with the arrow keys; the
 * focused tab is scrolled into view.
 */
const WIDTH = 32;

function ScrollButtons() {
  const t = useLabel();
  const { token } = theme.useToken();
  const anchor = useRef<HTMLSpanElement>(null);
  const [wrap, setWrap] = useState<HTMLElement | null>(null);
  const [can, setCan] = useState({ back: false, on: false });
  // Where the row's scrolling part is, inside the tabs box: the buttons sit on its two ends,
  // never over the content beside the row (tabBarExtraContent).
  const [box, setBox] = useState({ top: 0, height: 0, left: 0, right: 0 });

  useEffect(() => {
    const tabs = anchor.current?.closest('.ant-tabs');
    const found = tabs?.querySelector<HTMLElement>(':scope > .ant-tabs-nav .ant-tabs-nav-wrap');
    // Only a row of tabs scrolls sideways; tabs down the side keep Ant Design's own layout.
    const row =
      tabs !== null &&
      tabs !== undefined &&
      (tabs.classList.contains('ant-tabs-top') || tabs.classList.contains('ant-tabs-bottom'));
    setWrap(row ? (found ?? null) : null);
  }, []);

  const measure = useCallback(() => {
    if (wrap === null) return;
    // In RTL scrollLeft runs from 0 to negative: the distance from the start is its size.
    const from = Math.abs(wrap.scrollLeft);
    const room = wrap.scrollWidth - wrap.clientWidth;
    setCan({ back: from > 1, on: room - from > 1 });
    const outer = wrap.closest('.ant-tabs')?.getBoundingClientRect();
    const inner = wrap.getBoundingClientRect();
    if (outer !== undefined) {
      setBox({
        top: inner.top - outer.top,
        height: inner.height,
        left: inner.left - outer.left,
        right: inner.right - outer.left,
      });
    }
  }, [wrap]);

  useEffect(() => {
    if (wrap === null) return undefined;
    measure();
    const onFocus = (event: FocusEvent) => {
      if (event.target instanceof HTMLElement) {
        event.target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      }
    };
    wrap.addEventListener('scroll', measure, { passive: true });
    wrap.addEventListener('focusin', onFocus);
    const watch = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure);
    watch?.observe(wrap);
    const list = wrap.querySelector('.ant-tabs-nav-list');
    if (list !== null) watch?.observe(list);
    return () => {
      wrap.removeEventListener('scroll', measure);
      wrap.removeEventListener('focusin', onFocus);
      watch?.disconnect();
    };
  }, [wrap, measure]);

  const rtl = wrap !== null && getComputedStyle(wrap).direction === 'rtl';
  const go = (towardsEnd: boolean) => {
    if (wrap === null) return;
    const step = Math.max(80, wrap.clientWidth * 0.7) * (towardsEnd ? 1 : -1);
    wrap.scrollBy({ left: rtl ? -step : step, behavior: 'smooth' });
  };
  const button = (towardsEnd: boolean) => (
    <button
      type="button"
      className="sx-tabs-scroll"
      aria-label={t(towardsEnd ? 'layout.tabs_later' : 'layout.tabs_earlier')}
      title={t(towardsEnd ? 'layout.tabs_later' : 'layout.tabs_earlier')}
      onClick={() => {
        go(towardsEnd);
      }}
      data-testid={towardsEnd ? 'tabs-scroll-later' : 'tabs-scroll-earlier'}
      style={{
        position: 'absolute',
        top: box.top,
        height: box.height,
        // Physical places: the box was measured on screen. The end is on the left in RTL.
        left: towardsEnd !== rtl ? box.right - WIDTH : box.left,
        zIndex: 2,
        width: WIDTH,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: 'none',
        cursor: 'pointer',
        color: token.colorText,
        background: token.colorBgContainer,
        boxShadow: `${towardsEnd !== rtl ? '-' : ''}6px 0 6px -4px ${token.colorBorder}`,
      }}
    >
      {/* The arrow points the way the row moves on screen, mirrored in RTL. */}
      {towardsEnd !== rtl ? <RightOutlined /> : <LeftOutlined />}
    </button>
  );
  return (
    <span ref={anchor} style={{ display: 'contents' }}>
      {can.back && button(false)}
      {can.on && button(true)}
    </span>
  );
}

/**
 * Ant Design's tabs with a row that scrolls by buttons when it does not fit (F-06/V-04).
 * Use it for every tab row: the overflow menu is turned off app-wide.
 */
export function Tabs(props: TabsProps) {
  const { renderTabBar, style } = props;
  return (
    <AntTabs
      {...props}
      style={{ position: 'relative', ...style }}
      renderTabBar={(barProps, DefaultTabBar) => (
        <>
          {renderTabBar === undefined ? (
            <DefaultTabBar {...barProps} />
          ) : (
            renderTabBar(barProps, DefaultTabBar)
          )}
          <ScrollButtons />
        </>
      )}
    />
  );
}

export type { TabsProps };
