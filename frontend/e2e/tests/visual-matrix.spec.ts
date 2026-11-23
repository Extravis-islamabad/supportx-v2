import { mkdirSync, writeFileSync } from 'node:fs';

import AxeBuilder from '@axe-core/playwright';
import { expect, test, type ConsoleMessage, type Page, type Route } from '@playwright/test';

import { PORTAL_URL, passwordOf, SEEDED, USERS } from '../stack';
import { FAKE, ME, asHoldManager, mockErasures, mockPeopleList } from './erasureMocks';
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
  // A key also selects the screens split off it as `<key>-<part>` (lane C, #559): `incidents`
  // still shoots the board, cards and calendar states, kept apart so they can run alone.
  const parts: Record<string, readonly string[]> = {
    incidents: ['incidents-board', 'incidents-cards', 'incidents-calendar'],
  };
  return ONLY.some((key) =>
    key.endsWith('*')
      ? screen.key.startsWith(key.slice(0, -1))
      : screen.key === key || (parts[key] ?? []).includes(screen.key),
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
    | 'workflowRunFlow'
    | 'ci'
    | 'businessView'
    | 'ciType',
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

// WP-053 S4a (#574): one rule, one run, and the preview's answer, shaped as the API's schema.
const SYNC_RULE = '01936f2a-5b1c-7000-8000-00000000c501';
const SYNC_RUN = '01936f2a-5b1c-7000-8000-00000000c502';
const SYNC_ASSET = '01936f2a-5b1c-7000-8000-00000000c503';

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
  state?: {
    name: string;
    open: (page: Page) => Promise<void>;
    /** Undo what `open` changed for the whole tenant, so later shots see the stack as it was. */
    close?: (page: Page) => Promise<void>;
  };
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

// ADR-052 erasure screens: answered in the browser (erasureMocks.ts), made-up people only.
// Nothing is requested, redacted or approved on any server (the coordinator's condition 2).
const ERASURE_PATH = `/admin/erasures/${FAKE.erasure}`;
const erasureState = (name: string, testId: string, after?: (page: Page) => Promise<void>) => ({
  name,
  open: async (page: Page) => {
    await mockErasures(page, { reviewed: true });
    await page.reload();
    await page.getByTestId(testId).first().waitFor({ timeout: STATE_TIMEOUT });
    if (after) await after(page);
    await page.waitForTimeout(400);
  },
});
const privacyTab = async (page: Page, held: boolean, reasonShown = true) => {
  await mockErasures(page, { exists: false, held, reasonShown });
  await mockPeopleList(page);
  await page.reload();
  const crashes: string[] = [];
  const crashed = (error: Error) => {
    crashes.push(error.message);
  };
  page.on('pageerror', crashed);
  const before = page.url();
  await page.getByText('Noor Hassan').first().click({ timeout: STATE_TIMEOUT });
  const tab = page.locator('[data-node-key="privacy"] [role="tab"]').first();
  const opened = await page
    .locator('.ant-drawer [data-node-key="details"]')
    .first()
    .waitFor({ timeout: STATE_TIMEOUT })
    .then(() => true)
    .catch(() => false);
  if (!opened) {
    // Say what is there instead (#532 run 44120567969).
    const drawers = await page.locator('.ant-drawer-content').allInnerTexts();
    const rows = await page.getByText('Noor Hassan').count();
    // A picture of what the click led to, kept with the run's shots (lane C, #532).
    const picture = `drawer-failure-${String(Date.now())}.jpg`;
    await page
      .screenshot({ path: `${OUT}/${picture}`, fullPage: true, type: 'jpeg', quality: 70 })
      .catch(() => undefined);
    throw new Error(
      `person drawer: no tabs; url ${before} -> ${page.url()}; Noor Hassan matches ${String(rows)};` +
        ` drawer text: ${drawers.join(' | ').slice(0, 300)}; picture ${picture};` +
        ` page errors: ${crashes.join(' | ').slice(0, 400)}`,
    );
  }
  if (await tab.isVisible()) {
    await tab.click({ timeout: STATE_TIMEOUT });
  } else {
    // Five tabs in a drawer: antd moves the last ones into its "more" menu (run 44102835733).
    await page.locator('.ant-drawer .ant-tabs-nav-more').first().click({ timeout: STATE_TIMEOUT });
    await page
      .locator('.ant-tabs-dropdown-menu-item[data-menu-id$="privacy"]')
      .first()
      .click({ timeout: STATE_TIMEOUT });
  }
  page.off('pageerror', crashed);
  // Later shots of the people list read the real list again.
  await page.unroute(/\/api\/v1\/users(\?.*)?$/u);
};
const requestDrawer = (page: Page) => privacyTab(page, false);

// WP-046b S3a (lane C's states, rule 8 OK): a starred view, an unread row and row colours on the
// incident list; the General tab's row colour and view audit cards. Seeded through the API as
// the matrix's own admin; the unread row comes from a second person's real public reply, so the
// live path runs. Each shot re-seeds (idempotent): another screen may have opened INC-30.
const STARRED_VIEW = 'Matrix: an unread row';
const UNREAD_SUBJECT = 'Matrix: an unread row';
let replier: Page | undefined;
let unreadIncident: { id: string; display_id: string } | undefined;
// The tenant's colouring before the shot, put back by `close` (lane C: it is tenant-wide).
let colouringBefore: string | undefined;

async function replierPage(page: Page): Promise<Page> {
  if (replier !== undefined) return replier;
  const browser = page.context().browser();
  if (browser === null) throw new Error('no browser for the second person');
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const other = await context.newPage();
  other.setDefaultTimeout(SHOT_TIMEOUT);
  // As the matrix signs in its own admin: the showcase password comes from the environment.
  await signIn(other, 'tech@showcase.test', SHOWCASE_PASSWORD, '/');
  replier = other;
  return other;
}

/** The matrix's own incident for this state (never INC-30: other screens shoot that one). */
async function unreadRecord(page: Page, other: Page): Promise<{ id: string; display_id: string }> {
  if (unreadIncident !== undefined) return unreadIncident;
  const filter = JSON.stringify({ field: 'subject', op: 'eq', value: UNREAD_SUBJECT });
  const found = (await (
    await page.request.get(`/api/v1/incidents?limit=1&filter=${encodeURIComponent(filter)}`)
  ).json()) as { items?: { id: string; display_id: string }[] };
  const existing = found.items?.[0];
  if (existing !== undefined) return (unreadIncident = existing);
  const admin = await me(page);
  const theirs = await me(other);
  // In a group the second person works, so their reply is theirs to make.
  const groups = (await (await page.request.get('/api/v1/organization/groups')).json()) as {
    id: string;
    member_ids: string[];
  }[];
  const group = groups.find((g) => g.member_ids.includes(theirs.id));
  if (group === undefined) throw new Error('no group of the second person');
  const made = await page.request.post('/api/v1/incidents', {
    data: { subject: UNREAD_SUBJECT, requester_id: admin.id, group_id: group.id },
    headers: {
      'X-CSRF-Token': admin.csrf,
      'X-SupportX-Client': 'console',
      'Idempotency-Key': crypto.randomUUID(),
    },
  });
  if (!made.ok()) throw new Error(`incident: ${String(made.status())}`);
  return (unreadIncident = (await made.json()) as { id: string; display_id: string });
}

async function setColouring(page: Page, value: string): Promise<string> {
  const { csrf } = await me(page);
  const display = (await (
    await page.request.get('/api/v1/incidents/settings/list-display')
  ).json()) as { row_colour_by: string; settings_version: number };
  if (display.row_colour_by !== value) {
    const set = await page.request.put('/api/v1/incidents/settings/list-display', {
      data: { row_colour_by: value },
      headers: { 'X-CSRF-Token': csrf, 'If-Match': `"${String(display.settings_version)}"` },
    });
    if (!set.ok()) throw new Error(`row colours: ${String(set.status())}`);
  }
  return display.row_colour_by;
}

async function starredUnreadColoured(page: Page): Promise<void> {
  const { csrf } = await me(page);
  const write = { 'X-CSRF-Token': csrf };
  const other = await replierPage(page);
  const incident = await unreadRecord(page, other);
  // A view of that incident alone, starred.
  const views = (await (await page.request.get('/api/v1/incidents/saved-views')).json()) as {
    id: string;
    name: string;
  }[];
  let view = views.find((v) => v.name === STARRED_VIEW);
  if (view === undefined) {
    const made = await page.request.post('/api/v1/incidents/saved-views', {
      data: {
        name: STARRED_VIEW,
        filter: { field: 'display_id', op: 'eq', value: incident.display_id },
      },
      headers: { ...write, 'Idempotency-Key': crypto.randomUUID() },
    });
    if (!made.ok()) throw new Error(`saved view: ${String(made.status())}`);
    view = (await made.json()) as { id: string; name: string };
  }
  const star = await page.request.put(`/api/v1/incidents/saved-views/${view.id}/favourite`, {
    headers: write,
  });
  if (!star.ok()) throw new Error(`star: ${String(star.status())}`);
  colouringBefore = await setColouring(page, 'priority');
  // Read by the admin, then a public reply by someone else: unread again.
  const read = await page.request.post(`/api/v1/incidents/${incident.id}/read`, { headers: write });
  if (!read.ok()) throw new Error(`read: ${String(read.status())}`);
  const theirs = await me(other);
  const replied = await other.request.post(`/api/v1/incidents/${incident.id}/conversation`, {
    data: { kind: 'note', visibility: 'public', body: '<p>Checked on site: still failing.</p>' },
    headers: { 'X-CSRF-Token': theirs.csrf, 'Idempotency-Key': crypto.randomUUID() },
  });
  if (!replied.ok()) throw new Error(`reply: ${String(replied.status())}`);
  // The list keeps its view on the screen, not in the address: picked as a person does, from
  // the Starred group (lane C's run 44391110161 timed out on a ?view= address).
  await page.goto('/incidents');
  const seen = async (what: string, locator: ReturnType<Page['locator']>) => {
    try {
      await locator.first().waitFor({ timeout: STATE_TIMEOUT });
    } catch {
      throw new Error(`starred-unread-coloured: no ${what}`);
    }
  };
  await page.getByTestId('inc-view').click({ timeout: STATE_TIMEOUT });
  await seen(
    'starred view in the picker',
    page.locator('.ant-select-item-option', { hasText: STARRED_VIEW }),
  );
  await page.locator('.ant-select-item-option', { hasText: STARRED_VIEW }).first().click();
  // The picker's list fades out: shot only once it is gone (lane C; #548's compare state too).
  try {
    await page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
      .first()
      .waitFor({ state: 'hidden', timeout: STATE_TIMEOUT });
  } catch {
    throw new Error('starred-unread-coloured: the view picker did not close');
  }
  await seen('star toggle', page.getByTestId('inc-view-star'));
  await seen('unread row', page.locator('[data-unread="true"]'));
  await seen('row colour mark', page.locator('[data-row-mark]'));
}

/** Put the tenant's colouring back as it was before the shot. */
async function restoreColouring(page: Page): Promise<void> {
  if (colouringBefore === undefined) return;
  await setColouring(page, colouringBefore);
  colouringBefore = undefined;
}

const generalCard = (testId: string) => async (page: Page) => {
  const card = page.getByTestId(testId);
  await card.scrollIntoViewIfNeeded({ timeout: STATE_TIMEOUT });
  await card.waitFor({ timeout: STATE_TIMEOUT });
  // Back to the top: the full-page shot holds the card anyway, and a scrolled page drew the
  // sticky side nav halfway down (lane C, run 44391110161).
  await page.evaluate(() => {
    window.scrollTo(0, 0);
  });
};

// WP-046b S3b (lane C's states): the incident list as cards, a board and a calendar. The layout
// is picked from the toolbar's switch as a person does, and put back to the table by `close`
// (it is the matrix admin's own setting, kept per view).
const DUE_SUBJECT = 'Matrix: due the same day';

async function pickLayout(page: Page, label: RegExp): Promise<void> {
  // The shot has already opened the list: no second navigation (each one costs seconds, for
  // every layout, theme, language and width).
  const switcher = page.getByTestId('inc-layout');
  await switcher.waitFor({ timeout: STATE_TIMEOUT });
  // Usable once the person's setting is read.
  await switcher
    .locator('.ant-segmented-item:not(.ant-segmented-item-disabled)', { hasText: label })
    .first()
    .click({ timeout: STATE_TIMEOUT });
}

async function backToTable(page: Page): Promise<void> {
  await pickLayout(page, /^(Table|جدول)$/u);
}

const seenOrSay = async (what: string, locator: ReturnType<Page['locator']>) => {
  try {
    await locator.first().waitFor({ timeout: STATE_TIMEOUT });
  } catch {
    throw new Error(`layouts: no ${what}`);
  }
};

/** The board's grouping, picked as a person does (it is kept in their list settings). */
async function groupBy(page: Page, label: RegExp): Promise<void> {
  await page
    .getByTestId('inc-board-group-by')
    .locator('.ant-segmented-item', { hasText: label })
    .first()
    .click({ timeout: STATE_TIMEOUT });
}

/** Back to the board by status, then the table: the grouping is the person's too. */
async function backToStatusAndTable(page: Page): Promise<void> {
  await groupBy(page, /status|الحالة/iu);
  await backToTable(page);
}

async function boardRefused(page: Page): Promise<void> {
  await pickLayout(page, /^(Board|لوحة)$/u);
  await seenOrSay('board', page.getByTestId('inc-board'));
  // By status whatever was kept: a board by technician has no "Closed" to move to (the first
  // run: every shot after the technician state timed out here).
  await groupBy(page, /status|الحالة/iu);
  // A card moved where its life cycle has no step (open to closed): it stays and says why.
  const opener = page.locator('[data-testid^="inc-board-stage-move-"]').first();
  await seenOrSay('card on the board', opener);
  await opener.click({ timeout: STATE_TIMEOUT });
  const menu = page.locator('.ant-dropdown:not(.ant-dropdown-hidden) [role="menu"]').last();
  await seenOrSay('"Move to" menu', menu);
  await menu
    .locator('[role="menuitem"]', { hasText: /Closed|مغلق/u })
    .first()
    .click({ timeout: STATE_TIMEOUT });
  await seenOrSay('refusal', page.locator('[data-testid="inc-board-stage-refusal"]:not(:empty)'));
  // The "Move to" menu fades out after the choice: shot only once it has gone (lane C F1).
  await page
    .locator('.ant-dropdown:not(.ant-dropdown-hidden)')
    .first()
    .waitFor({ state: 'hidden', timeout: STATE_TIMEOUT })
    .catch(() => undefined);
}

async function boardByTechnicianMore(page: Page): Promise<void> {
  await pickLayout(page, /^(Board|لوحة)$/u);
  await groupBy(page, /technician|الفني/iu);
  // Only with more than twelve people holding records: said as a finding at once otherwise,
  // never waited out on every layout, theme, language and width.
  await seenOrSay('board by technician', page.locator('[data-testid^="inc-board-stage-heading-"]'));
  // The counts arrive after the columns: a short wait before saying there is none (one shot
  // of run 44762732484 counted while they loaded).
  await page
    .getByTestId('inc-board-more-columns')
    .waitFor({ timeout: 5_000 })
    .catch(() => undefined);
  if ((await page.getByTestId('inc-board-more-columns').count()) === 0) {
    // Recorded as a finding with the number, never a skip (lane C).
    const people = await page
      .locator('[data-testid^="inc-board-stage-heading-"]:not([data-testid$="__none__"])')
      .count();
    throw new Error(`layouts: no "More columns": ${String(people)} technicians hold records`);
  }
  await page.getByTestId('inc-board-more-columns').click({ timeout: STATE_TIMEOUT });
  await seenOrSay(
    'columns menu',
    page.locator('.ant-dropdown:not(.ant-dropdown-hidden) [role="menu"]'),
  );
}

const cards = (compact: boolean) => async (page: Page) => {
  await pickLayout(page, /^(Cards|بطاقات)$/u);
  await seenOrSay('cards', page.getByTestId('inc-cards'));
  if (compact) {
    await page
      .getByTestId('inc-cards-density')
      .locator('.ant-segmented-item', { hasText: /Compact|مضغوط/u })
      .click({ timeout: STATE_TIMEOUT });
  }
};

/** Five incidents of one priority, created together, so they fall due the same day. */
async function dueTogether(page: Page): Promise<void> {
  const filter = JSON.stringify({ field: 'subject', op: 'eq', value: DUE_SUBJECT });
  const found = (await (
    await page.request.post('/api/v1/incidents/list', {
      data: { filter: JSON.parse(filter) as unknown, limit: 5 },
      headers: { 'X-CSRF-Token': (await me(page)).csrf },
    })
  ).json()) as { items?: unknown[] };
  const admin = await me(page);
  for (let n = found.items?.length ?? 0; n < 5; n += 1) {
    const made = await page.request.post('/api/v1/incidents', {
      // The tenant's default priority for all five: the same targets, so the same due day.
      data: { subject: DUE_SUBJECT, requester_id: admin.id },
      headers: {
        'X-CSRF-Token': admin.csrf,
        'X-SupportX-Client': 'console',
        'Idempotency-Key': crypto.randomUUID(),
      },
    });
    if (!made.ok()) throw new Error(`due incident: ${String(made.status())}`);
  }
}

const calendar = (shown: 'month' | 'week' | 'more') => async (page: Page) => {
  if (shown === 'more') await dueTogether(page);
  await pickLayout(page, /^(Calendar|تقويم)$/u);
  await seenOrSay('calendar', page.getByTestId('inc-calendar'));
  if (shown === 'week') {
    await page
      .getByTestId('inc-cal-view')
      .locator('.ant-segmented-item', { hasText: /Week|أسبوع/u })
      .click({ timeout: STATE_TIMEOUT });
  }
  if (shown === 'more') {
    // Forward to the month they fall due in, when it is not this one.
    const more = page.locator('[data-testid^="inc-cal-more-"]');
    // This month's records first (one shot of run 44762732484 looked before they loaded).
    await more
      .first()
      .waitFor({ timeout: 5_000 })
      .catch(() => undefined);
    for (let step = 0; step < 2 && (await more.count()) === 0; step += 1) {
      await page.getByTestId('inc-cal-next').click({ timeout: STATE_TIMEOUT });
      await page.waitForLoadState('networkidle');
    }
    await seenOrSay('"N more" (five due the same day)', more);
    await more.first().click({ timeout: STATE_TIMEOUT });
    await seenOrSay('day list', page.locator('[data-testid^="inc-cal-list-"]'));
    // Back to the top for the full-page shot: a scrolled page drew the sticky side navigation
    // part-way down (lane C, run 44762732484; as generalCard does).
    await page.evaluate(() => {
      window.scrollTo(0, 0);
    });
  }
};

export const SCREENS: Screen[] = [
  { key: 'home', path: '/', app: 'console' },
  { key: 'incidents', path: '/incidents', app: 'console' },
  {
    key: 'incidents',
    path: '/incidents',
    app: 'console',
    state: {
      name: 'starred-unread-coloured',
      open: starredUnreadColoured,
      close: restoreColouring,
    },
  },
  {
    key: 'incidents-board',
    path: '/incidents',
    app: 'console',
    state: { name: 'board-refused', open: boardRefused, close: backToTable },
  },
  {
    key: 'incidents-board',
    path: '/incidents',
    app: 'console',
    state: {
      name: 'board-technician-more',
      open: boardByTechnicianMore,
      close: backToStatusAndTable,
    },
  },
  {
    key: 'incidents-cards',
    path: '/incidents',
    app: 'console',
    state: { name: 'cards', open: cards(false), close: backToTable },
  },
  {
    key: 'incidents-cards',
    path: '/incidents',
    app: 'console',
    state: { name: 'cards-compact', open: cards(true), close: backToTable },
  },
  {
    key: 'incidents-calendar',
    path: '/incidents',
    app: 'console',
    state: { name: 'calendar-month', open: calendar('month'), close: backToTable },
  },
  {
    key: 'incidents-calendar',
    path: '/incidents',
    app: 'console',
    state: { name: 'calendar-week', open: calendar('week'), close: backToTable },
  },
  {
    key: 'incidents-calendar',
    path: '/incidents',
    app: 'console',
    state: { name: 'calendar-more', open: calendar('more'), close: backToTable },
  },
  {
    key: 'admin-incidents-general',
    path: '/admin/incidents',
    app: 'console',
    sideOnly: true,
    state: { name: 'row-colours', open: generalCard('settings-row-colours') },
  },
  {
    key: 'admin-incidents-general',
    path: '/admin/incidents',
    app: 'console',
    sideOnly: true,
    state: { name: 'view-audit', open: generalCard('settings-view-audit') },
  },
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
  // WP-053 S1 (lane B; lane C's #524 review): the CMDB list with its type tree, one CI, a new CI,
  // the CI record with someone else's save in the way (ConflictDialog) and Admin › CMDB.
  { key: 'cmdb', path: '/cmdb', app: 'console' },
  { key: 'ci', path: (r) => (r.ci ? `/cmdb/${r.ci}` : undefined), app: 'console' },
  {
    key: 'ci-conflict',
    path: (r) => (r.ci ? `/cmdb/${r.ci}` : undefined),
    app: 'console',
    state: { name: 'conflict', open: ciConflict },
  },
  { key: 'ci-new', path: '/cmdb/new', app: 'console' },
  { key: 'admin-cmdb', path: '/admin/cmdb', app: 'console' },
  // WP-053 S2 (lane B; lane C's condition 14): the CI's Map tab as it is, the map with a
  // restricted placeholder and keyboard focus on a node, its node menu, the business views list,
  // one business view, the Versions tab and a comparison.
  { key: 'ci-map', path: (r) => (r.ci ? `/cmdb/${r.ci}?tab=map` : undefined), app: 'console' },
  {
    key: 'ci-map-focus',
    path: (r) => (r.ci ? `/cmdb/${r.ci}?tab=map` : undefined),
    app: 'console',
    state: { name: 'keyboard', open: ciMapFocus(false) },
  },
  {
    key: 'ci-map-menu',
    path: (r) => (r.ci ? `/cmdb/${r.ci}?tab=map` : undefined),
    app: 'console',
    state: { name: 'menu', open: ciMapFocus(true) },
  },
  { key: 'cmdb-views', path: '/cmdb/views', app: 'console' },
  {
    key: 'cmdb-view',
    path: (r) => (r.businessView ? `/cmdb/views/${r.businessView}` : undefined),
    app: 'console',
  },
  {
    key: 'ci-versions',
    path: (r) => (r.ci ? `/cmdb/${r.ci}?tab=versions` : undefined),
    app: 'console',
  },
  // 0175 part 2 (lane B): one CI type's custom fields, its own and those it inherits.
  {
    key: 'cmdb-type-fields',
    path: (r) => (r.ciType ? `/admin/cmdb/types/${r.ciType}/fields` : undefined),
    app: 'console',
    state: { name: 'inherited', open: ciTypeFields },
  },
  // 0175 part 2: changing a CI's type drops a field's value (danger, the field named), or is
  // blocked by a field access rule.
  {
    key: 'ci-change-type',
    path: (r) => (r.ci ? `/cmdb/${r.ci}` : undefined),
    app: 'console',
    state: { name: 'drops', open: ciChangeType(false) },
  },
  {
    key: 'ci-change-type-blocked',
    path: (r) => (r.ci ? `/cmdb/${r.ci}` : undefined),
    app: 'console',
    state: { name: 'blocked', open: ciChangeType(true) },
  },
  {
    key: 'ci-versions-compare',
    path: (r) => (r.ci ? `/cmdb/${r.ci}?tab=versions` : undefined),
    app: 'console',
    state: { name: 'compare', open: ciCompare },
  },
  // WP-053 S4a (lane B, #574; lane C's matrix conditions): sync rules in Admin › CMDB, the list,
  // the editor with its preview drawer, and a run's drawer with a restricted item, a kept field,
  // a skipped target, and totals hidden from a narrowed reader. A fresh stack has no rules, so the
  // sync endpoints are answered here; everything else is the stack's own.
  {
    key: 'cmdb-sync-rules',
    path: '/admin/cmdb/sync-rules',
    app: 'console',
    state: syncState('listed'),
  },
  {
    key: 'cmdb-sync-rule',
    path: `/admin/cmdb/sync-rules/${SYNC_RULE}`,
    app: 'console',
    state: syncState('editor'),
  },
  {
    key: 'cmdb-sync-rule-preview',
    path: `/admin/cmdb/sync-rules/${SYNC_RULE}`,
    app: 'console',
    state: syncState('preview'),
  },
  {
    key: 'cmdb-sync-run',
    path: `/admin/cmdb/sync-rules/${SYNC_RULE}`,
    app: 'console',
    state: syncState('run'),
  },
  {
    key: 'cmdb-sync-run-hidden',
    path: `/admin/cmdb/sync-rules/${SYNC_RULE}`,
    app: 'console',
    state: syncState('totals-hidden'),
  },
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
  // ADR-052 erasure screens (lane C's condition 8), on the mocked erasure API only.
  {
    key: 'erasures',
    path: '/admin/erasures',
    app: 'console',
    sideOnly: true,
    state: erasureState('mocked', 'erasures-table'),
  },
  {
    key: 'erasure',
    path: ERASURE_PATH,
    app: 'console',
    sideOnly: true,
    state: erasureState('summary', 'erasure-page'),
  },
  {
    key: 'erasure-mentions',
    path: ERASURE_PATH,
    app: 'console',
    sideOnly: true,
    state: erasureState('passage', 'erasure-page', async (page) => {
      await tab('mentions')(page);
      await click(`erasure-passage-${FAKE.mention}`)(page);
      await page.getByTestId('erasure-passage-text').waitFor({ timeout: STATE_TIMEOUT });
    }),
  },
  {
    key: 'erasure-history',
    path: ERASURE_PATH,
    app: 'console',
    sideOnly: true,
    state: erasureState('history', 'erasure-page', tab('history')),
  },
  {
    key: 'erasure-approve',
    path: ERASURE_PATH,
    app: 'console',
    sideOnly: true,
    state: erasureState('dialog', 'erasure-page', click('erasure-approve')),
  },
  {
    key: 'person-privacy',
    path: '/admin/users',
    app: 'console',
    sideOnly: true,
    state: { name: 'privacy', open: requestDrawer },
  },
  {
    // Lane C's condition 6: the hold section with a hold placed, then lifting it (the
    // warning and the reason). The lift is answered by the mock and never sent on.
    key: 'person-legal-hold',
    path: '/admin/users',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'lift',
      open: async (page: Page) => {
        // The hold manager's view (lane C): the hold as placed with its reason, then lifting it.
        await asHoldManager(page);
        try {
          await privacyTab(page, true);
          await page.getByTestId('legal-hold-details').first().waitFor({ timeout: STATE_TIMEOUT });
          await click('legal-hold-switch')(page);
          await page.getByTestId('legal-hold-reason').first().waitFor({ timeout: STATE_TIMEOUT });
        } finally {
          await page.unroute(ME);
        }
      },
    },
  },
  {
    // Someone who may ask for erasure but not place holds: held, by whom and since, never why.
    key: 'person-legal-hold',
    path: '/admin/users',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'held',
      open: async (page: Page) => {
        await privacyTab(page, true, false);
        await page.getByTestId('legal-hold-details').first().waitFor({ timeout: STATE_TIMEOUT });
      },
    },
  },
  {
    key: 'erasure-request',
    path: '/admin/users',
    app: 'console',
    sideOnly: true,
    state: {
      name: 'drawer',
      open: async (page: Page) => {
        await requestDrawer(page);
        await click('person-erasure-ask')(page);
        await page.getByTestId('erasure-request').first().waitFor({ timeout: STATE_TIMEOUT });
      },
    },
  },
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
  const ci = (await first('/api/v1/cmdb/cis?limit=1', firstItem)) ?? (await showcaseCi(page));
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
    ci,
    // 0175 part 2: a CI type's Fields page (the built-in server type: every tenant has it).
    ciType: await first(
      '/api/v1/cmdb/ci-types',
      (b) =>
        ((b as { items?: { id: string; api_name: string }[] }).items ?? []).find(
          (x) => x.api_name === 'server',
        )?.id,
    ),
    // WP-053 S2: a business view to open (one on the showcase CI when the stack has none).
    businessView:
      (await first('/api/v1/cmdb/business-views?limit=1', firstItem)) ??
      (await showcaseView(page, ci)),
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
/** A CI for the CMDB shots (WP-053 S1): the stack's showcase has none yet. */
async function showcaseCi(page: Page): Promise<string | undefined> {
  const types = await page.request.get('/api/v1/cmdb/ci-types');
  if (!types.ok()) return undefined;
  const type = ((await types.json()) as { items?: { id: string }[] }).items?.[0]?.id;
  if (type === undefined) return undefined;
  const { csrf } = await me(page);
  const made = await page.request.post('/api/v1/cmdb/cis', {
    data: { type_id: type, name: 'Core switch SW-01', description: 'Floor 2 network core.' },
    headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-CSRF-Token': csrf },
  });
  return made.ok() ? ((await made.json()) as { id: string }).id : undefined;
}

/** A business view on the showcase CI (WP-053 S2): the stack's showcase has none yet. */
async function showcaseView(page: Page, ci: string | undefined): Promise<string | undefined> {
  if (ci === undefined) return undefined;
  const { csrf } = await me(page);
  const made = await page.request.post('/api/v1/cmdb/business-views', {
    data: {
      base_ci_id: ci,
      name: 'Core switch map',
      description: 'What the core switch connects.',
    },
    headers: { 'Idempotency-Key': crypto.randomUUID(), 'X-CSRF-Token': csrf },
  });
  return made.ok() ? ((await made.json()) as { id: string }).id : undefined;
}

/**
 * The map with neighbours answered in the browser (the showcase CI has no relationships yet): two
 * CIs, one end of life, and a CI the viewer may not open, so the shot has every node look. Then
 * keyboard focus on a node (an arrow key moves it, so the focus ring shows), and with `menu`
 * its menu open (Enter).
 */
function ciMapFocus(menu: boolean): (page: Page) => Promise<void> {
  return async (page) => {
    const url = '**/api/v1/cmdb/cis/*/neighbours*';
    const answer = (route: Route) => {
      const base = /\/cis\/([^/]+)\/neighbours/.exec(route.request().url())?.[1] ?? '';
      const node = (id: string, name: string, display: string, eol = false, type = 'server') => ({
        key: id,
        restricted: false,
        depth: id === base ? 0 : 1,
        id,
        display_id: display,
        name,
        type_label_key: `cmdb_ci_type.${type}`,
        type_names: {},
        state_category: eol ? 'end_of_life' : 'active',
        state_label_key: eol ? 'cmdb_ci_state.retired' : 'cmdb_ci_state.in_use',
        state_names: {},
        version: 1,
        counts: null,
      });
      const a = '0190aaaa-0000-7000-8000-000000000001';
      const b = '0190aaaa-0000-7000-8000-000000000002';
      return route.fulfill({
        json: {
          nodes: [
            // The showcase CI's own type, so the shot matches its header.
            node(base, 'Core switch SW-01', 'CI-1', false, 'application'),
            node(a, 'Server SRV-01', 'CI-2'),
            node(b, 'Old server SRV-00', 'CI-3', true),
            { key: 'r1', restricted: true, depth: 1 },
          ],
          edges: [
            // Links between CIs the person sees carry their IDs (the menu offers Remove on them);
            // only the restricted node's link has none.
            {
              id: '01a1f000-0000-7000-8000-0000000000e1',
              type_id: 'x',
              from_key: base,
              to_key: a,
              version: 1,
            },
            {
              id: '01a1f000-0000-7000-8000-0000000000e2',
              type_id: 'x',
              from_key: base,
              to_key: b,
              version: 1,
            },
            { id: null, type_id: 'x', from_key: 'r1', to_key: base, version: null },
          ],
          truncated: false,
          node_max: 500,
          counts_available: false,
        },
      });
    };
    await page.route(url, answer);
    try {
      await page.reload();
      const node = page.locator('.react-flow__node').first();
      await node.waitFor({ timeout: STATE_TIMEOUT });
      await node.focus();
      await page.keyboard.press('ArrowDown');
      if (menu) {
        await page.keyboard.press('Enter');
        await page.getByTestId('ci-map-menu').waitFor({ timeout: STATE_TIMEOUT });
      }
    } finally {
      await page.unroute(url, answer);
    }
  };
}

/** A CI custom-field definition as the API answers it, for mocked matrix states (0175 part 2). */
const ciField = (key: string, en: string, ar: string, extra: Record<string, unknown> = {}) => ({
  id: key, // callers set a UUID per row
  entity: 'ci',
  key,
  field_type: 'text',
  labels: { en, ar },
  help: null,
  choices: [],
  display: 'list',
  default: null,
  validation: {
    required: false,
    min: null,
    max: null,
    min_length: null,
    max_length: null,
    pattern: null,
  },
  currency: null,
  sort_order: 0,
  retired: false,
  removed: false,
  in_use: true,
  index_state: 'none',
  index_error: null,
  sensitive: false,
  seal_state: 'plain',
  scope_type_id: null,
  inherited: false,
  version: 1,
  ...extra,
});

/**
 * A CI type's Fields page with every kind of row (0175 part 2), answered in the browser: a field
 * of every CI type, one from the parent type (read-only, "From Hardware"), and two of its own,
 * one retired. The stack's real fields come back after the shot.
 */
async function ciTypeFields(page: Page): Promise<void> {
  const url = '**/api/v1/custom-fields*';
  const types = (await (await page.request.get('/api/v1/cmdb/ci-types')).json()) as {
    items: { id: string; api_name: string }[];
  };
  const hardware = types.items.find((x) => x.api_name === 'hardware')?.id ?? null;
  const server = types.items.find((x) => x.api_name === 'server')?.id ?? null;
  const field = ciField;
  const rows = [
    field('asset_owner_note', 'Owner note', 'ملاحظة المالك', { inherited: true }),
    field('rack_position', 'Rack position', 'موضع الحامل', {
      scope_type_id: hardware,
      inherited: true,
    }),
    field('os_version', 'Operating system', 'نظام التشغيل', { scope_type_id: server }),
    field('cpu_cores', 'CPU cores', 'أنوية المعالج', {
      scope_type_id: server,
      field_type: 'integer',
    }),
    field('legacy_tag', 'Legacy tag', 'وسم قديم', { scope_type_id: server, retired: true }),
  ].map((row, index) => ({ ...row, id: `0190cccc-0000-7000-8000-00000000000${String(index)}` }));
  const answer = (route: Route) =>
    route.request().method() === 'GET' ? route.fulfill({ json: rows }) : route.continue();
  await page.route(url, answer);
  try {
    await page.reload();
    await page.getByTestId('cf-inherited-link-rack_position').waitFor({ timeout: STATE_TIMEOUT });
  } finally {
    await page.unroute(url, answer);
  }
}

/** Two versions compared, answered in the browser (the showcase CI has one version). */
async function ciCompare(page: Page): Promise<void> {
  const at = new Date(Date.now() - 3600_000).toISOString();
  const versions = '**/api/v1/cmdb/cis/*/versions*';
  const compare = '**/api/v1/cmdb/cis/*/compare*';
  const siteSeen = '0190dddd-0000-7000-8000-000000000001';
  const siteHidden = '0190dddd-0000-7000-8000-000000000002';
  const names = {
    [siteSeen]: { label: 'Islamabad HQ', restricted: false, gone: false },
    [siteHidden]: { label: null, restricted: true, gone: false },
  };
  const listed = (route: Route) =>
    route.fulfill({
      json: {
        items: [
          {
            version: 2,
            saved_at: new Date().toISOString(),
            saved_by: null,
            saved_by_name: 'Sara Khan',
          },
          { version: 1, saved_at: at, saved_by: null, saved_by_name: 'Sara Khan' },
        ],
        next_cursor: null,
      },
    });
  const compared = (route: Route) => {
    const empty = {
      saved_at: at,
      saved_by: null,
      saved_by_name: null,
      fields: {},
      relationships: [],
    };
    return route.fulfill({
      json: {
        from_version: { ...empty, version: 1, masked_fields: ['custom.licence_key'], names },
        to_version: { ...empty, version: 2, masked_fields: ['custom.licence_key'], names },
        attributes: [
          { field: 'name', kind: 'changed', old: 'Core switch', new: 'Core switch SW-01' },
          {
            field: 'description',
            kind: 'changed',
            old: 'Floor 2 network core.',
            new: 'Floor 2 network core. '.repeat(12),
          },
          { field: 'criticality', kind: 'added', old: null, new: 'high' },
          // A custom field by its label (0175 part 2).
          { field: 'custom.os_version', kind: 'changed', old: 'Ubuntu 22.04', new: 'Ubuntu 24.04' },
          // References by the server's names (CMDB polish): one named, one the reader may not see.
          { field: 'site_id', kind: 'changed', old: siteSeen, new: siteHidden },
        ],
        relationships_added: [
          { id: null, type_id: 'x', direction: 'forward', ci: { key: 'r1', restricted: true } },
        ],
        relationships_removed: [],
      },
    });
  };
  const fields = '**/api/v1/custom-fields*';
  const defined = (route: Route) =>
    route.request().method() === 'GET'
      ? route.fulfill({
          json: [
            ciField('os_version', 'Operating system', 'نظام التشغيل', {
              id: '0190cccc-0000-7000-8000-0000000000a1',
            }),
            ciField('licence_key', 'Licence key', 'مفتاح الترخيص', {
              id: '0190cccc-0000-7000-8000-0000000000a2',
            }),
          ],
        })
      : route.continue();
  await page.route(versions, listed);
  await page.route(compare, compared);
  await page.route(fields, defined);
  try {
    await page.reload();
    const pick = async (testId: string, nth: number) => {
      await page.getByTestId(testId).first().click({ timeout: STATE_TIMEOUT });
      const dropdown = page.locator('.ant-select-dropdown:visible');
      await dropdown.locator('.ant-select-item-option').nth(nth).click({ timeout: STATE_TIMEOUT });
      // Wait until it has closed: a second pick during the first one's fade-out lands in the old
      // dropdown, leaving Compare disabled (run 44377613773 timed out on that click).
      await dropdown.waitFor({ state: 'hidden', timeout: STATE_TIMEOUT });
    };
    await pick('ci-versions-from', 1);
    await pick('ci-versions-to', 0);
    await page.getByTestId('ci-versions-compare').first().click({ timeout: STATE_TIMEOUT });
    await page.getByTestId('ci-versions-comparison').waitFor({ timeout: STATE_TIMEOUT });
  } finally {
    await page.unroute(versions, listed);
    await page.unroute(compare, compared);
    await page.unroute(fields, defined);
  }
}

type SyncStateName = 'listed' | 'editor' | 'preview' | 'run' | 'totals-hidden';

/**
 * A sync rules screen with the sync endpoints answered in the browser (lane C's conditions):
 * one route per endpoint, only the method the screen calls, anything else passed on. The rule
 * targets the stack's own first CI type, so its name renders through the stack's labels.
 */
function syncState(name: SyncStateName): NonNullable<Screen['state']> {
  const routes: [RegExp, (route: Route) => Promise<void>][] = [];
  const only =
    (method: string, json: () => unknown, headers?: Record<string, string>) => (route: Route) =>
      route.request().method() === method
        ? route.fulfill({ json: json(), headers })
        : route.continue();
  return {
    name,
    open: async (page) => {
      const types = await page.request.get('/api/v1/cmdb/ci-types');
      const typeId =
        ((await types.json()) as { items?: { id: string }[] }).items?.[0]?.id ??
        '01936f2a-5b1c-7000-8000-00000000c509';
      const hidden = name === 'totals-hidden';
      const rule = {
        id: SYNC_RULE,
        name: 'Laptops become workstations',
        source_kind: 'assets',
        filter: null,
        target_type_id: typeId,
        target_state_id: null,
        field_map: { name: 'name', description: 'location', 'custom.retired_rack': 'tag' },
        enabled: true,
        updated_at: '2026-11-21T09:00:00Z',
        version: 3,
      };
      const run = {
        id: SYNC_RUN,
        rule_id: SYNC_RULE,
        trigger: 'schedule',
        status: 'succeeded',
        incremental: false,
        started_at: '2026-11-21T09:00:00Z',
        ended_at: '2026-11-21T09:00:05Z',
        created_count: hidden ? null : 12,
        updated_count: hidden ? null : 3,
        kept_count: hidden ? null : 1,
        unchanged_count: hidden ? null : 24,
        failed_count: hidden ? null : 1,
        failure: null,
        // A CI field that stopped being plain since the rule was saved (lane C (a)).
        skipped_targets: ['retired_rack'],
        created_at: '2026-11-21T09:00:00Z',
        version: 3,
      };
      const items = [
        // A CI and an asset the reader may not see: "Not visible to you", no ID or name.
        {
          outcome: 'updated',
          asset_id: null,
          asset_label: null,
          asset_restricted: true,
          ci_id: null,
          ci_label: null,
          ci_restricted: true,
          kept: [],
          code: null,
        },
        // A value a stronger source holds (a hand edit), kept.
        {
          outcome: 'kept',
          asset_id: SYNC_ASSET,
          asset_label: 'SX-LAP-001',
          asset_restricted: false,
          ci_id: null,
          ci_label: 'Finance laptop',
          ci_restricted: false,
          kept: ['description'],
          code: null,
        },
        // A refused save, with its labelled reason.
        {
          outcome: 'failed',
          asset_id: SYNC_ASSET,
          asset_label: 'SX-LAP-002',
          asset_restricted: false,
          ci_id: null,
          ci_label: null,
          ci_restricted: false,
          kept: [],
          code: 'cmdb_sync_name_required',
        },
      ];
      const preview = {
        total: 40,
        complete: true,
        counts: { created: 36, updated: 3, kept: 1, unchanged: 0, failed: 0 },
        items: [
          {
            asset_id: SYNC_ASSET,
            asset_tag: 'SX-LAP-001',
            asset_name: 'Finance laptop',
            ci_id: null,
            outcome: 'created',
            changes: ['name', 'description'],
            kept: [],
          },
        ],
      };
      routes.push(
        [/\/api\/v1\/cmdb\/sync-rules(\?.*)?$/u, only('GET', () => ({ items: [rule] }))],
        [
          new RegExp(`/api/v1/cmdb/sync-rules/${SYNC_RULE}(\\?.*)?$`, 'u'),
          only('GET', () => rule, { ETag: '"3"' }),
        ],
        [
          new RegExp(`/api/v1/cmdb/sync-rules/${SYNC_RULE}/runs(\\?.*)?$`, 'u'),
          only('GET', () => ({ items: [run] })),
        ],
        [
          new RegExp(`/api/v1/cmdb/sync-runs/${SYNC_RUN}(\\?.*)?$`, 'u'),
          only('GET', () => ({ ...run, items })),
        ],
        [/\/api\/v1\/cmdb\/sync-rules\/preview$/u, only('POST', () => preview)],
      );
      for (const [url, answer] of routes) await page.route(url, answer);
      await page.reload();
      if (name === 'listed') {
        await page.getByTestId(`cmdb-sync-link-${SYNC_RULE}`).waitFor({ timeout: STATE_TIMEOUT });
        return;
      }
      await page.getByTestId('cmdb-sync-name').waitFor({ timeout: STATE_TIMEOUT });
      if (name === 'preview') {
        await page.getByTestId('cmdb-sync-preview').click({ timeout: STATE_TIMEOUT });
        await page.getByTestId('cmdb-sync-preview-body').waitFor({ timeout: STATE_TIMEOUT });
      } else if (name === 'run' || name === 'totals-hidden') {
        await page.getByTestId(`cmdb-sync-run-${SYNC_RUN}`).click({ timeout: STATE_TIMEOUT });
        await page.getByTestId('cmdb-sync-run-body').waitFor({ timeout: STATE_TIMEOUT });
        await page
          .getByTestId(hidden ? 'cmdb-sync-totals-hidden' : 'cmdb-sync-skipped-targets')
          .waitFor({ timeout: STATE_TIMEOUT });
      }
    },
    close: async (page) => {
      for (const [url, answer] of routes.splice(0)) await page.unroute(url, answer);
    },
  };
}

/**
 * The CI's change-type dialog with a mocked preview (0175 part 2): `drops` names the field whose
 * value would go and the button turns danger; `blocked` says the person may not change the type.
 */
function ciChangeType(blocked: boolean): (page: Page) => Promise<void> {
  return async (page) => {
    const url = '**/api/v1/cmdb/cis/*/change-type-preview*';
    const answer = (route: Route) =>
      route.fulfill({
        json: {
          dropped: [{ key: 'os_version', labels: { en: 'Operating system', ar: 'نظام التشغيل' } }],
          blocked,
        },
      });
    await page.route(url, answer);
    try {
      await page.reload();
      await page.getByTestId('ci-actions-more').click({ timeout: STATE_TIMEOUT });
      await page.getByTestId('ci-change-type').click({ timeout: STATE_TIMEOUT });
      // The dialog has finished zooming in before the tree opens.
      await page
        .locator('.ant-modal-wrap .ant-zoom-enter, .ant-modal-wrap .ant-zoom-appear')
        .waitFor({ state: 'detached', timeout: STATE_TIMEOUT });
      await page.getByTestId('ci-new-type').click({ timeout: STATE_TIMEOUT });
      const tree = page.locator('.ant-select-dropdown:visible');
      await tree
        .locator('.ant-select-tree-node-content-wrapper')
        .nth(1)
        .click({ timeout: STATE_TIMEOUT });
      // The shot and axe wait for the tree to close: a fading dropdown fails contrast (run
      // 44407478834) and hides the dialog.
      await tree.waitFor({ state: 'hidden', timeout: STATE_TIMEOUT });
      await page
        .getByTestId(blocked ? 'ci-change-type-blocked' : 'ci-change-type-drops')
        .waitFor({ timeout: STATE_TIMEOUT });
    } finally {
      await page.unroute(url, answer);
    }
  };
}

/** The CI record's edit, with its save beaten by someone else's (a 409 answered here). */
async function ciConflict(page: Page): Promise<void> {
  const url = '**/api/v1/cmdb/cis/*';
  const answer = (route: Route) =>
    route.request().method() === 'PATCH'
      ? route.fulfill({
          status: 409,
          contentType: 'application/problem+json',
          json: {
            type: 'about:blank',
            title: 'Conflict',
            status: 409,
            code: 'version_conflict',
            params: { expected_version: 1, current_version: 2 },
          },
        })
      : route.continue();
  await page.route(url, answer);
  const logged: string[] = [];
  const listen = (message: ConsoleMessage) => {
    if (message.type() === 'error' || message.type() === 'warning') logged.push(message.text());
  };
  page.on('console', listen);
  try {
    await page.getByTestId('ci-edit').first().click({ timeout: STATE_TIMEOUT });
    await page.getByTestId('ci-name').first().fill('Core switch SW-01 (floor 2)');
    const patched = page
      .waitForResponse(
        (r) => r.request().method() === 'PATCH' && r.url().includes('/api/v1/cmdb/cis/'),
        { timeout: STATE_TIMEOUT },
      )
      .catch(() => null);
    await page.getByTestId('ci-save').first().click({ timeout: STATE_TIMEOUT });
    const answered = await patched;
    if (answered === null) {
      // Say why in the matrix index rather than a bare timeout (#524 run 44069892680).
      const problems = await page.locator('.ant-form-item-explain-error').allInnerTexts();
      throw new Error(`ci-conflict: no PATCH was sent; form errors: ${problems.join(' | ')}`);
    }
    // The ConflictDialog's own button: a bare `.ant-modal`/dialog `.first()` can be a hidden one
    // already in the page, which never becomes visible (#524 run 44077613745).
    const shown = await page
      .getByTestId('conflict-keep-mine')
      .waitFor({ timeout: STATE_TIMEOUT })
      .then(() => true)
      .catch(() => false);
    if (!shown) {
      // What the page did instead (#524 run 44102520175): the answer, any toast, still editing?
      const toasts = await page.locator('.ant-message, .ant-notification').allInnerTexts();
      const editing = await page.getByTestId('ci-save').count();
      throw new Error(
        `ci-conflict: no dialog; PATCH ${answered.url()} answered ${String(answered.status())};` +
          ` toasts: ${toasts.join(' | ')}; save buttons: ${String(editing)};` +
          ` console: ${logged.join(' | ').slice(0, 600)}`,
      );
    }
  } finally {
    page.off('console', listen);
    await page.unroute(url, answer);
  }
}

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
    // Also said at once: a run cut off by its time limit writes no index, and kept nothing of
    // why its shots failed (#559's run 44725524374).
    console.log(`visual-matrix: ${shot.file}: ${String(shot.error)}`);
  } finally {
    if (screen.state?.close) await screen.state.close(page).catch(() => undefined);
    if (screen.loading) await page.close().catch(() => undefined);
  }
}

test.skip(!RUN, 'the visual matrix runs in its own workflow (VISUAL_MATRIX=1)');

// The second person's context (S3a's unread row), closed once the shard is done (lane C).
test.afterAll(async () => {
  await replier?.context().close();
  replier = undefined;
});

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
