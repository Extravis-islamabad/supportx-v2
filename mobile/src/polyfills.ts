import { randomUUID } from 'expo-crypto';

// @supportx/api-client calls crypto.randomUUID() for request IDs and idempotency keys (§10);
// Hermes has no Web Crypto, so the native generator from expo-crypto stands in for it.
const scope = globalThis as { crypto?: Partial<Crypto> };
if (typeof scope.crypto?.randomUUID !== 'function') {
  const uuid = randomUUID as Crypto['randomUUID'];
  if (scope.crypto === undefined) scope.crypto = { randomUUID: uuid };
  else scope.crypto.randomUUID = uuid;
}
