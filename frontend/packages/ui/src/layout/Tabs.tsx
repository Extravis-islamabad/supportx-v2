import { LeftOutlined, RightOutlined } from '@ant-design/icons';
import { Tabs as AntTabs, theme, type TabsProps } from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useLabel } from '../appearance';

/**
 * Buttons that scroll a tab row that does not fit (QA 2026-11-11 F-06/V-04). Ant Design's own
 * overflow menu puts its button inside the tab list, which may hold only tabs (axe
 * aria-required-children), so it stays hidden (AppearanceProvider) and the row scrolls
 * instead. A row that scrolls with no visible control could not be reached by a mouse
 * (the designer's Test and Versions tabs), so these sit beside the list, outside it. While the
 * row overflows, its scrolling part is narrowed by a button's width on each side and the
 * buttons sit in that room: they never cover a tab, so a click on a tab is never taken by a
 * button (the #402 smoke run: Test could not be clicked under "Later tabs"). Each is disabled
 * when there is nothing more that way. The keyboard moves through the tabs with the arrow
 * keys; the focused tab is scrolled into view.
 */
const WIDTH = 32;

function ScrollButtons() {
  const t = useLabel();
  const { token } = theme.useToken();
  const anchor = useRef<HTMLSpanElement>(null);
  const [wrap, setWrap] = useState<HTMLElement | null>(null);
  const [can, setCan] = useState({ over: false, back: false, on: false });
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
    // The room the buttons take counts back in, so the row stops overflowing (and the buttons
    // go) only once it fits without them.
    const narrowed = wrap.style.marginInline !== '' ? 2 * WIDTH : 0;
    const over = room - narrowed > 1 || (narrowed === 0 && room > 1);
    wrap.style.marginInline = over ? `${String(WIDTH)}px` : '';
    setCan({ over, back: over && from > 1, on: over && room - from > 1 });
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
    // A focused tab keeps the row where it is. Ant Design's tab list resets the row's scroll
    // to the start on every tab focus (it scrolls by transform, which is off here), so a tab
    // pressed in a scrolled row slid away before the press ended and the click never landed
    // (the #402 smoke runs: the designer's Test tab, an incident's Automation tab). The scroll
    // is put back once its handler has run, before the pointer is released; keyboard focus then
    // brings the focused tab into view.
    const onFocus = (event: FocusEvent) => {
      const tab = event.target;
      if (!(tab instanceof HTMLElement)) return;
      const kept = wrap.scrollLeft;
      let keyboard: boolean;
      try {
        keyboard = tab.matches(':focus-visible');
      } catch {
        keyboard = false; // an engine without :focus-visible: never move on focus
      }
      queueMicrotask(() => {
        if (wrap.scrollLeft !== kept) wrap.scrollLeft = kept;
        if (keyboard) tab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      });
    };
    // A pointer press never moves focus onto a tab: focusing one makes Ant Design reset the
    // row's scroll (above), and in a real browser the tab still slid out from under the press,
    // so the click never chose it (the #402 smoke runs). The click itself still chooses the tab;
    // the keyboard reaches tabs by Tab and the arrow keys as before.
    const onPress = (event: MouseEvent) => {
      if (
        event.button === 0 &&
        event.target instanceof Element &&
        event.target.closest('[role="tab"]')
      ) {
        event.preventDefault();
      }
    };
    wrap.addEventListener('scroll', measure, { passive: true });
    wrap.addEventListener('focusin', onFocus);
    wrap.addEventListener('mousedown', onPress, { capture: true });
    const watch = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(measure);
    watch?.observe(wrap);
    const list = wrap.querySelector('.ant-tabs-nav-list');
    if (list !== null) watch?.observe(list);
    return () => {
      wrap.style.marginInline = '';
      wrap.removeEventListener('scroll', measure);
      wrap.removeEventListener('focusin', onFocus);
      wrap.removeEventListener('mousedown', onPress, { capture: true });
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
      disabled={towardsEnd ? !can.on : !can.back}
      onClick={() => {
        go(towardsEnd);
      }}
      data-testid={towardsEnd ? 'tabs-scroll-later' : 'tabs-scroll-earlier'}
      style={{
        position: 'absolute',
        top: box.top,
        height: box.height,
        // In the room beside the scrolling part, never over it. Physical places: the box was
        // measured on screen, and the end is on the left in RTL.
        left: towardsEnd !== rtl ? box.right : box.left - WIDTH,
        zIndex: 2,
        width: WIDTH,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: 'none',
        cursor: (towardsEnd ? can.on : can.back) ? 'pointer' : 'default',
        color: (towardsEnd ? can.on : can.back) ? token.colorText : token.colorTextDisabled,
        background: token.colorBgContainer,
      }}
    >
      {/* "Later" points to the end and "earlier" to the start: the icons mirror themselves
          in RTL (the matrix's Arabic shot showed them flipped twice when this flipped too). */}
      {towardsEnd ? <RightOutlined /> : <LeftOutlined />}
    </button>
  );
  return (
    <span ref={anchor} style={{ display: 'contents' }}>
      {can.over && button(false)}
      {can.over && button(true)}
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
