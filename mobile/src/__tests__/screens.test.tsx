import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { currentApiOrigin, currentSessionId, setApiOrigin } from '@supportx/api-client';

import { AppProviders } from '../AppProviders';
import type { SignInResult } from '../auth';
import { MeScreen } from '../screens/MeScreen';
import { ServerScreen } from '../screens/ServerScreen';
import { SignInScreen } from '../screens/SignInScreen';
import { appSide } from '../session';
import { useSettings } from '../settings';

const SERVER = 'https://support.example.com';

function stubFetch(answer: (path: string, request: Request) => Response | Promise<Response>) {
  const calls: Request[] = [];
  // api-client always hands fetch a Request (openapi-fetch builds one per call).
  const fake: typeof fetch = (input) => {
    const request = input as Request;
    calls.push(request);
    return Promise.resolve(answer(new URL(request.url).pathname, request));
  };
  globalThis.fetch = jest.fn(fake) as typeof fetch;
  return calls;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const HEALTH = { status: 'ok', version: '2.4.0' };

function me(overrides: { user_type?: string; roles?: string[]; tenants?: number } = {}) {
  const tenants = [
    { id: 't-1', name: 'Demo Company' },
    { id: 't-2', name: 'Other Company' },
  ].slice(0, overrides.tenants ?? 1);
  return {
    csrf_token: 'csrf-1',
    permissions: [],
    tenant: tenants[0],
    tenants,
    user: {
      id: 'u-1',
      email: 'tariq@demo.test',
      display_name: 'Tariq Mahmood',
      locale: 'en',
      user_type: overrides.user_type ?? 'technician',
      roles: overrides.roles ?? ['technician'],
    },
  };
}

let client: QueryClient;

beforeEach(async () => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useSettings.setState({
    server: null,
    session: null,
    sessionEnded: false,
    locale: 'en',
    loaded: true,
  });
  setApiOrigin(null);
  await useSettings.getState().setSession(null);
});

afterEach(() => {
  // Unmounted queries keep garbage-collection and refetch timers otherwise.
  client.clear();
});

async function signedIn() {
  useSettings.setState({ server: SERVER });
  setApiOrigin(SERVER);
  await useSettings.getState().setSession('session-1');
}

describe('ServerScreen', () => {
  it('checks the server, saves it and points the API client at it', async () => {
    const calls = stubFetch(() => json(HEALTH));
    const onConnected = jest.fn();
    await render(
      <AppProviders client={client}>
        <ServerScreen onConnected={onConnected} allowHttp={false} />
      </AppProviders>,
    );
    await fireEvent.changeText(screen.getByTestId('server-address'), 'support.example.com');
    await fireEvent.press(screen.getByTestId('server-connect'));

    await waitFor(() => {
      expect(onConnected).toHaveBeenCalled();
    });
    expect(calls[0]?.url).toBe(`${SERVER}/api/v1/health`);
    expect(calls[0]?.headers.get('X-Request-ID')).toMatch(/^[0-9a-f-]{36}$/);
    expect(useSettings.getState().server).toBe(SERVER);
    expect(currentApiOrigin()).toBe(SERVER);
  });

  it('says why an address is refused, in words', async () => {
    stubFetch(() => {
      throw new TypeError('Network request failed');
    });
    await render(
      <AppProviders client={client}>
        <ServerScreen onConnected={jest.fn()} allowHttp={false} />
      </AppProviders>,
    );
    await fireEvent.changeText(screen.getByTestId('server-address'), 'http://support.example.com');
    await fireEvent.press(screen.getByTestId('server-connect'));
    expect(screen.getByTestId('server-problem')).toHaveTextContent(
      'The address must start with https://.',
    );

    await fireEvent.changeText(screen.getByTestId('server-address'), 'support.example.com');
    await fireEvent.press(screen.getByTestId('server-connect'));
    await waitFor(() => {
      expect(screen.getByTestId('server-problem')).toHaveTextContent(
        'The server could not be reached. Check the address and your connection.',
      );
    });
    expect(useSettings.getState().server).toBeNull();
  });

  it('forgets the session when the server changes', async () => {
    await signedIn();
    stubFetch(() => json(HEALTH));
    await render(
      <AppProviders client={client}>
        <ServerScreen onConnected={jest.fn()} allowHttp={false} />
      </AppProviders>,
    );
    await fireEvent.changeText(screen.getByTestId('server-address'), 'other.example.com');
    await fireEvent.press(screen.getByTestId('server-connect'));
    await waitFor(() => {
      expect(useSettings.getState().server).toBe('https://other.example.com');
    });
    expect(useSettings.getState().session).toBeNull();
    expect(currentSessionId()).toBeNull();
  });
});

describe('SignInScreen', () => {
  it('keeps the session the sign-in hands back', async () => {
    useSettings.setState({ server: SERVER });
    const start = jest.fn((): Promise<SignInResult> =>
      Promise.resolve({ ok: true, sessionId: 'session-9' }),
    );
    const onSignedIn = jest.fn();
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={onSignedIn} onChangeServer={jest.fn()} start={start} />
      </AppProviders>,
    );
    await fireEvent.press(screen.getByTestId('signin'));
    await waitFor(() => {
      expect(onSignedIn).toHaveBeenCalled();
    });
    expect(start).toHaveBeenCalledWith(SERVER);
    expect(useSettings.getState().session).toBe('session-9');
    expect(currentSessionId()).toBe('session-9');
  });

  it('shows a label, never a code, when the sign-in fails or is cancelled', async () => {
    useSettings.setState({ server: SERVER });
    const answers: SignInResult[] = [
      { ok: false, reason: 'error', code: 'no_organization' },
      { ok: false, reason: 'cancelled' },
    ];
    const cancelled: SignInResult = { ok: false, reason: 'cancelled' };
    let call = 0;
    const start = jest.fn((): Promise<SignInResult> =>
      Promise.resolve(answers[call++] ?? cancelled),
    );
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={jest.fn()} onChangeServer={jest.fn()} start={start} />
      </AppProviders>,
    );
    await fireEvent.press(screen.getByTestId('signin'));
    await waitFor(() => {
      expect(screen.getByTestId('signin-problem')).not.toHaveTextContent('no_organization');
    });
    await fireEvent.press(screen.getByTestId('signin'));
    await waitFor(() => {
      expect(screen.getByTestId('signin-problem')).toHaveTextContent('Sign-in was cancelled.');
    });
    expect(useSettings.getState().session).toBeNull();
  });
});

describe('session', () => {
  it('forgets the session when the server says it is over (401)', async () => {
    await signedIn();
    stubFetch(() => json({ code: 'session_expired', status: 401 }, 401));
    await render(
      <AppProviders client={client}>
        <MeScreen onSignedOut={jest.fn()} onChangeServer={jest.fn()} />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(useSettings.getState().session).toBeNull();
    });
    expect(currentSessionId()).toBeNull();
    expect(useSettings.getState().sessionEnded).toBe(true);

    // The sign-in screen says why: signing in again is expected (ADR-044, D-157).
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={jest.fn()} onChangeServer={jest.fn()} start={jest.fn()} />
      </AppProviders>,
    );
    expect(screen.getByTestId('signin-problem')).toHaveTextContent(
      'Your session has ended, so please sign in again.',
      { exact: false },
    );
  });

  it('gives technicians and requesters their own side', () => {
    expect(appSide(me() as never)).toBe('technician');
    expect(appSide(me({ user_type: 'requester', roles: ['requester'] }) as never)).toBe(
      'requester',
    );
  });
});

describe('MeScreen', () => {
  it('shows the person, the server status, and switches to Arabic right to left', async () => {
    await signedIn();
    stubFetch((path) => json(path === '/api/v1/health' ? HEALTH : me()));
    await render(
      <AppProviders client={client}>
        <MeScreen onSignedOut={jest.fn()} onChangeServer={jest.fn()} />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('server-status')).toHaveTextContent(/API online/);
    });
    expect(screen.getByTestId('me-name')).toHaveTextContent(/Tariq Mahmood/);
    expect(screen.getByTestId('server-version')).toHaveTextContent(/2\.4\.0/);
    expect(screen.getByTestId('app-root')).toHaveStyle({ direction: 'ltr' });

    await fireEvent.press(screen.getByTestId('language-ar'));
    await waitFor(() => {
      expect(screen.getByTestId('app-root')).toHaveStyle({ direction: 'rtl' });
    });
    expect(screen.getByText('تسجيل الخروج')).toBeOnTheScreen();
  });

  it('switches organisation with the CSRF token and keeps the new session ID', async () => {
    await signedIn();
    const calls = stubFetch((path) => {
      if (path === '/api/v1/auth/switch-tenant') {
        return new Response(JSON.stringify(me({ tenants: 2 })), {
          headers: { 'Content-Type': 'application/json', 'X-SupportX-Session': 'session-2' },
        });
      }
      return json(path === '/api/v1/health' ? HEALTH : me({ tenants: 2 }));
    });
    await render(
      <AppProviders client={client}>
        <MeScreen onSignedOut={jest.fn()} onChangeServer={jest.fn()} />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('tenant-t-2')).toBeOnTheScreen();
    });
    await fireEvent.press(screen.getByTestId('tenant-t-2'));
    await waitFor(() => {
      expect(useSettings.getState().session).toBe('session-2');
    });
    const switched = calls.find((c) => new URL(c.url).pathname === '/api/v1/auth/switch-tenant');
    expect(switched?.headers.get('X-CSRF-Token')).toBe('csrf-1');
  });

  it('signs out on the server and forgets the session', async () => {
    await signedIn();
    const calls = stubFetch((path) =>
      path === '/api/v1/auth/logout'
        ? new Response(null, { status: 204 })
        : json(path === '/api/v1/health' ? HEALTH : me()),
    );
    const onSignedOut = jest.fn();
    await render(
      <AppProviders client={client}>
        <MeScreen onSignedOut={onSignedOut} onChangeServer={jest.fn()} />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(screen.getByTestId('me-name')).toBeOnTheScreen();
    });
    await fireEvent.press(screen.getByTestId('sign-out'));
    await waitFor(() => {
      expect(onSignedOut).toHaveBeenCalled();
    });
    const logout = calls.find((c) => new URL(c.url).pathname === '/api/v1/auth/logout');
    expect(logout?.headers.get('X-SupportX-Session')).toBe('session-1');
    expect(useSettings.getState().session).toBeNull();
  });
});

describe('dev quick sign-in (D-163)', () => {
  const LOCAL = 'http://localhost:5173';
  const PERSONAS = [
    { code: 'technician', email: 'tech@showcase.test', app: 'console', enrolled: true },
    { code: 'new_starter', email: 'newstarter@showcase.test', app: 'portal', enrolled: false },
  ];

  it('signs a persona in as the app, keeps the session, and sends no Origin', async () => {
    useSettings.setState({ server: LOCAL });
    const calls = stubFetch((path) =>
      path.endsWith('/personas') ? json(PERSONAS) : json({ session_id: 'session-dev' }),
    );
    const onSignedIn = jest.fn();
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={onSignedIn} onChangeServer={jest.fn()} quickSignIn />
      </AppProviders>,
    );
    await fireEvent.press(await screen.findByTestId('dev-quick-sign-in-technician'));
    await waitFor(() => {
      expect(onSignedIn).toHaveBeenCalled();
    });
    const post = calls.find((call) => call.method === 'POST');
    expect(post?.url).toBe(`${LOCAL}/api/v1/auth/dev/mobile/sign-in`);
    expect(post?.headers.get('X-SupportX-Client')).toBe('mobile');
    expect(post?.headers.get('Origin')).toBeNull();
    expect(useSettings.getState().session).toBe('session-dev');
    expect(currentSessionId()).toBe('session-dev');
  });

  it('says where the new starter’s set-up link went, in words', async () => {
    useSettings.setState({ server: LOCAL });
    stubFetch((path) =>
      path.endsWith('/personas')
        ? json(PERSONAS)
        : json({ session_id: null, setup_link_sent_to: 'newstarter@showcase.test' }),
    );
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={jest.fn()} onChangeServer={jest.fn()} quickSignIn />
      </AppProviders>,
    );
    await fireEvent.press(await screen.findByTestId('dev-quick-sign-in-new_starter'));
    expect(await screen.findByTestId('dev-quick-sign-in-sent')).toHaveTextContent(
      /newstarter@showcase\.test/,
    );
    expect(useSettings.getState().session).toBeNull();
  });

  it('shows nothing when the server does not offer it (404)', async () => {
    useSettings.setState({ server: LOCAL });
    stubFetch(() => json({ code: 'not_found' }, 404));
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={jest.fn()} onChangeServer={jest.fn()} quickSignIn />
      </AppProviders>,
    );
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });
    expect(screen.queryByTestId('dev-quick-sign-in')).toBeNull();
  });

  it('never asks in a release build', async () => {
    useSettings.setState({ server: LOCAL });
    const calls = stubFetch(() => json(PERSONAS));
    await render(
      <AppProviders client={client}>
        <SignInScreen onSignedIn={jest.fn()} onChangeServer={jest.fn()} quickSignIn={false} />
      </AppProviders>,
    );
    expect(screen.queryByTestId('dev-quick-sign-in')).toBeNull();
    expect(calls).toHaveLength(0);
  });
});
