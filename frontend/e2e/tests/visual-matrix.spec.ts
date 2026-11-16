import { mkdirSync, writeFileSync } from 'node:fs';

import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page, type Route } from '@playwright/test';

import { PORTAL_URL, passwordOf, SEEDED, USERS } from '../stack';
import { signIn } from './helpers';

// The daily visual review (product owner, 2026-11-04): every console and portal screen in every
// navigation layout, theme, language and width, as JPEG screenshots with cheap automatic checks
// recorded as warnings (never failures) in index.json. Only a crash of this spec turns the job
// red. Run by the "Visual matrix" workflow (nightly and on demand), one sixth of the screens per
// shard (VISUAL_SHARD=n/6); never part of the stack smoke (it is skipped there).
//
// File names put the screen first, so a day's changed screens are easy to filter:
//   <screen>[~<state>]__<layout>__<theme>__<lang>__<width>.jpg

const RUN = process.env.VISUAL_MATRIX === '1';
const OUT = process.env.VISUAL_OUT ?? 'visual-matrix';
const [SHARD, SHARDS] = (process.env.VISUAL_SHARD ?? '1/1').split('/').map(Number) as [
  number,
  number,
];
const SHOWCASE_PASSWORD = process.env.SUPPORTX_SHOWCASE_PASSWORD ?? '';
// A run of only some screens (the workflow's `screens` input): keys, or prefixes ending in "*".
const ONLY = (process.env.VISUAL_SCREENS ?? '')
  .split(',')
  .map((key) => key.trim())
  .filter((key) => key !== '');

function wanted(screen: { key: string }): boolean {
  if (ONLY.length === 0) return true;
  return ONLY.some((key) =>
    key.endsWith('*') ? screen.key.startsWith(key.slice(0, -1)) : screen.key === key,
  );
}

const LAYOUTS = ['side', 'side_compact', 'top'] as const;
const THEMES = ['light', 'dark'] as const;
const LANGS = ['en', 'ar'] as const;
const WIDTHS = [1440, 1280, 390] as const;

type Layout = (typeof LAYOUTS)[number];
type Records = Partial<
  Record<
    | 'incident'
    | 'request'
    | 'article'
    | 'dashboard'
    | 'problem'
    | 'release'
    | 'announcement'
    | 'asset'
    | 'consumable'
    | 'audit'
    | 'scannedAsset'
    | 'catalogItem'
    | 'workflow'
    | 'workflowRun'
    | 'workflowRunFlow',
    string
  >
>;

/** The new-incident form with a kept draft on the server (readable or not). */
function keptDraft(unreadable: boolean): (page: Page) => Promise<void> {
  return async (page) => {
    const url = '**/api/v1/drafts/incident-new';
    const answer = (route: Route) =>
      route.request().method() === 'GET'
        ? route.fulfill({
            json: {
              form_key: 'incident-new',
              version: 2,
              updated_at: new Date(Date.now() - 10 * 60_000).toISOString(),
              unreadable,
              values: unreadable ? null : { subject: 'Printer jams on floor 2' },
            },
          })
        : route.continue();
    await page.route(url, answer);
    // Every shot shares one tab: an earlier shot's own copy of this form (sessionStorage) would
    // count as restored and hide the server's note (lane C, matrix 43474443928).
    await page.evaluate(() => {
      for (const name of Object.keys(window.sessionStorage)) {
        if (name.startsWith('supportx.draft.')) window.sessionStorage.removeItem(name);
      }
    });
    await page.reload();
    try {
      await page.getByTestId(unreadable ? 'kept-draft-unreadable' : 'kept-draft').waitFor();
    } finally {
      // Read once and kept (staleTime Infinity): the note stays, and later shots on this tab get
      // the real answer again.
      await page.unroute(url, answer);
    }
  };
}

const STOP_TOKEN = 'S'.repeat(43);

/** The stop-mails page with its public calls answered in the browser; `press`: also stop. */
function stopMails(press: boolean): (page: Page) => Promise<void> {
  return async (page) => {
    await page.route('**/api/v1/public/notify-links/peek', (route) =>
      route.fulfill({ json: { display_id: 'INC-12', address: 'b***@acme.test' } }),
    );
    await page.route('**/api/v1/public/notify-links/stop', (route) =>
      route.fulfill({ status: 204, body: '' }),
    );
    const url = new URL(page.url());
    url.hash = STOP_TOKEN;
    await page.goto(url.href);
    await page.getByTestId('stop-mails-ask').waitFor();
    if (press) {
      await page.getByTestId('stop-mails-button').click();
      await page.getByTestId('stop-mails-done').waitFor();
    }
  };
}

interface Screen {
  key: string;
  /** A path, or one built from the records found at the start (none: skipped, noted). */
  path: string | ((r: Records) => string | undefined);
  app: 'console' | 'portal' | 'e2e';
  /** Admin sub-sections: the side layout only (layouts do not change their bodies). */
  sideOnly?: boolean;
  /** An open state shot after the page settles (a menu, a drawer, a dialog ...). */
  state?: { name: string; open: (page: Page) => Promise<void> };
  /** Shot without waiting for the network: the loading state. */
  loading?: boolean;
}

// The config sets no action timeout and this test runs for hours: an element a screen no longer
// has would wait forever and hang the shard (the second and third full runs). Ten seconds, then
// the shot records the error as a finding and the run goes on.
const STATE_TIMEOUT = 10_000;
// Every action and navigation of a shot, so nothing waits forever.
const SHOT_TIMEOUT = 30_000;

const click = (testId: string) => async (page: Page) => {
  await page.getByTestId(testId).first().click({ timeout: STATE_TIMEOUT });
  await page.waitForTimeout(400);
};

// A record tab by its key (Ant Design's node key: the same in every language). At 390 the tab
// list scrolls sideways (AppearanceProvider hides the "more" menu), and a tab scrolled out of
// sight could take a pointer click meant for its neighbour (run 42977617899): click it in the DOM.
const tab = (key: string) => async (page: Page) => {
  const node = page.locator(`[data-node-key="${key}"] [role="tab"]`).first();
  await node.waitFor({ state: 'attached', timeout: STATE_TIMEOUT });
  await node.evaluate((el) => {
    (el as HTMLElement).click();
  });
  await page.waitForTimeout(400);
};

// A record operation: on the bar when it fits, else in the "more" menu (as helpers' clickAction).
const operation = (testId: string) => async (page: Page) => {
  const button = page.getByTestId(testId);
  if (await button.isVisible()) {
    await button.click({ timeout: STATE_TIMEOUT });
  } else {
    await page.getByTestId('inc-operations-more').click({ timeout: STATE_TIMEOUT });
    await page.getByTestId(`${testId}-menu`).click({ timeout: STATE_TIMEOUT });
  }
  await page.waitForTimeout(400);
};

const ADMIN_SECTIONS: Record<string, string[]> = {
  incidents: [
    'general',
    'templates',
    'checklists', // WP-046a S2: the checklist library
    'custom-fields',
    'statuses',
    'reasons',
    'priority',
    'categories',
    'levels',
    'closure-codes',
    'closing',
    'reply-templates',
    'task-templates', // WP-046a S1 (REQ-INC-074)
  ],
  sla: ['policies', 'calendars', 'holidays', 'settings'],
  automation: ['business-rules', 'triggers', 'routing', 'transitions'],
  organization: ['sites', 'departments', 'groups', 'desks'],
};

const incident = (r: Records) => (r.incident ? `/incidents/${r.incident}` : undefined);

export const SCREENS: Screen[] = [
  { key: 'home', path: '/', app: 'console' },
  { key: 'incidents', path: '/incidents', app: 'console' },
  { key: 'incident-new', path: '/incidents/new', app: 'console' },
  // WP-046a S5c (REQ-INC-019): a kept draft offered back, and one that could not be read
  // (lane C). The draft is answered in the browser: the matrix keeps none of its own.
  {
    key: 'incident-new',
    path: '/incidents/new',
    app: 'console',
    state: { name: 'kept-draft', open: keptDraft(false) },
  },
  {
    key: 'incident-new',
    path: '/incidents/new',
    app: 'console',
    state: { name: 'kept-draft-unreadable', open: keptDraft(true) },
  },
  {
    key: 'incident-new',
    path: '/incidents/new',
    app: 'console',
    state: {
      name: 'validation',
      open: async (page) => {
        await page.getByTestId('inc-save').click();
        await page.waitForTimeout(400);
      },
    },
  },
  { key: 'incident', path: incident, app: 'console' },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'composer', open: click('inc-op-reply') }, // the header's one Reply (D-155)
  },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'more-actions', open: click('inc-operations-more') },
  },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'assign', open: operation('inc-op-assign') },
  },
  // Template A (D-147): the empty properties behind "Add details", and the Worklogs form.
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'properties-all', open: click('inc-properties-add') },
  },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'worklogs', open: tab('worklogs') },
  },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'notifications', open: click('notifications-bell') },
  },
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: { name: 'user-menu', open: click('user-menu') }, // near the right edge (left in RTL)
  },
  // WP-046a S1 (REQ-INC-073, -075): a task's details drawer. The record may have no task yet, so
  // one is added first through the list's own form.
  {
    key: 'incident',
    path: incident,
    app: 'console',
    state: {
      name: 'task-details',
      open: async (page: Page) => {
        await tab('tasks')(page);
        if ((await page.getByTestId('inc-task-details-0').count()) === 0) {
          await page.getByTestId('inc-task-title').fill('Back up the switch');
          await page.getByTestId('inc-task-add').click({ timeout: STATE_TIMEOUT });
        }
        await click('inc-task-details-0')(page);
      },
    },
  },
  { key: 'my-tasks', path: '/my-tasks', app: 'console' }, // WP-046a S1 (REQ-INC-076)
  { key: 'change-calendar', path: '/changes/calendar', app: 'console' }, // WP-045c S3
  // WP-058b S5b (REQ-REL-056): releases by stage, the shared StageBoard.
  { key: 'release-board', path: '/releases/board', app: 'console' },
  {
    // WP-058b S1: the shared staged calendar on releases, and its timeline view (the fifth).
    key: 'release-calendar',
    path: '/releases/calendar',
    app: 'console',
    state: {
      name: 'timeline',
      open: async (page: Page) => {
        await page
          .getByTestId('calendar-view')
          .locator('.ant-segmented-item')
          .nth(4)
          .click({ timeout: STATE_TIMEOUT });
        await page.waitForTimeout(400);
      },
    },
  },
  { key: 'requests', path: '/requests', app: 'console' },
  {
    key: 'request',
    path: (r) => (r.request ? `/requests/${r.request}` : undefined),
    app: 'console',
  },
  {
    key: 'request',
    path: (r) => (r.request ? `/requests/${r.request}` : undefined),
    app: 'console',
    // The header's approvals drawer (the record has no own approvals button; QA9 matrix fix).
    state: { name: 'approvals', open: click('approvals-drawer-open') },
  },
  { key: 'knowledge', path: '/knowledge', app: 'console' },
  {
    key: 'article',
    path: (r) => (r.article ? `/knowledge/articles/${r.article}` : undefined),
    app: 'console',
  },
  { key: 'knowledge-approvals', path: '/knowledge/approvals', app: 'console' },
  // QA9: the routes the 11-09 coverage list found missing.
  { key: 'article-new', path: '/knowledge/articles/new', app: 'console' },
  {
    key: 'article-edit',
    path: (r) => (r.article ? `/knowledge/articles/${r.article}/edit/en` : undefined),
    app: 'console',
  },
  { key: 'problems', path: '/problems', app: 'console' },
  { key: 'problem-new', path: '/problems/new', app: 'console' },
  { key: 'known-errors', path: '/problems/known-errors', app: 'console' },
  {
    key: 'problem',
    path: (r) => (r.problem ? `/problems/${r.problem}` : undefined),
    app: 'console',
  },
  // Assets (WP-049a, D-155 template A; lane B): the list, one asset, vendors, loans, groups.
  { key: 'assets', path: '/assets', app: 'console' },
  // WP-049b s4a (lane B): the product type tree with a node chosen, the views drawer, and the
  // honest empty "recently discovered" view (no discovery yet).
  {
    key: 'asset-tree',
    path: '/assets',
    app: 'console',
    state: {
      name: 'node-chosen',
      open: async (page) => {
        // On a phone the tree waits behind its button (QA 2026-11-12 V-03): open it first.
        const toggle = page.getByTestId('asset-tree-toggle');
        if (await toggle.isVisible()) await toggle.click({ timeout: STATE_TIMEOUT });
        // The first type after "All types": its branch listed, its row chosen.
        await page
          .getByRole('treeitem')
          .nth(1)
          .locator('div')
          .first()
          .click({ timeout: STATE_TIMEOUT });
        await page.waitForTimeout(400);
      },
    },
  },
  {
    key: 'asset-views-drawer',
    path: '/assets',
    app: 'console',
    state: { name: 'views-drawer', open: click('assets-views-open') },
  },
  { key: 'assets-discovered', path: '/assets?view=recently_discovered', app: 'console' },
  {
    key: 'asset',
    path: (r) => (r.asset ? `/assets/${r.asset}` : undefined),
    app: 'console',
  },
  { key: 'asset-vendors', path: '/assets/vendors', app: 'console' },
  { key: 'asset-loans', path: '/assets/loans', app: 'console' },
  { key: 'asset-groups', path: '/assets/groups', app: 'console' },
  // WP-049b s2 (lane B): the asset record's Financials (costs, depreciation, book value), its
  // notes and files, and its history with the filters (REQ-AST-036..038, 048..050).
  {
    key: 'asset-financials',
    path: (r) => (r.asset ? `/assets/${r.asset}?tab=financials` : undefined),
    app: 'console',
  },
  {
    key: 'asset-notes',
    path: (r) => (r.asset ? `/assets/${r.asset}?tab=notes` : undefined),
    app: 'console',
  },
  {
    key: 'asset-history',
    path: (r) => (r.asset ? `/assets/${r.asset}?tab=history` : undefined),
    app: 'console',
  },
  // WP-049b s3 (lane B): asset audits, one running audit (items, progress, discrepancies), and
  // an asset's scan history (the showcase's scanned laptop, else the first asset).
  { key: 'asset-audits', path: '/assets/audits', app: 'console' },
  {
    key: 'asset-audit',
    path: (r) => (r.audit ? `/assets/audits/${r.audit}` : undefined),
    app: 'console',
  },
  {
    key: 'asset-scans',
    path: (r) => {
      const id = r.scannedAsset ?? r.asset;
      return id ? `/assets/${id}?tab=scans` : undefined;
    },
    app: 'console',
  },
  // WP-049b s1 (lane B): consumables, one consumable (stock, lots, ledger).
  { key: 'consumables', path: '/assets/consumables', app: 'console' },
  {
    key: 'consumable',
    path: (r) => (r.consumable ? `/assets/consumables/${r.consumable}` : undefined),
    app: 'console',
  },
  { key: 'releases', path: '/releases', app: 'console' },
  { key: 'release-new', path: '/releases/new', app: 'console' },
  {
    key: 'release',
    path: (r) => (r.release ? `/releases/${r.release}` : undefined),
    app: 'console',
    state: { name: 'changes', open: tab('changes') }, // WP-058b S1: the changes in it
  },
  {
    // WP-058b S2: the Schedule tab, where a release's conflicts, acks and override live.
    key: 'release-schedule',
    path: (r) => (r.release ? `/releases/${r.release}` : undefined),
    app: 'console',
    state: { name: 'schedule', open: tab('schedule') },
  },
  { key: 'request-new', path: '/requests/new', app: 'console' },
  { key: 'announcement-new', path: '/announcements/new', app: 'console' },
  {
    key: 'announcement',
    path: (r) => (r.announcement ? `/announcements/${r.announcement}` : undefined),
    app: 'console',
  },
  {
    key: 'admin-catalog-item',
    path: (r) => (r.catalogItem ? `/admin/catalog/items/${r.catalogItem}` : undefined),
    app: 'console',
    sideOnly: true,
  },
  // WP-048b S5: the runs overview (template C) and the designer's versions.
  { key: 'admin-workflows-runs', path: '/admin/workflows/runs', app: 'console', sideOnly: true },
  {
    key: 'admin-workflow-versions',
    path: (r) => (r.workflowRunFlow ? `/admin/workflows/${r.workflowRunFlow}` : undefined),
    app: 'console',
    sideOnly: true,
    // The move dialog over version 1, whose run is still live after version 2 was published.
    state: {
      name: 'move',
      open: async (page) => {
        await tab('versions')(page);
        await click('version-1-move')(page);
      },
    },
  },
  // WP-048b S4d: a record's Workflows tab, with a run waiting on it (template A's tabs).
  {
    key: 'incident-workflows',
    path: (r) => (r.workflowRun ? `/incidents/${r.workflowRun}` : undefined),
    app: 'console',
    state: { name: 'workflows', open: tab('workflows') },
  },
  // WP-046a S2: a record's checklists and all its files (template A's tabs), and your
  // reminders in the header (lane C's condition: 390 and 1280, en/ar, top/side).
  {
    key: 'incident-checklists',
    path: incident,
    app: 'console',
    state: { name: 'checklists', open: tab('checklists') },
  },
  {
    key: 'incident-files',
    path: incident,
    app: 'console',
    state: { name: 'files', open: tab('files') },
  },
  {
    key: 'home-reminders',
    path: '/',
    app: 'console',
    state: { name: 'reminders', open: click('reminders-drawer-open') },
  },
  // WP-048b S4: the designer, "template A header + canvas body"; its outline and problems.
  {
    key: 'admin-workflow',
    path: (r) => (r.workflow ? `/admin/workflows/${r.workflow}` : undefined),
    app: 'console',
    sideOnly: true,
  },
  {
    key: 'admin-workflow-outline',
    path: (r) => (r.workflow ? `/admin/workflows/${r.workflow}` : undefined),
    app: 'console',
    sideOnly: true,
    state: { name: 'outline', open: tab('outline') },
  },
  // A top-layout shot of a setup page (the admin pages are side-only otherwise).
  { key: 'admin-users-all-layouts', path: '/admin/users', app: 'console' },
  { key: 'announcements', path: '/announcements', app: 'console' },
  { key: 'dashboards', path: '/dashboards', app: 'console' },
  {
    key: 'dashboard',
    path: (r) => (r.dashboard ? `/dashboards/${r.dashboard}` : undefined),
    app: 'console',
  },
  { key: 'reports', path: '/reports', app: 'console' },
  { key: 'report', path: '/reports/builtin/incidents_open_by_priority', app: 'console' },
  // Notifications are a drawer from the header bell, not a route (QA9: /notifications was a 404).
  {
    key: 'notifications',
    path: '/',
    app: 'console',
    state: { name: 'drawer', open: click('notifications-bell') },
  },
  { key: 'profile', path: '/profile', app: 'console' },
  { key: 'not-found', path: '/no/such/page', app: 'console' },
  { key: 'admin', path: '/admin', app: 'console' },
  // WP-057 S1a (REQ-AUD-015): Audit › Sign-ins.
  { key: 'admin-audit-sign-ins', path: '/admin/audit?tab=sign_ins', app: 'console' },
  ...[
    'users',
    'roles',
    'security',
    'branding',
    'instance',
    'licence',
    'api-keys',
    'audit',
    'files',
    'mail',
    'integrations',
    'integrations/directories',
    'ai',
    'knowledge',
    'notifications',
    'requests',
    'portal',
    'catalog',
    'workflows',
    'change-windows', // WP-045c S3 (lane C's #381 review)
    // WP-058b S4: Admin › Releases, each section (template E).
    'releases/closure-codes',
    'releases/closing',
    'releases/stages',
    'releases/roles', // WP-058b S5a: what Take makes you
  ].map<Screen>((page) => ({
    key: `admin-${page.replace('/', '-')}`,
    path: `/admin/${page}`,
    app: 'console',
    sideOnly: true,
  })),
  // ADR-047 slice c: the role editor's Field access tab, and "Who sees this" in its modal.
  {
    key: 'admin-roles-field-access',
    path: '/admin/roles',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'tab',
      open: async (page) => {
        await click('role-row-technician')(page);
        await tab('field_access')(page);
      },
    },
  },
  {
    key: 'admin-roles-field-access-who',
    path: '/admin/roles',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'who',
      open: async (page) => {
        await click('role-row-technician')(page);
        await tab('field_access')(page);
        await click('field-access-who-impact_details')(page);
      },
    },
  },
  // WP-046a S5b: the template drawer with the form designer and a form rule open (lane C).
  {
    key: 'admin-incidents-template-designer',
    path: '/admin/incidents/templates',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'designer',
      open: async (page) => {
        await click('tpl-admin-new')(page);
        await click('tpl-layout-on')(page);
        await click('tpl-frule-add')(page);
        await page.getByTestId('tpl-layout').scrollIntoViewIfNeeded();
      },
    },
  },
  ...Object.entries(ADMIN_SECTIONS).flatMap(([area, sections]) =>
    sections.map<Screen>((section) => ({
      key: `admin-${area}-${section}`,
      path: `/admin/${area}/${section}`,
      app: 'console',
      sideOnly: true,
    })),
  ),
  // The e2e tenant: an empty list and a loading state (the showcase has rows everywhere).
  { key: 'incidents-empty', path: '/incidents?view=unassigned_mine', app: 'e2e' },
  { key: 'incidents-loading', path: '/incidents', app: 'e2e', loading: true },
  // The portal: no navigation layouts.
  { key: 'portal-home', path: '/', app: 'portal' },
  { key: 'portal-catalog', path: '/catalog', app: 'portal' },
  { key: 'portal-request-new', path: '/requests/new', app: 'portal' },
  { key: 'portal-requests', path: '/requests', app: 'portal' },
  { key: 'portal-service-requests', path: '/service-requests', app: 'portal' },
  { key: 'portal-approvals', path: '/approvals', app: 'portal' },
  { key: 'portal-approval-link', path: '/requests/approval-link', app: 'portal' },
  // WP-046a S6 (REQ-INC-066): stopping mails to someone kept informed, no sign-in. A made-up
  // token shows the dead link; the ask and done states answer the two public calls in the
  // browser (the matrix has no mail to take a real link from), lane C's #485 review.
  { key: 'portal-stop-mails', path: `/stop-mails#${STOP_TOKEN}`, app: 'portal' },
  {
    key: 'portal-stop-mails',
    path: `/stop-mails#${STOP_TOKEN}`,
    app: 'portal',
    state: { name: 'ask', open: stopMails(false) },
  },
  {
    key: 'portal-stop-mails',
    path: `/stop-mails#${STOP_TOKEN}`,
    app: 'portal',
    state: { name: 'done', open: stopMails(true) },
  },
  { key: 'portal-account', path: '/account', app: 'portal' },
  { key: 'portal-search', path: '/search?q=password', app: 'portal' },
  { key: 'portal-not-found', path: '/no/such/page', app: 'portal' },
];

interface Shot {
  file: string;
  screen: string;
  state?: string;
  layout: Layout | 'none';
  theme: string;
  lang: string;
  width: number;
  url: string;
  warnings: string[];
  axe: string[];
  /** Each serious violation's first node (selector and markup, cut): enough to find it. */
  axe_nodes?: string[];
  error?: string;
}

/** Cheap visual checks, in the page: findings only, never failures. */
function checks(): string[] {
  const out: string[] = [];
  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1) out.push('horizontal_scroll');
  const shown = (el: Element) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const name = (el: Element) =>
    (el.getAttribute('data-testid') ?? el.tagName.toLowerCase()) +
    (el.textContent ? `:${el.textContent.trim().slice(0, 24)}` : '');
  const boxes = [
    ...document.querySelectorAll('button, input, select, textarea, h1, h2, h3, .ant-btn'),
  ].filter(shown);
  const width = window.innerWidth;
  for (const el of boxes) {
    const r = el.getBoundingClientRect();
    // Inside a strip that scrolls sideways (a wide table, the editor's narrow toolbar) a control
    // past the edge is scrolled to, not lost (lane B's asset notes, 2026-11-11).
    let scroller: Element | null = el.parentElement;
    while (
      scroller !== null &&
      !['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX)
    ) {
      scroller = scroller.parentElement;
    }
    if (scroller === null && (r.right > width + 1 || r.left < -1)) {
      out.push(`off_screen:${name(el)}`);
    }
  }
  // A dialog, drawer, menu or popup lies over the page on purpose: only elements of the same
  // layer can overlap (QA9: the open assign dialog and notifications drawer were findings).
  // So does a sticky or fixed bar (a card's Save bar kept in reach, QA6 ADM-04): in a full-page
  // shot it is drawn where the first screen ends, over whatever field lies there, which a person
  // scrolls past (lane C's #460: the password card's "overlap" in Arabic at 390 px was this).
  const floating = (el: Element): Element | null => {
    for (let node: Element | null = el; node !== null; node = node.parentElement) {
      const position = getComputedStyle(node).position;
      if (position === 'sticky' || position === 'fixed') return node;
    }
    return null;
  };
  const layer = (el: Element) =>
    el.closest(
      '.ant-modal-root, .ant-drawer, .ant-dropdown, .ant-popover, .ant-select-dropdown, ' +
        '.ant-picker-dropdown, .ant-tooltip, .ant-notification, .ant-message',
    ) ?? floating(el);
  const firstBoxes = boxes.slice(0, 150);
  firstBoxes.forEach((aEl, i) => {
    const a = aEl.getBoundingClientRect();
    for (const bEl of firstBoxes.slice(i + 1)) {
      if (aEl.contains(bEl) || bEl.contains(aEl)) continue;
      if (layer(aEl) !== layer(bEl)) continue;
      const b = bEl.getBoundingClientRect();
      const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (w > 4 && h > 4) out.push(`overlap:${name(aEl)}|${name(bEl)}`);
    }
  });
  for (const el of document.querySelectorAll('body *')) {
    if (!(el instanceof HTMLElement) || !shown(el) || el.children.length > 0) continue;
    const s = getComputedStyle(el);
    // Text for screen readers only is clipped on purpose (a 1 px box or a clip rectangle, e.g.
    // the phone header's "Menu: <name>" on the avatar button): not a finding.
    const forScreenReaders =
      el.closest('.sx-visually-hidden') !== null ||
      s.getPropertyValue('clip').startsWith('rect(') ||
      s.clipPath.startsWith('inset(50%') ||
      el.clientWidth <= 1;
    const clipped =
      !forScreenReaders &&
      (s.overflow === 'hidden' || s.textOverflow === 'ellipsis') &&
      el.scrollWidth > el.clientWidth + 1;
    if (clipped && !el.title && !el.closest('[title]') && !el.closest('[aria-describedby]')) {
      out.push(`clipped:${name(el)}`);
    }
  }
  // A split button (Reply and its chevron) is one primary action drawn as two buttons.
  const primary = new Set(
    [...document.querySelectorAll('main .ant-btn-primary')]
      .filter(shown)
      .map((el) => el.closest('.ant-dropdown-button') ?? el),
  ).size;
  if (primary > 1) out.push(`primary_buttons:${String(primary)}`);
  for (const bar of document.querySelectorAll('[data-testid$="actions"], [role="toolbar"]')) {
    if (!shown(bar)) continue;
    // Wrapped = an item starts below another's bottom. Comparing tops alone flagged one row of
    // centred items of different heights (a 32px select beside 24px buttons; lane C polish).
    const boxes = [...bar.children].filter(shown).map((c) => c.getBoundingClientRect());
    const lowestTop = Math.max(...boxes.map((b) => b.top));
    const highestBottom = Math.min(...boxes.map((b) => b.bottom));
    if (boxes.length > 1 && lowestTop >= highestBottom - 1) out.push(`toolbar_wraps:${name(bar)}`);
  }
  return [...new Set(out)].slice(0, 40);
}

async function me(page: Page): Promise<{ csrf: string; id: string }> {
  const body = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
  };
  return { csrf: body.csrf_token, id: body.user.id };
}

/** The signed-in person's layout and language, through the API (If-Match, CSRF). */
async function prefer(page: Page, values: Record<string, string | null>): Promise<void> {
  const { csrf, id } = await me(page);
  const path = `/api/v1/users/${id}`;
  const current = (await (await page.request.get(path)).json()) as { version: number };
  const saved = await page.request.patch(path, {
    data: values,
    headers: { 'If-Match': `"${String(current.version)}"`, 'X-CSRF-Token': csrf },
  });
  if (saved.status() !== 200) throw new Error(`preferences: ${String(saved.status())}`);
}

async function findRecords(page: Page): Promise<Records> {
  const first = async (url: string, pick: (body: unknown) => string | undefined) => {
    const response = await page.request.get(url);
    return response.ok() ? pick(await response.json()) : undefined;
  };
  const firstItem = (body: unknown) => ((body as { items?: { id: string }[] }).items ?? [])[0]?.id;
  // Some lists are a plain array (knowledge articles, catalog items: QA9 matrix fix).
  const firstOfList = (body: unknown) =>
    (Array.isArray(body) ? (body as { id: string }[]) : [])[0]?.id;
  const incident =
    (await first('/api/v1/incidents/lookup/INC-30', (b) => (b as { id?: string }).id)) ??
    (await first('/api/v1/incidents?limit=1', firstItem));
  return {
    incident,
    ...(await showcaseRun(page, incident).then((made) =>
      made === undefined ? {} : { workflowRun: made.incident, workflowRunFlow: made.flow },
    )),
    request: await first('/api/v1/service-requests?limit=1', firstItem),
    article: await first('/api/v1/knowledge/articles', firstOfList),
    dashboard: await first(
      '/api/v1/dashboards',
      (b) => ((b as { items?: { ref: string }[] }).items ?? [])[0]?.ref,
    ),
    problem: await first('/api/v1/problems?limit=1', firstItem),
    release: await first('/api/v1/releases?limit=1', firstItem),
    announcement: await first('/api/v1/announcements?limit=1', firstItem),
    asset: await first('/api/v1/assets?limit=1', firstItem),
    consumable: await first('/api/v1/assets/consumables', firstOfList),
    // WP-049b s3: the showcase's running audit, and its laptop with scans (SX-LAP-001).
    audit: await first('/api/v1/assets/audits', firstOfList),
    scannedAsset: await first('/api/v1/assets?search=SX-LAP-001&limit=1', firstItem),
    catalogItem: await first('/api/v1/catalog/items', firstOfList),
    workflow:
      (await first('/api/v1/automation/workflows?record_type=incident', firstOfList)) ??
      (await showcaseWorkflow(page)),
  };
}

/**
 * A workflow run on an incident for its Workflows tab (WP-048b S4d): start → wait for a change
 * → end, published, switched on and started on the incident, so the tab shows a run waiting.
 * Returns the incident's ID; a stack that refuses any step simply has no such shot.
 */
async function showcaseRun(
  page: Page,
  incident: string | undefined,
): Promise<{ incident: string; flow: string } | undefined> {
  if (incident === undefined) return undefined;
  const { csrf } = await me(page);
  const write = { 'X-CSRF-Token': csrf };
  const made = await page.request.post('/api/v1/automation/workflows', {
    data: { record_type: 'incident', name: 'Wait for the requester' },
    headers: { ...write, 'Idempotency-Key': crypto.randomUUID() },
  });
  if (!made.ok()) return undefined;
  let flow = (await made.json()) as { id: string; version: number };
  const step = async (method: 'put' | 'post', path: string, data?: unknown) => {
    const response = await page.request[method](`/api/v1/automation/workflows/${flow.id}${path}`, {
      data,
      headers: { ...write, 'If-Match': `"${String(flow.version)}"` },
    });
    if (!response.ok()) return false;
    flow = (await response.json()) as typeof flow;
    return true;
  };
  const at = (x: number, y: number) => ({ x, y });
  const definition = {
    format: 1,
    nodes: [
      { id: 'start', type: 'start', config: {}, position: at(0, 0) },
      {
        id: 'reply',
        type: 'wait',
        config: { events: ['requester_replied'], limit_seconds: 86_400 },
        position: at(0, 140),
      },
      { id: 'end', type: 'end', config: {}, position: at(0, 280) },
    ],
    links: [
      { from: 'start', port: 'next', to: 'reply' },
      { from: 'reply', port: 'next', to: 'end' },
      { from: 'reply', port: 'overtaken', to: 'end' },
      { from: 'reply', port: 'timeout', to: 'end' },
    ],
    variables: [],
  };
  if (!(await step('put', '/draft', { definition }))) return undefined;
  if (!(await step('post', '/publish'))) return undefined;
  if (!(await step('put', '/enabled', { enabled: true }))) return undefined;
  const started = await page.request.post(`/api/v1/automation/workflows/${flow.id}/instances`, {
    data: { record_id: incident },
    headers: { ...write, 'Idempotency-Key': crypto.randomUUID() },
  });
  if (!started.ok()) return undefined;
  // Version 2 (the same steps): the run stays on version 1, so the Versions tab can move it.
  if (!(await step('put', '/draft', { definition }))) return { incident, flow: flow.id };
  await step('post', '/publish');
  return { incident, flow: flow.id };
}

/**
 * A workflow to shoot when the stack has none (WP-048b S4): REQ-WF-008 AC1's shape, start → if
 * → notification → set status → end, laid out top to bottom, with one problem left in (the
 * condition is empty) so the problem chip and marker are in the shot too.
 */
async function showcaseWorkflow(page: Page): Promise<string | undefined> {
  const { csrf } = await me(page);
  const made = await page.request.post('/api/v1/automation/workflows', {
    data: { record_type: 'incident', name: 'Major incident follow-up' },
    headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-CSRF-Token': csrf },
  });
  if (!made.ok()) return undefined;
  const flow = (await made.json()) as { id: string; version: number };
  const at = (x: number, y: number) => ({ x, y });
  await page.request.put(`/api/v1/automation/workflows/${flow.id}/draft`, {
    data: {
      definition: {
        format: 1,
        nodes: [
          { id: 'start', type: 'start', config: {}, position: at(0, 0) },
          { id: 'is_major', type: 'if', config: {}, position: at(0, 140) },
          {
            id: 'tell_team',
            type: 'notify',
            config: {
              audience: { relatives: ['group', 'group_head'] },
              subject: { en: 'Major incident', ar: 'حادث كبير' },
              body: { en: 'A major incident needs the team.', ar: 'حادث كبير يحتاج إلى الفريق.' },
            },
            position: at(-130, 280),
          },
          {
            id: 'work',
            type: 'set_status',
            config: { action: 'start_work' },
            position: at(-130, 420),
          },
          { id: 'end', type: 'end', config: {}, position: at(0, 560) },
        ],
        links: [
          { from: 'start', port: 'next', to: 'is_major' },
          { from: 'is_major', port: 'yes', to: 'tell_team' },
          { from: 'is_major', port: 'no', to: 'end' },
          { from: 'tell_team', port: 'next', to: 'work' },
          { from: 'work', port: 'next', to: 'end' },
        ],
        variables: [],
      },
    },
    headers: { 'If-Match': `"${String(flow.version)}"`, 'X-CSRF-Token': csrf },
  });
  return flow.id;
}

async function shoot(main: Page, shot: Shot, screen: Screen): Promise<void> {
  // A loading state is shot on a page of its own, closed afterwards: closing it aborts the
  // requests still held back, so none of them is left hanging on the page every later shot uses
  // (the second full run waited out 75 minutes on such requests).
  const page = screen.loading ? await main.context().newPage() : main;
  page.setDefaultTimeout(SHOT_TIMEOUT);
  try {
    if (screen.loading) {
      await page.setViewportSize(main.viewportSize() ?? { width: 1280, height: 900 });
      await page.route('**/api/v1/**', async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 4000));
        // The page may be closed before the delay ends: a late continue is then refused.
        await route.continue().catch(() => undefined);
      });
      await page.goto(shot.url, { waitUntil: 'commit' });
      await page.waitForTimeout(1200);
    } else {
      await page.goto(shot.url);
      await page
        .locator('main')
        .first()
        .waitFor({ timeout: 15_000 })
        .catch(() => undefined);
      await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => undefined);
      await page.waitForTimeout(500);
      if (screen.state) await screen.state.open(page);
    }
    // A full-page shot keeps the window's own height for layout, so a footer bar sticky to the
    // window's foot was drawn in the middle of a long form, over its fields (QA V-01). In the
    // shot it sits where it ends up once the page is scrolled to the end.
    await page
      .addStyleTag({ content: '[data-sticky-footer] { position: static !important; }' })
      .catch(() => undefined);
    await page.screenshot({
      path: `${OUT}/${shot.file}`,
      fullPage: true,
      type: 'jpeg',
      quality: 80,
    });
    shot.warnings = await page.evaluate(checks);
    if (!screen.loading) {
      const results = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze();
      const serious = results.violations.filter(
        (v) => v.impact === 'serious' || v.impact === 'critical',
      );
      shot.axe = serious.map((v) => `${v.id} (${String(v.nodes.length)})`);
      // The first node of each (QA10V-30: without it, a one-node finding needed another run).
      shot.axe_nodes = serious.flatMap((v) => {
        const node = v.nodes[0];
        if (node === undefined) return [];
        return [`${v.id}: ${node.target.join(' ')} ${node.html.slice(0, 200)}`];
      });
    }
  } catch (error) {
    // A screen that breaks is a finding, not a crash of the run.
    shot.error = error instanceof Error ? error.message.split('\n')[0] : String(error);
  } finally {
    if (screen.loading) await page.close().catch(() => undefined);
  }
}

test.skip(!RUN, 'the visual matrix runs in its own workflow (VISUAL_MATRIX=1)');

test(`visual matrix, shard ${String(SHARD)}/${String(SHARDS)}`, async ({ browser }) => {
  test.setTimeout(3 * 60 * 60_000);
  mkdirSync(OUT, { recursive: true });
  const mine = SCREENS.filter(wanted).filter((_, index) => index % SHARDS === SHARD - 1);
  const shots: Shot[] = [];
  const skipped: string[] = [];

  for (const app of ['console', 'e2e', 'portal'] as const) {
    const screens = mine.filter((s) => s.app === app);
    if (screens.length === 0) continue;
    // The console keeps the config's own base URL: passing undefined would drop it.
    const context = await browser.newContext({
      baseURL: app === 'portal' ? PORTAL_URL : test.info().project.use.baseURL,
    });
    const page = await context.newPage();
    page.setDefaultTimeout(SHOT_TIMEOUT);
    if (app === 'console') {
      expect(SHOWCASE_PASSWORD, 'SUPPORTX_SHOWCASE_PASSWORD').not.toBe('');
      await signIn(page, 'admin@showcase.test', SHOWCASE_PASSWORD, '/');
    } else if (app === 'e2e') {
      await signIn(page, USERS.tech.email, passwordOf('tech'), '/');
    } else {
      await signIn(page, SEEDED.arabic.email, SEEDED.arabic.password, `${PORTAL_URL}/`);
    }
    const records = app === 'console' ? await findRecords(page) : {};
    const before = (await (
      await page.request.get(`/api/v1/users/${(await me(page)).id}`)
    ).json()) as {
      nav_layout: string | null;
      ui_locale: string | null;
    };
    try {
      const layouts: readonly (Layout | 'none')[] = app === 'portal' ? ['none'] : LAYOUTS;
      for (const layout of layouts) {
        for (const lang of LANGS) {
          await prefer(
            page,
            layout === 'none' ? { ui_locale: lang } : { nav_layout: layout, ui_locale: lang },
          );
          for (const theme of THEMES) {
            await page.goto('/');
            await page.evaluate((mode) => {
              window.localStorage.setItem('supportx.theme_mode', mode);
            }, theme);
            for (const width of WIDTHS) {
              await page.setViewportSize({ width, height: 900 });
              for (const screen of screens) {
                if (screen.sideOnly && layout !== 'side') continue;
                const path = typeof screen.path === 'string' ? screen.path : screen.path(records);
                const label = `${screen.key}${screen.state ? `~${screen.state.name}` : ''}`;
                if (path === undefined) {
                  skipped.push(label);
                  continue;
                }
                const shot: Shot = {
                  file: `${label}__${layout}__${theme}__${lang}__${String(width)}.jpg`,
                  screen: screen.key,
                  state: screen.state?.name,
                  layout,
                  theme,
                  lang,
                  width,
                  url: path,
                  warnings: [],
                  axe: [],
                };
                await shoot(page, shot, screen);
                shots.push(shot);
              }
            }
          }
        }
      }
    } finally {
      await prefer(
        page,
        app === 'portal'
          ? { ui_locale: before.ui_locale }
          : { nav_layout: before.nav_layout ?? 'side', ui_locale: before.ui_locale },
      ).catch(() => undefined);
      await context.close();
    }
  }
  writeFileSync(
    `${OUT}/index-${String(SHARD)}.json`,
    JSON.stringify(
      {
        shard: `${String(SHARD)}/${String(SHARDS)}`,
        shots,
        skipped: [...new Set(skipped)],
        summary: {
          shots: shots.length,
          errors: shots.filter((s) => s.error).length,
          with_warnings: shots.filter((s) => s.warnings.length > 0).length,
          with_axe: shots.filter((s) => s.axe.length > 0).length,
        },
      },
      null,
      2,
    ),
  );
});
