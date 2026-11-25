/**
 * D-129: holding no role but `requester` (or none) means the portal, never the console. A
 * vendor support account holds no role at all and works in the console: its access is its
 * grant's, checked by the server on every request (WP-057 S4c-3, the BFF's own rule).
 */
export function requesterOnly(user: { roles: string[]; user_type: string }): boolean {
  if (user.user_type === 'vendor_support') return false;
  return user.roles.every((role) => role === 'requester');
}
