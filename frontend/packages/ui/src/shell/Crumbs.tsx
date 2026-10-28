import { Breadcrumb, Typography } from 'antd';
import { useMemo, useState, type ReactNode } from 'react';

import { useLabels } from '@supportx/labels';

import { CrumbContext, type Crumb } from './pageCrumbs';

/** Holds the page's own crumbs for the header and the tab title (once, in the layout). */
export function CrumbProvider({ children }: { children: ReactNode }) {
  const [crumbs, setCrumbs] = useState<Crumb[] | null>(null);
  const value = useMemo(() => ({ crumbs, setCrumbs }), [crumbs]);
  return <CrumbContext.Provider value={value}>{children}</CrumbContext.Provider>;
}

/**
 * The header's breadcrumbs. Narrow screens show only the page itself, cut short with an
 * ellipsis (its full text as a tooltip), so the header never wraps.
 */
export function HeaderCrumbs({
  crumbs,
  narrow,
  onNavigate,
}: {
  crumbs: Crumb[];
  narrow: boolean;
  onNavigate: (path: string) => void;
}) {
  const t = useLabels();
  const last = crumbs[crumbs.length - 1];
  if (last === undefined) return <span style={{ flex: 1 }} />;
  if (narrow) {
    return (
      <Typography.Text
        strong
        ellipsis={{ tooltip: last.label }}
        style={{ flex: 1, minWidth: 0 }}
        data-testid="header-crumbs"
      >
        {last.label}
      </Typography.Text>
    );
  }
  return (
    <nav aria-label={t('shell.breadcrumbs')} style={{ flex: 1, minWidth: 0 }}>
      <Breadcrumb
        data-testid="header-crumbs"
        items={crumbs.map((crumb, index) => {
          const current = index === crumbs.length - 1;
          return {
            key: `${String(index)}-${crumb.label}`,
            title:
              crumb.path !== undefined && !current ? (
                <a
                  href={crumb.path}
                  onClick={(event) => {
                    event.preventDefault();
                    onNavigate(crumb.path ?? '/');
                  }}
                >
                  {crumb.label}
                </a>
              ) : (
                <Typography.Text strong={current} aria-current={current ? 'page' : undefined}>
                  {crumb.label}
                </Typography.Text>
              ),
          };
        })}
      />
    </nav>
  );
}
