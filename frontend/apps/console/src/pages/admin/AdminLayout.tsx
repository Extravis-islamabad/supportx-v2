import { Grid, Typography, theme } from 'antd';
import { Navigate, Outlet, useLocation, useNavigate } from 'react-router';

import { NoAccess, PageHeader, useAccess, useLabel, usePageCrumbs } from '@supportx/ui';

import { pagesFor, SETUP_GROUPS, type SetupPage } from './setupMap';

type Token = ReturnType<typeof theme.useToken>['token'];

function linkStyle(token: Token, current: boolean) {
  return {
    display: 'block',
    padding: '6px 8px',
    borderRadius: token.borderRadius,
    color: token.colorText,
    fontWeight: current ? 600 : 400,
    background: current ? token.colorFillSecondary : 'transparent',
    borderInlineStart: `3px solid ${current ? token.colorPrimary : 'transparent'}`,
    textDecoration: 'none',
  } as const;
}

/** A setup link: a plain click stays in the app, a modified click opens a new tab as usual. */
function MenuLink({
  to,
  current,
  testId,
  children,
}: {
  to: string;
  current: boolean;
  testId: string;
  children: string;
}) {
  const navigate = useNavigate();
  const { token } = theme.useToken();
  return (
    <a
      href={to}
      aria-current={current ? 'page' : undefined}
      data-testid={testId}
      style={linkStyle(token, current)}
      onClick={(event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
        event.preventDefault();
        void navigate(to);
      }}
    >
      {children}
    </a>
  );
}

/**
 * The setup menu (WP-042, REQ-ADM-108): the pages this person may open, grouped by task, as a
 * `<nav>` of links (each page has its own address; `aria-current` on the open one). Beside the
 * page from 992 px, above it on smaller screens. Test ids stay `admin-sections-<key>`.
 */
function SetupMenu({ pages, active }: { pages: SetupPage[]; active: string | undefined }) {
  const t = useLabel();
  return (
    <nav aria-label={t('setup.menu')} data-testid="admin-sections">
      <MenuLink to="/admin" current={active === undefined} testId="admin-sections-home">
        {t('setup.home')}
      </MenuLink>
      {SETUP_GROUPS.map((group) => {
        const inGroup = pages.filter((page) => page.group === group);
        if (inGroup.length === 0) return null;
        return (
          <div key={group} style={{ marginTop: 12 }}>
            <Typography.Text
              type="secondary"
              strong
              id={`setup-group-${group}`}
              style={{ display: 'block', fontSize: 12, padding: '0 8px 4px' }}
            >
              {t(`setup.group.${group}`)}
            </Typography.Text>
            <ul
              aria-labelledby={`setup-group-${group}`}
              style={{ listStyle: 'none', margin: 0, padding: 0 }}
            >
              {inGroup.map((page) => (
                <li key={page.key}>
                  <MenuLink
                    to={`/admin/${page.key}`}
                    current={page.key === active}
                    testId={`admin-sections-${page.key}`}
                  >
                    {t(page.labelKey)}
                  </MenuLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export function AdminLayout() {
  const t = useLabel();
  const { can } = useAccess();
  const { pathname } = useLocation();
  const wide = Grid.useBreakpoint().lg !== false;
  const pages = pagesFor(can);
  const segment = pathname.split('/')[2];
  const active = segment === undefined || segment === '' ? undefined : segment;
  const page = pages.find((candidate) => candidate.key === active);
  usePageCrumbs(
    page === undefined
      ? null
      : [{ label: t('setup.title'), path: '/admin' }, { label: t(page.labelKey) }],
  );

  if (pages.length === 0) return <NoAccess titleKey="nav.admin" />;
  // An address this person may not open goes home rather than showing an empty frame.
  if (active !== undefined && page === undefined) return <Navigate to="/admin" replace />;

  return (
    <>
      {/* Each setup page shows its own name as its heading (level 2, D-124). */}
      <PageHeader title={t('setup.title')} testId="admin-header" />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: wide ? '220px minmax(0, 1fr)' : 'minmax(0, 1fr)',
          gap: 24,
          alignItems: 'start',
        }}
      >
        <div style={wide ? { position: 'sticky', top: 16 } : undefined}>
          <SetupMenu pages={pages} active={active} />
        </div>
        <div style={{ minWidth: 0 }}>
          <Outlet />
        </div>
      </div>
    </>
  );
}
