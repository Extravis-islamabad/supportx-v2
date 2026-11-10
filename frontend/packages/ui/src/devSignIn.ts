/** Whether this path is the dev-only quick sign-in page (D-151), in the console or the portal. */
export function isDevSignIn(pathname: string): boolean {
  return pathname.replace(/\/$/, '').endsWith('/dev/sign-in');
}
