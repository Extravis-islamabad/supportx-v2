import { devSubscription, fixtures, keycloakAdmin, tenantAddressCallbacks } from './stack';

/**
 * After the suite: remove the scroll-test rows and the tenant-address callbacks, and put Other
 * Company back on its seeded plan in case the read-only test was interrupted before its own
 * restore (same values as db-seed).
 */
export default async function globalTeardown(): Promise<void> {
  fixtures('delete');
  await tenantAddressCallbacks(await keycloakAdmin(), 'remove');
  devSubscription('other', '--expires never --status active --technicians 2');
}
