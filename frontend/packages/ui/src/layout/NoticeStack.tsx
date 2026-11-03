import { Button, Flex, Typography } from 'antd';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

import { useLabel } from '../appearance';
import { SPACE, TYPE } from '../density';

const COLLAPSED = 'data-notices-collapsed';

/**
 * The shell's notices (D-124): the banners decide for themselves whether to show, in order of
 * importance. With two or more showing, only the first stays and a line says how many more,
 * with "View" to see them all in place; a page never starts below a wall of banners.
 */
export function NoticeStack({ children, testId }: { children: ReactNode; testId?: string }) {
  const t = useLabel();
  const ref = useRef<HTMLDivElement>(null);
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return undefined;
    // A banner that has nothing to say renders nothing (or an empty box): count only the
    // ones with text, so the line never promises notices that are not there.
    const update = () => {
      setCount(
        Array.from(element.children).filter((child) => child.textContent.trim() !== '').length,
      );
    };
    update();
    const observer = new MutationObserver(update);
    observer.observe(element, { childList: true, subtree: true, characterData: true });
    return () => {
      observer.disconnect();
    };
  }, []);

  const collapsed = count > 1 && !open;
  return (
    <div data-testid={testId}>
      {/* Hidden notices stay mounted, so their own live state (and focus order) is kept. */}
      <style>{`[${COLLAPSED}="true"] > :not(:first-child) { display: none; }`}</style>
      <div ref={ref} {...{ [COLLAPSED]: String(collapsed) }}>
        {children}
      </div>
      {count > 1 && (
        <Flex
          align="center"
          gap={SPACE.xs}
          style={{ padding: `${String(SPACE.xxs)}px ${String(SPACE.md)}px` }}
        >
          <Typography.Text type="secondary" style={{ fontSize: TYPE.meta }}>
            {open
              ? t('layout.notices_count', { count })
              : t('layout.notices_more', { count: count - 1 })}
          </Typography.Text>
          <Button
            type="link"
            size="small"
            aria-expanded={open}
            onClick={() => {
              setOpen(!open);
            }}
            data-testid={testId === undefined ? undefined : `${testId}-toggle`}
          >
            {t(open ? 'layout.hide' : 'layout.view')}
          </Button>
        </Flex>
      )}
    </div>
  );
}
