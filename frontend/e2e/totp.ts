import { createHmac } from 'node:crypto';

/**
 * A time-based one-time code (RFC 6238: SHA-1, 6 digits, 30 seconds), as any authenticator app
 * computes it. Keycloak's set-up page holds the raw secret in its hidden `#totpSecret` field; the
 * key it shows is that secret in base32 (proved on 26.8.1).
 */
export function totp(secret: string, at: number = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const hmac = createHmac('sha1', Buffer.from(secret, 'utf8')).update(counter).digest();
  const offset = (hmac[hmac.length - 1] ?? 0) & 0x0f;
  const code = (hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000;
  return String(code).padStart(6, '0');
}
