// @supportx/realtime: Centrifugo client, channel hooks and TanStack Query cache patching
// (architecture.md §8.3; WP-011). See docs/architecture/realtime.md.
export {
  ACCESS_CHANGED,
  RETRY_DELAYS_MS,
  FALLBACK_AFTER_MS,
  POLL_INTERVAL_MS,
  RealtimeConnection,
  defaultClientFactory,
  inertClientFactory,
  setDefaultClientFactory,
  type ClientFactory,
} from './connection';
export {
  refreshList,
  refreshRecord,
  useChannel,
  useListChannel,
  useRealtimeStatus,
  useRealtimeUser,
  usePersonalChannel,
  useRecordChannel,
  useTenantChannel,
} from './hooks';
export { REALTIME_KEY, listChannelsKey } from './keys';
export { RealtimeContext, type RealtimeContextValue } from './context';
export { RealtimeProvider, type RealtimeProviderProps } from './RealtimeProvider';
export type { ConnectionStatus, PresenceMember, RealtimeMessage } from './types';
