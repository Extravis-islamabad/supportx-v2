import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { setApiOrigin } from '@supportx/api-client';

import { AppProviders } from '../AppProviders';
import { IncidentRequestDetail } from '../req/RequestDetail';
import { ReportProblem } from '../req/RequesterScreens';
import { useSettings } from '../settings';
import { Approvals } from '../tech/Approvals';
import { IncidentScreen } from '../tech/IncidentScreen';
import { Queue } from '../tech/Queue';
import { TechHome } from '../tech/TechHome';
import { Toast } from '../ui';

let mockParams: Record<string, string> = {};
jest.mock('expo-router', () => ({
  router: {
    push: jest.fn(),
    replace: jest.fn(),
    back: jest.fn(),
    canGoBack: jest.fn(() => true),
    setParams: jest.fn(),
  },
  useLocalSearchParams: () => mockParams,
}));
const mockRouter = jest.requireMock<{ router: Record<string, jest.Mock> }>('expo-router').router;

const SERVER = 'https://support.example.com';
const ME = 'u-me';
const SOON = new Date(Date.now() + 12 * 60_000).toISOString();
const LATE = new Date(Date.now() - 25 * 60_000).toISOString();

interface Call {
  path: string;
  method: string;
  body: unknown;
  headers: Headers;
}

function stubApi(routes: Record<string, unknown>) {
  const calls: Call[] = [];
  const fake: typeof fetch = async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = request.method === 'GET' ? '' : await request.text();
    const call = {
      path,
      method: request.method,
      body: text ? (JSON.parse(text) as unknown) : undefined,
      headers: request.headers,
    };
    calls.push(call);
    const route = routes[`${request.method} ${path}`];
    if (route === undefined) {
      return new Response(JSON.stringify({ code: 'not_found', status: 404 }), { status: 404 });
    }
    const body = typeof route === 'function' ? (route as (c: Call) => unknown)(call) : route;
    return new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });
  };
  globalThis.fetch = jest.fn(fake) as typeof fetch;
  return calls;
}

const meBody = {
  csrf_token: 'csrf-1',
  permissions: [],
  tenant: { id: 't-1', name: 'Demo Company' },
  tenants: [{ id: 't-1', name: 'Demo Company' }],
  user: {
    id: ME,
    email: 'tariq@demo.test',
    display_name: 'Tariq Mahmood',
    locale: 'en',
    user_type: 'technician',
    roles: ['technician'],
  },
};

function incident(overrides: Record<string, unknown> = {}) {
  return {
    id: 'i-1',
    display_id: 'INC-1042',
    subject: 'VPN disconnects every 10 minutes',
    priority: 'p2',
    status: 'assigned',
    status_category: 'open',
    channel: 'portal',
    technician_id: ME,
    requester_id: 'u-req',
    sla_policy_id: 'sla-1',
    resolution_due_at: SOON,
    resolution_sla_state: 'warning',
    version: 3,
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

const page = (items: unknown[]) => ({
  items,
  has_more: false,
  next_cursor: null,
  estimated_total: items.length,
  people: {
    'u-req': { display_name: 'Ayesha Khan', email: 'a@demo.test' },
    'u-sara': { display_name: 'Sara Malik', email: 's@demo.test' },
  },
});

let client: QueryClient;

beforeEach(async () => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  mockParams = {};
  jest.clearAllMocks();
  useSettings.setState({ server: SERVER, locale: 'en', loaded: true });
  setApiOrigin(SERVER);
  await useSettings.getState().setSession('session-1');
});

afterEach(() => {
  client.clear();
});

function wrap(node: React.ReactNode) {
  return (
    <AppProviders client={client}>
      {node}
      <Toast />
    </AppProviders>
  );
}

describe('technician home', () => {
  it('shows the KPIs, the MonetX alert and what needs attention', async () => {
    stubApi({
      'GET /api/v1/auth/me': meBody,
      'GET /api/v1/automation/availability': [
        { user_id: ME, state: 'available', changed_at: null, changed_by: null },
      ],
      'GET /api/v1/incidents/views': [
        { view: 'my_open', count: 3, capped: false },
        { view: 'my_overdue', count: 1, capped: false },
        { view: 'my_due_today', count: 2, capped: false },
        { view: 'unassigned', count: 4, capped: false },
      ],
      'GET /api/v1/incidents': page([
        incident(),
        incident({
          id: 'i-2',
          display_id: 'INC-1037',
          subject: 'Outlook not syncing',
          resolution_due_at: LATE,
          resolution_sla_state: 'breached',
        }),
        incident({
          id: 'i-3',
          display_id: 'INC-1039',
          subject: 'Core switch SW-ISB-02 unreachable',
          channel: 'monetx',
          technician_id: null,
        }),
      ]),
    });
    await render(wrap(<TechHome />));
    await waitFor(() => {
      expect(screen.getByTestId('kpi-my_overdue')).toHaveTextContent(/1/);
    });
    expect(screen.getByTestId('kpi-unassigned')).toHaveTextContent(/4/);
    expect(screen.getByTestId('monetx-alert')).toHaveTextContent(
      /Core switch SW-ISB-02 unreachable/,
    );
    expect(screen.getByTestId('incident-INC-1037')).toHaveTextContent(/Overdue by/);
    await fireEvent.press(screen.getByTestId('kpi-my_overdue'));
    expect(mockRouter.replace).toHaveBeenCalledWith('/t/queue?view=my_overdue');
  });
});

describe('queue', () => {
  it('lists the chosen view with counts and an SLA on every row', async () => {
    mockParams = { view: 'unassigned' };
    const calls = stubApi({
      'GET /api/v1/auth/me': meBody,
      'GET /api/v1/incidents/views': [{ view: 'unassigned', count: 1, capped: false }],
      'GET /api/v1/incidents': page([
        incident({ technician_id: null, display_id: 'INC-1035', subject: 'Wi-Fi drops in 4B' }),
      ]),
    });
    await render(wrap(<Queue />));
    await waitFor(() => {
      expect(screen.getByTestId('incident-INC-1035')).toHaveTextContent(/Wi-Fi drops in 4B/);
    });
    expect(screen.getByTestId('incident-INC-1035')).toHaveTextContent(/Due in/);
    expect(screen.getByTestId('filter-unassigned')).toHaveTextContent(/· 1/);
    const list = calls.find((c) => c.path === '/api/v1/incidents');
    expect(list).toBeDefined();
    await fireEvent.press(screen.getByTestId('filter-my_open'));
    expect(mockRouter.setParams).toHaveBeenCalledWith({ view: 'my_open' });
  });
});

describe('incident', () => {
  const detail = (overrides: Record<string, unknown> = {}) => ({
    ...incident(),
    people: { 'u-req': { display_name: 'Ayesha Khan', email: 'a@demo.test' } },
    actions: [
      { action: 'start_work', allowed: true, reason: null, missing: [], reason_mode: 'none' },
      { action: 'resolve', allowed: true, reason: null, missing: [], reason_mode: 'none' },
    ],
    ...overrides,
  });

  it('keeps the actions in order, disables Take with its reason, and asks for a resolution', async () => {
    const calls = stubApi({
      'GET /api/v1/auth/me': meBody,
      'GET /api/v1/incidents/i-1': detail(),
      'GET /api/v1/incidents/i-1/conversation': { items: [], people: {}, truncated: false },
      'POST /api/v1/incidents/i-1/actions/resolve': detail({
        status: 'resolved',
        status_category: 'resolved',
      }),
    });
    await render(wrap(<IncidentScreen id="i-1" />));
    await waitFor(() => {
      expect(screen.getByTestId('incident-assignee')).toHaveTextContent('You');
    });
    expect(screen.getByTestId('action-take')).toBeDisabled();
    expect(screen.getByTestId('action-start_work')).toBeEnabled();

    await fireEvent.press(screen.getByTestId('action-resolve'));
    await fireEvent.press(screen.getByTestId('confirm-resolve'));
    expect(screen.getByText('Write the resolution before resolving.')).toBeOnTheScreen();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);

    await fireEvent.changeText(
      screen.getByTestId('resolution'),
      'Raised the firewall session timeout.',
    );
    await fireEvent.press(screen.getByTestId('confirm-resolve'));
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/resolve'))).toBe(true);
    });
    const resolve = calls.find((c) => c.method === 'POST' && c.path.endsWith('/resolve'));
    expect(resolve?.body).toMatchObject({ resolution: 'Raised the firewall session timeout.' });
    expect(resolve?.headers.get('If-Match')).toBe('"3"');
    expect(resolve?.headers.get('X-CSRF-Token')).toBe('csrf-1'); // from /auth/me
  });

  it('sends a public reply and a private note as different kinds', async () => {
    const calls = stubApi({
      'GET /api/v1/auth/me': meBody,
      'GET /api/v1/incidents/i-1': detail(),
      'GET /api/v1/incidents/i-1/conversation': {
        items: [
          {
            id: 'e-1',
            kind: 'reply',
            visibility: 'public',
            body: 'My VPN drops every 10 minutes.',
            created_at: new Date().toISOString(),
            created_by: 'u-req',
            automatic: false,
            version: 1,
          },
        ],
        people: { 'u-req': { display_name: 'Ayesha Khan', email: 'a@demo.test' } },
        truncated: false,
      },
      'POST /api/v1/incidents/i-1/conversation': { entry: {}, record: detail() },
    });
    await render(wrap(<IncidentScreen id="i-1" />));
    await waitFor(() => {
      expect(screen.getByText('My VPN drops every 10 minutes.')).toBeOnTheScreen();
    });
    await fireEvent.changeText(screen.getByTestId('composer'), 'Checking the firewall now.');
    await fireEvent.press(screen.getByTestId('send'));
    await fireEvent.press(screen.getByTestId('mode-note'));
    await fireEvent.changeText(screen.getByTestId('composer'), 'Three users on ISP-2.');
    await fireEvent.press(screen.getByTestId('send'));
    await waitFor(() => {
      expect(calls.filter((c) => c.method === 'POST').length).toBe(2);
    });
    const [reply, note] = calls.filter((c) => c.method === 'POST');
    expect(reply?.body).toMatchObject({ kind: 'reply', visibility: 'public' });
    expect(note?.body).toMatchObject({ kind: 'note', visibility: 'private' });
  });
});

describe('approvals', () => {
  it('rejects only with a reason', async () => {
    const calls = stubApi({
      'GET /api/v1/service-requests/my-approvals': {
        items: [
          {
            approval_id: 'ap-1',
            approval_version: 2,
            record_id: 'sr-1',
            display_id: 'SR-208',
            subject: 'New laptop: ThinkPad T14',
            requester_id: 'u-req',
            on_behalf_of_id: null,
            catalog_item_id: null,
            comments_required: false,
            created_at: new Date().toISOString(),
          },
        ],
        people: { 'u-req': { display_name: 'Ayesha Khan', email: 'a@demo.test' } },
      },
      'POST /api/v1/service-requests/sr-1/approvals/ap-1/decision': {
        id: 'ap-1',
        state: 'rejected',
      },
    });
    await render(wrap(<Approvals />));
    await waitFor(() => {
      expect(screen.getByTestId('approval-SR-208')).toHaveTextContent(/Ayesha Khan/);
    });
    await fireEvent.press(screen.getByTestId('reject-SR-208'));
    await fireEvent.press(screen.getByTestId('confirm-reject'));
    expect(screen.getByText('A reason is required.')).toBeOnTheScreen();
    await fireEvent.changeText(
      screen.getByTestId('reject-reason'),
      'Budget is frozen this quarter.',
    );
    await fireEvent.press(screen.getByTestId('confirm-reject'));
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'POST')).toBe(true);
    });
    const decision = calls.find((c) => c.method === 'POST');
    expect(decision?.body).toMatchObject({
      decision: 'reject',
      comment: 'Budget is frozen this quarter.',
    });
    expect(decision?.headers.get('If-Match')).toBe('"2"');
  });
});

describe('requester', () => {
  it('reports a problem only with a subject, with one idempotency key per form', async () => {
    const calls = stubApi({
      'GET /api/v1/knowledge/suggestions': [],
      'POST /api/v1/portal/incidents': { id: 'p-1', display_id: 'INC-1050' },
    });
    await render(wrap(<ReportProblem />));
    await fireEvent.press(screen.getByTestId('report-send'));
    expect(screen.getByText('Say in a few words what is wrong.')).toBeOnTheScreen();
    await fireEvent.changeText(screen.getByTestId('report-subject'), 'Printer shows a paper jam');
    await fireEvent.press(screen.getByTestId('urgency-high'));
    await fireEvent.press(screen.getByTestId('report-send'));
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'POST')).toBe(true);
    });
    const sent = calls.find((c) => c.method === 'POST');
    expect(sent?.body).toMatchObject({ subject: 'Printer shows a paper jam', urgency: 'high' });
    expect(sent?.headers.get('Idempotency-Key')).toMatch(/^[0-9a-f-]{36}$/);
    expect(mockRouter.push).toHaveBeenCalledWith('/r/requests/incident/p-1');
  });

  it('says it is still broken with the requester’s words, which reopens it', async () => {
    const calls = stubApi({
      'GET /api/v1/portal/incidents/p-1': {
        id: 'p-1',
        display_id: 'INC-1042',
        subject: 'VPN drops',
        portal_status: 'resolved',
        updated_at: new Date().toISOString(),
      },
      'GET /api/v1/portal/incidents/p-1/conversation': { items: [] },
      'POST /api/v1/portal/incidents/p-1/resolution/reject': {
        id: 'p-1',
        portal_status: 'in_progress',
      },
    });
    await render(wrap(<IncidentRequestDetail id="p-1" />));
    await waitFor(() => {
      expect(screen.getByTestId('fixed-no')).toBeOnTheScreen();
    });
    expect(screen.getByTestId('timeline')).toHaveTextContent(/Received/);
    await fireEvent.press(screen.getByTestId('fixed-no'));
    await fireEvent.changeText(screen.getByTestId('broken-why'), 'Still drops at 3 PM.');
    await fireEvent.press(screen.getByTestId('broken-send'));
    await waitFor(() => {
      expect(calls.some((c) => c.method === 'POST' && c.path.endsWith('/resolution/reject'))).toBe(
        true,
      );
    });
  });
});
