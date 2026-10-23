import { devSubscription, fixtures } from './stack';

/**
 * After the suite: remove the scroll-test rows and put Other Company back on its seeded plan in
 * case the read-only test was interrupted before its own restore (same values as db-seed).
 */
export default function globalTeardown(): void {
  fixtures('delete');
  devSubscription('other', '--expires never --status active --technicians 2');
}
