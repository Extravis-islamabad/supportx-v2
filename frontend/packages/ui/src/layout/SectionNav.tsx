import { Flex, theme } from 'antd';

import { SPACE, TYPE } from '../density';

export interface SectionNavItem {
  key: string;
  label: string;
  /** Where the section lives: each section is a page with its own address. */
  path: string;
}

/**
 * The sections of a settings area as links (D-124). They are pages, not tab panels, so they are
 * a `<nav>` of links (`aria-current` on the open one), never a `tablist`. They wrap onto a second
 * line instead of hiding behind an overflow menu: Ant Design's tab overflow button inside a
 * tablist failed axe in Arabic, where labels are longer (aria-required-children).
 */
export function SectionNav({
  items,
  active,
  onNavigate,
  label,
  testId,
}: {
  items: readonly SectionNavItem[];
  active: string | undefined;
  onNavigate: (path: string) => void;
  /** The nav's accessible name ("Administration sections"). */
  label: string;
  testId?: string;
}) {
  const { token } = theme.useToken();
  return (
    <nav aria-label={label} data-testid={testId} style={{ marginBottom: SPACE.sm }}>
      <Flex
        wrap
        gap={SPACE.xxs}
        style={{ borderBottom: `1px solid ${token.colorBorderSecondary}` }}
      >
        {items.map((item) => {
          const current = item.key === active;
          return (
            <a
              key={item.key}
              href={item.path}
              aria-current={current ? 'page' : undefined}
              data-testid={testId === undefined ? undefined : `${testId}-${item.key}`}
              onClick={(event) => {
                // A plain click stays in the app; a modified click opens a new tab as usual.
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                event.preventDefault();
                onNavigate(item.path);
              }}
              style={{
                padding: `${String(SPACE.xs)}px ${String(SPACE.sm)}px`,
                fontSize: TYPE.body,
                color: current ? token.colorPrimary : token.colorText,
                fontWeight: current ? 600 : 400,
                borderBottom: `2px solid ${current ? token.colorPrimary : 'transparent'}`,
                marginBottom: -1,
                textDecoration: 'none',
              }}
            >
              {item.label}
            </a>
          );
        })}
      </Flex>
    </nav>
  );
}
