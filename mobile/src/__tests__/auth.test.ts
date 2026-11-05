import { APP_RETURN, base64Url, loginUrl, readReturn } from '../auth';

describe('mobile sign-in helpers (ADR-039)', () => {
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
  });

  it('reads the code or the error the browser comes back with', () => {
    expect(readReturn(`${APP_RETURN}?handoff=abc`)).toEqual({ handoff: 'abc', error: undefined });
    expect(readReturn(`${APP_RETURN}?auth_error=no_organization`)).toEqual({
      handoff: undefined,
      error: 'no_organization',
    });
    expect(readReturn(APP_RETURN)).toEqual({ handoff: undefined, error: undefined });
  });
});
