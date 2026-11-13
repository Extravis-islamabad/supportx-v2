import { appReturn, base64Url, loginUrl, readReturn, RETURN_PATH } from '../auth';

describe('mobile sign-in helpers (ADR-044)', () => {
  it('writes base64url without padding', () => {
    expect(base64Url('ab+c/d==')).toBe('ab-c_d');
    expect(base64Url('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw+cM=')).toBe(
      'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
    );
  });

  it('starts on the console client with the challenge', () => {
    const url = new URL(loginUrl('https://support.example.com', 'c'.repeat(43)));
    expect(url.origin + url.pathname).toBe('https://support.example.com/api/v1/auth/login');
    expect(url.searchParams.get('app')).toBe('console');
    expect(url.searchParams.get('mobile_challenge')).toBe('c'.repeat(43));
    expect(url.searchParams.has('mobile_platform')).toBe(false);
  });

  it('names the phone for the session list', () => {
    const url = new URL(
      loginUrl('https://support.example.com', 'c'.repeat(43), {
        platform: 'ios',
        version: '1.4.2',
      }),
    );
    expect(url.searchParams.get('mobile_platform')).toBe('ios');
    expect(url.searchParams.get('mobile_version')).toBe('1.4.2');
    const unknown = new URL(
      loginUrl('https://x.test', 'c'.repeat(43), { platform: 'android', version: '' }),
    );
    expect(unknown.searchParams.has('mobile_version')).toBe(false);
  });

  it('returns to a verified https link on the server, never a custom scheme', () => {
    expect(RETURN_PATH).toBe('/mobile/auth');
    expect(appReturn('https://support.example.com')).toBe(
      'https://support.example.com/mobile/auth',
    );
    expect(appReturn('https://support.example.com/')).toBe(
      'https://support.example.com/mobile/auth',
    );
  });

  it('reads the code or the error the browser comes back with', () => {
    const back = appReturn('https://support.example.com');
    expect(readReturn(`${back}?handoff=abc`)).toEqual({ handoff: 'abc', error: undefined });
    expect(readReturn(`${back}?auth_error=no_organization`)).toEqual({
      handoff: undefined,
      error: 'no_organization',
    });
    expect(readReturn(back)).toEqual({ handoff: undefined, error: undefined });
  });
});
