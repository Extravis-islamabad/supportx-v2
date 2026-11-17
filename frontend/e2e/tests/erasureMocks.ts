import type { Page, Route } from '@playwright/test';

/**
 * The erasure API answered in the browser (ADR-052): screens and tests only. Every erasure call
 * and every person these screens name is answered here, so nothing is requested, redacted or
 * approved on any server, and no real person's data is shown (the coordinator's condition 2: no
 * erasure on a shared stack until Haider says go). Made-up people only.
 */
export const FAKE = {
  person: '0190e2e0-0000-7000-8000-00000000e701',
  requester: '0190e2e0-0000-7000-8000-00000000e702',
  successor: '0190e2e0-0000-7000-8000-00000000e703',
  erasure: '0190e2e0-0000-7000-8000-00000000e7e1',
  mention: '0190e2e0-0000-7000-8000-00000000e7a1',
} as const;

const PEOPLE: Record<string, { display_name: string; email: string }> = {
  [FAKE.person]: { display_name: 'Noor Hassan', email: 'noor.hassan@example.test' },
  [FAKE.requester]: { display_name: 'Hina Admin', email: 'hina.admin@example.test' },
  [FAKE.successor]: { display_name: 'Samir Khan', email: 'samir.khan@example.test' },
};

function person(id: string) {
  const known = PEOPLE[id] ?? { display_name: 'Someone', email: 'someone@example.test' };
  const [first, ...rest] = known.display_name.split(' ');
  return {
    id,
    ...known,
    first_name: first,
    last_name: rest.join(' '),
    name_custom: false,
    user_type: 'requester',
    status: 'active',
    can_sign_in: true,
    vip: false,
    employee_id: null,
    job_title: null,
    description: null,
    phone: null,
    mobile: null,
    site_id: null,
    department_id: null,
    manager_id: null,
    locale: 'en',
    time_zone: 'UTC',
    request_visibility: null,
    roles: [],
    groups: [],
    sites: [],
    version: 3,
  };
}

export interface ErasureMockState {
  /** False until the screens ask for it (the person then has no open erasure). */
  exists: boolean;
  /** The made-up person is on legal hold. */
  held: boolean;
  state: 'requested' | 'approved';
  reviewed: boolean;
  redacted: boolean;
  version: number;
  /** Calls the screens made, by "METHOD path", for the test to check. */
  calls: string[];
}

function erasureBody(s: ErasureMockState) {
  const now = Date.now();
  return {
    id: FAKE.erasure,
    person_id: FAKE.person,
    state: s.state,
    step: 0,
    steps: 8,
    attempts: 0,
    reason_code: 'subject_request',
    reason_text: 'Asked in writing',
    successor_id: FAKE.successor,
    effective_successor_id: null,
    keep_files: {},
    requested_by: FAKE.requester,
    requested_at: new Date(now - 3_600_000).toISOString(),
    expires_at: new Date(now + 6 * 86_400_000).toISOString(),
    approved_by: s.state === 'approved' ? FAKE.successor : null,
    approved_at: s.state === 'approved' ? new Date(now).toISOString() : null,
    rejected_by: null,
    rejected_at: null,
    started_at: null,
    finished_at: null,
    last_error_code: null,
    report_ready: true,
    report: {
      complete: true,
      building: false,
      by_module: { work_items: { name: 3, email: 1 }, knowledge: { name: 1 }, files: { name: 1 } },
      ports_missing: [],
      attachment_content_searched: false,
      mail_bodies_searched: false,
      short_name_not_searched: false,
      reviewed_at: s.reviewed ? new Date(now - 60_000).toISOString() : null,
      reviewed_by: s.reviewed ? FAKE.successor : null,
    },
    counts: {},
    holdings: { assets_held: 2, asset_loans_open: 1 },
    version: s.version,
  };
}

function mentionBody(s: ErasureMockState) {
  return {
    id: FAKE.mention,
    module_key: 'work_items',
    record_type: 'work_item',
    record_id: '0190e2e0-0000-7000-8000-00000000e7b1',
    field: 'description',
    match_kind: 'name',
    occurrences: 2,
    state: s.redacted ? 'redacted' : 'found',
    redacted_by: null,
    redacted_at: null,
    reaches_record_history: false,
    history_kept: 0,
  };
}

/** Answers the erasure API and the made-up people in this page; returns the mock's state. */
export async function mockErasures(
  page: Page,
  start: Partial<ErasureMockState> = {},
): Promise<ErasureMockState> {
  const s: ErasureMockState = {
    exists: true,
    held: false,
    state: 'requested',
    reviewed: false,
    redacted: false,
    version: 1,
    calls: [],
    ...start,
  };
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({
      status,
      json: body,
      headers: { ETag: `"${String(s.version)}"`, 'Cache-Control': 'no-store' },
    });
  await page.route('**/api/v1/erasures**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api\/v1/u, '');
    s.calls.push(`${request.method()} ${path}`);
    const base = `/erasures/${FAKE.erasure}`;
    if (request.method() === 'GET' && path === '/erasures') {
      return json(route, { items: s.exists ? [erasureBody(s)] : [] });
    }
    if (request.method() === 'GET' && path === base) return json(route, erasureBody(s));
    if (request.method() === 'GET' && path === `${base}/mentions`) {
      return json(route, {
        items: [mentionBody(s)],
        next_cursor: null,
        report: erasureBody(s).report,
      });
    }
    if (request.method() === 'GET' && path === `${base}/mentions/${FAKE.mention}/passage`) {
      return json(route, {
        mention_id: FAKE.mention,
        text: s.redacted
          ? "Laptop handed over by Removed at the person's request."
          : 'Laptop handed over by Noor Hassan on Monday.',
      });
    }
    if (request.method() === 'POST' && path === `${base}/report/reviewed`) {
      s.reviewed = true;
      s.version += 1;
      return json(route, erasureBody(s));
    }
    if (request.method() === 'POST' && path === `${base}/mentions/redact`) {
      s.redacted = true;
      s.version += 1;
      return json(route, { erasure: erasureBody(s), redacted: [mentionBody(s)] });
    }
    if (request.method() === 'POST' && path === `${base}/approve`) {
      s.state = 'approved';
      s.version += 1;
      return json(route, erasureBody(s));
    }
    // Anything else under /erasures is refused here, never sent on.
    return json(route, { code: 'not_found', message_key: 'errors.not_found' }, 404);
  });
  // The made-up person's legal hold and uploads (PersonDrawer › Privacy): read here, and any
  // change to the hold is refused here, never sent on.
  await page.route(`**/api/v1/people/${FAKE.person}/legal-hold**`, async (route) => {
    s.calls.push(`${route.request().method()} /people/${FAKE.person}/legal-hold`);
    if (route.request().method() !== 'GET') {
      return json(route, { code: 'not_found', message_key: 'errors.not_found' }, 404);
    }
    return json(route, {
      user_id: FAKE.person,
      held: s.held,
      held_at: s.held ? new Date(Date.now() - 2 * 86_400_000).toISOString() : null,
      held_by: s.held ? FAKE.requester : null,
      reason: s.held ? 'Employment tribunal, case 42' : null,
      version: 3,
    });
  });
  await page.route(`**/api/v1/people/${FAKE.person}/uploads**`, (route) =>
    json(route, {
      items: [
        {
          id: '0190e2e0-0000-7000-8000-00000000e7d1',
          name: 'signed-contract.pdf',
          size: 48_210,
          content_type: 'application/pdf',
          created_at: new Date(Date.now() - 40 * 86_400_000).toISOString(),
          attached_to: 'work_item',
        },
        {
          id: '0190e2e0-0000-7000-8000-00000000e7d2',
          name: 'desk-photo.jpg',
          size: 120_400,
          content_type: 'image/jpeg',
          created_at: new Date(Date.now() - 12 * 86_400_000).toISOString(),
          attached_to: null,
        },
      ],
      next_cursor: null,
    }),
  );
  await page.route(`**/api/v1/people/${FAKE.person}/erasure`, async (route) => {
    s.calls.push(`${route.request().method()} /people/${FAKE.person}/erasure`);
    s.exists = true;
    return json(route, erasureBody(s), 201);
  });
  // The erasure's History tab: its audit entries, answered here too.
  await page.route(
    (url) => url.pathname.endsWith('/api/v1/audit/entries') && url.search.includes(FAKE.erasure),
    (route) =>
      json(route, {
        items: [
          {
            id: '0190e2e0-0000-7000-8000-00000000e7c1',
            action: 'person.erasure_requested',
            actor_id: FAKE.requester,
            actor_name: 'Hina Admin',
            actor_type: 'person',
            category: 'security',
            change_id: null,
            client: 'console',
            details: {},
            module: 'identity_access',
            object_id: FAKE.erasure,
            object_name: null,
            object_type: 'person_erasure',
            occurred_at: new Date(Date.now() - 3_600_000).toISOString(),
            on_behalf_id: null,
            outcome: 'success',
            reason_code: null,
            request_id: null,
            seq: 1,
          },
        ],
        has_more: false,
        next_cursor: null,
      }),
  );
  await page.route('**/api/v1/users/0190e2e0-0000-7000-8000-00000000e7*', async (route) => {
    const id = new URL(route.request().url()).pathname.split('/').pop() ?? '';
    if (route.request().method() !== 'GET') {
      return json(route, { code: 'not_found', message_key: 'errors.not_found' }, 404);
    }
    return json(route, person(id));
  });
  return s;
}

/** The people list holding only the made-up person (to open their drawer). */
export async function mockPeopleList(page: Page): Promise<void> {
  await page.route(/\/api\/v1\/users(\?.*)?$/u, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({
          json: {
            items: [person(FAKE.person), person(FAKE.successor)],
            has_more: false,
            next_cursor: null,
            estimated_total: 2,
          },
        })
      : route.continue(),
  );
}
