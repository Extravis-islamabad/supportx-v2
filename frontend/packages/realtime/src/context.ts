import { createContext } from 'react';

import type { RealtimeConnection } from './connection';

export interface RealtimeContextValue {
  connection: RealtimeConnection;
  tenantId: string;
  userId: string;
}

/** The session's realtime connection (null outside a session). */
export const RealtimeContext = createContext<RealtimeContextValue | null>(null);
