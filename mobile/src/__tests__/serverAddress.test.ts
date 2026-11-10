import { parseServerAddress } from '../serverAddress';

describe('parseServerAddress', () => {
  it('adds https and keeps only the origin', () => {
    expect(parseServerAddress(' support.example.com/portal ', false)).toEqual({
      ok: true,
      origin: 'https://support.example.com',
    });
    expect(parseServerAddress('https://sx.local:8443/', false)).toEqual({
      ok: true,
      origin: 'https://sx.local:8443',
    });
  });

  it('refuses plain http unless allowed (development builds only)', () => {
    expect(parseServerAddress('http://10.0.2.2:8000', false)).toEqual({
      ok: false,
      problem: 'https_required',
    });
    expect(parseServerAddress('http://10.0.2.2:8000', true)).toEqual({
      ok: true,
      origin: 'http://10.0.2.2:8000',
    });
    expect(parseServerAddress('ftp://support.example.com', true)).toEqual({
      ok: false,
      problem: 'https_required',
    });
  });

  it('refuses empty, malformed and credential-bearing addresses', () => {
    for (const input of ['', '   ', 'https://', 'https://user:pass@support.example.com']) {
      expect(parseServerAddress(input, false)).toEqual({ ok: false, problem: 'invalid' });
    }
  });
});
