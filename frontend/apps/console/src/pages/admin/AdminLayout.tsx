import { MenuOutlined } from '@ant-design/icons';
import { Button, Drawer, Grid, Typography, theme } from 'antd';
import { useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router';

import {
  NoAccess,
  PageHeader,
  SettingsPageHeader,
  useAccess,
  useLabel,
  usePageCrumbs,
} from '@supportx/ui';

import { pagesFor, SETUP_GROUPS, SETUP_PAGES, type SetupPage } from './setupMap';

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
  onPick,
}: {
  to: string;
  current: boolean;
  testId: string;
  children: string;
  /** After a plain click: the phone drawer closes. */
  onPick?: () => void;
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
        onPick?.();
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
function SetupMenu({
  pages,
  active,
  onPick,
}: {
  pages: SetupPage[];
  active: string | undefined;
  onPick?: () => void;
}) {
  const t = useLabel();
  return (
    <nav aria-label={t('setup.menu')} data-testid="admin-sections">
      <MenuLink
        to="/admin"
        current={active === undefined}
        testId="admin-sections-home"
        onPick={onPick}
      >
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
                    onPick={onPick}
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

/**
 * Setup pages that have no header of their own: the shell gives them the one settings header
 * (title and description from the setup menu), so every setup page starts the same way
 * (QA9-V-16, SHELL-01). The others (people, roles, incidents, automation, instance, mail,
 * requests, portal, catalog) show their own, with their actions in it.
 */
const SHELL_HEADED = new Set([
  'ai',
  'api-keys',
  'audit',
  'branding',
  'files',
  'integrations',
  'knowledge',
  'licence',
  'notifications',
  'organization',
  'security',
  'sla',
]);

export function AdminLayout() {
  const t = useLabel();
  const { can } = useAccess();
  const { token } = theme.useToken();
  const { pathname } = useLocation();
  const wide = Grid.useBreakpoint().lg !== false;
  const [sections, setSections] = useState(false);
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
  // A setup page this person may not open says so here, by the same rule as the menu, instead
  // of rendering and failing on the server's 403 (coverage 2026-11-09 §17 item 2). Pages may
  // still check finer rights of their own.
  const known = SETUP_PAGES.find((candidate) => candidate.key === active);
  const refused = known !== undefined && page === undefined;

  const menu = (
    <SetupMenu
      pages={pages}
      active={active}
      onPick={
        wide
          ? undefined
          : () => {
              setSections(false);
            }
      }
    />
  );
  return (
    <>
      {/* "Setup" heads Setup home only; inside a page the top bar's breadcrumb is the path and
          the page shows its own name (QA6S-SHELL-02: four headings before any content). */}
      {active === undefined ? (
        <PageHeader title={t('setup.title')} testId="admin-header" />
      ) : (
        // The page's own name is its visible heading (level 2); "Setup" stays its level 1.
        <h1 className="sx-visually-hidden" data-testid="admin-header">
          {t('setup.title')}
        </h1>
      )}
      {!wide && (
        // Below 992 px the sections open in a drawer, not as a screen of links (QA6S-SHELL-04).
        <>
          <Button
            icon={<MenuOutlined />}
            onClick={() => {
              setSections(true);
            }}
            aria-expanded={sections}
            data-testid="admin-sections-button"
            style={{ marginBottom: 12 }}
          >
            {page === undefined ? t('setup.menu') : t(page.labelKey)}
          </Button>
          <Drawer
            open={sections}
            onClose={() => {
              setSections(false);
            }}
            title={t('setup.menu')}
            placement="left"
            width={300}
          >
            {menu}
          </Drawer>
        </>
      )}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: wide ? '220px minmax(0, 1fr)' : 'minmax(0, 1fr)',
          gap: 24,
          alignItems: 'start',
        }}
      >
        {wide && (
          // Sticky under the top bar with its own scroll, so the open page stays in view and a
          // short page does not scroll for the menu's sake (QA6S-SHELL-03).
          <div
            style={{
              position: 'sticky',
              top: 72,
              maxHeight: 'calc(100vh - 88px)',
              overflowY: 'auto',
              paddingInlineEnd: 4,
              scrollbarWidth: 'thin',
              borderInlineEnd: `1px solid ${token.colorBorderSecondary}`,
            }}
          >
            {menu}
          </div>
        )}
        <div style={{ minWidth: 0 }}>
          {page !== undefined && SHELL_HEADED.has(page.key) && (
            <SettingsPageHeader
              title={t(page.labelKey)}
              description={t(`setup.page.${page.key}.description`)}
              testId="admin-page-header"
            />
          )}
          {refused ? <NoAccess titleKey={known.labelKey} /> : <Outlet />}
        </div>
      </div>
    </>
  );
}
