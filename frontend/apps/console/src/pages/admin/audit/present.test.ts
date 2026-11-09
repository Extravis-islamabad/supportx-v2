import { describe, expect, it } from 'vitest';

import { actionLabel, deviceLabel } from './present';

// AUD-01: the browser's own string, as people say it. The label is the template itself here.
const t = (key: string, params?: Record<string, unknown>) =>
  key === 'audit.ui.device'
    ? `${String(params?.browser)} on ${String(params?.system)}`
    : key.replace('audit.ui.', '');

describe('deviceLabel', () => {
  it.each([
    [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36 Edg/155.0.0.0',
      'Edge 155 on Windows',
    ],
    [
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.1 Safari/605.1.15',
      'Safari 19 on macOS',
    ],
    [
      'Mozilla/5.0 (iPhone; CPU iPhone OS 19_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.1 Mobile/15E148 Safari/604.1',
      'Safari 19 on iOS',
    ],
    [
      'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0',
      'Firefox 150 on Linux',
    ],
    [
      'Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Mobile Safari/537.36',
      'Chrome 155 on Android',
    ],
    ['curl/8.9.1', 'device_unknown'],
  ])('%s', (agent, expected) => {
    expect(deviceLabel(t, agent)).toBe(expected);
  });
});

describe('actionLabel', () => {
  const plain = (key: string) => key;
  it('names the outcome of an approval decision when the entry records one (QA9-F-03)', () => {
    const entry = { action: 'service_request.approval_decided', details: { outcome: 'rejected' } };
    expect(actionLabel(plain, entry)).toBe(
      'audit.decision.service_request.approval_decided.rejected',
    );
  });
  it('keeps the general label for older entries and unknown outcomes', () => {
    for (const details of [{}, { outcome: 'maybe' }, { outcome: 3 }]) {
      expect(actionLabel(plain, { action: 'service_request.approval_decided', details })).toBe(
        'audit.action.service_request.approval_decided',
      );
    }
  });
});
