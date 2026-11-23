import type { useLabel } from './appearance';

/**
 * A sign-in's device code ("chrome:windows", identity_access domain/sign_in.py `device`) in words:
 * "Chrome on Windows". Used by the sign-in log and the signed-in sessions list (REQ-SEC-030).
 */
export function deviceText(
  t: ReturnType<typeof useLabel>,
  device: string | null | undefined,
): string {
  if (device == null) return t('sign_in_device.unknown');
  const [browser = 'other', system = 'other'] = device.split(':');
  return t('sign_in_device.on', {
    browser: t(`sign_in_device.browser.${browser}`),
    system: t(`sign_in_device.system.${system}`),
  });
}
