import { CloseOutlined } from '@ant-design/icons';
import { Button, Flex, Tooltip } from 'antd';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

const COLLAPSED = 'data-notices-collapsed';
const EXTRA = 'data-notice-extra';
const CRITICAL = '[data-notice-critical="true"]';

/**
 * The shell's notices (D-124, D-147): the banners decide for themselves whether to show, in order
 * of importance. One compact strip: the most important notice, and on the same line "N more"
 * to see the others in place, and a dismiss button that hides the strip until a notice is
 * added (never while a critical one shows). A page never starts below a wall of banners.
 *
 * "Showing" means having text: a banner with nothing to say may still render an empty box, which
 * never counts and never takes the visible place. A critical announcement takes that place
 * whatever its order, so it is never behind "N more notices".
 */
export function NoticeStack({ children, testId }: { children: ReactNode; testId?: string }) {
  const t = useLabel();
  const ref = useRef<HTMLDivElement>(null);
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [critical, setCritical] = useState(false);
  const [ownClose, setOwnClose] = useState(false);
  // The notices showing when the strip was dismissed, by their text (QA10-P3-10): the strip stays
  // hidden while only those show, through navigation and a notice that comes and goes, and comes
  // back when a new one appears. Kept for the tab's session (a reload keeps it too).
  const [texts, setTexts] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(readDismissed);

  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return undefined;
    // A banner that has nothing to say renders nothing (or an empty box): count only the
    // ones with text, so the line never promises notices that are not there.
    const update = () => {
      const showing = Array.from(element.children).filter(
        (child) => child.textContent.trim() !== '',
      );
      const first = showing.find((child) => child.querySelector(CRITICAL) !== null) ?? showing[0];
      for (const child of Array.from(element.children)) {
        // Attributes only (not observed), so marking never triggers another update.
        if (showing.includes(child) && child !== first) child.setAttribute(EXTRA, 'true');
        else child.removeAttribute(EXTRA);
      }
      setCount(showing.length);
      setTexts(showing.map((child) => child.textContent.trim()));
      setCritical(showing.some((child) => child.querySelector(CRITICAL) !== null));
      setOwnClose(first?.querySelector('.ant-alert-close-icon') != null);
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(element, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
    };
  }, []);

  const collapsed = count > 1 && !open;
  // Dismissed until a notice is added: hiding the strip never hides news (D-147 global fix 3).
  // One × per line: a notice with its own close (an announcement's dismissal is stored for the
  // person) keeps it, and the strip's dismiss shows only for notices without one.
  const hidden =
    count > 0 && !critical && texts.every((text) => dismissed.has(text)) && dismissed.size > 0;
  return (
    <div data-testid={testId} data-notice-strip="true" hidden={hidden || undefined}>
      {/* Hidden notices stay mounted, so their own live state (and focus order) is kept. A
          compact strip: the banners lose their tall padding. */}
      <style>{`[${COLLAPSED}="true"] > [${EXTRA}="true"] { display: none; }
[data-notice-strip] .ant-alert-banner { padding-block: 4px; }`}</style>
      <Flex align="center" style={{ minWidth: 0 }}>
        <div ref={ref} style={{ flex: 1, minWidth: 0 }} {...{ [COLLAPSED]: String(collapsed) }}>
          {children}
        </div>
        {count > 1 && (
          <Button
            type="link"
            size="small"
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
            data-testid={testId === undefined ? undefined : `${testId}-toggle`}
            style={{ flex: 'none', fontSize: TYPE.meta }}
          >
            {open ? t('layout.hide') : t('layout.notices_more', { count: count - 1 })}
          </Button>
        )}
        {count > 0 && !critical && !ownClose && (
          <Tooltip title={t('layout.notices_dismiss')}>
            <Button
              type="text"
              size="small"
              icon={<CloseOutlined />}
              aria-label={t('layout.notices_dismiss')}
              onClick={() => {
                const next = new Set([...dismissed, ...texts]);
                setDismissed(next);
                writeDismissed(next);
                setOpen(false);
              }}
              data-testid={testId === undefined ? undefined : `${testId}-dismiss`}
              style={{ flex: 'none', marginInline: SPACE.xs }}
            />
          </Tooltip>
        )}
      </Flex>
    </div>
  );
}

const DISMISSED_KEY = 'supportx.notices.dismissed';

// Per tab and best effort: storage can be missing or refuse (private windows); the strip then
// simply shows again after a reload.
function readDismissed(): ReadonlySet<string> {
  try {
    const raw = window.sessionStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed.filter((v) => typeof v === 'string') : []);
  } catch {
    return new Set();
  }
}

function writeDismissed(texts: ReadonlySet<string>): void {
  try {
    window.sessionStorage.setItem(DISMISSED_KEY, JSON.stringify([...texts].slice(-50)));
  } catch {
    // Not stored: shown again after a reload, never an error.
  }
}
