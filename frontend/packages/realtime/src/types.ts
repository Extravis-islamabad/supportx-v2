/**
 * A realtime message: what changed, never the data itself (architecture.md §8.2). Screens patch
 * or refetch through the API. `refresh` (or type `refresh`) means "refetch everything you show".
 */
export interface RealtimeMessage {
  type: string;
  ids: string[];
  fields?: string[];
  version?: number;
  /** User ID of whoever made the change, when a person did. */
  by?: string;
  refresh?: boolean;
}

/**
 * connecting / reconnecting: trying (live updates may lag); connected: live;
 * polling: no connection for a while, screens refresh on a timer; offline: given up (signed out).
 */
export type ConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'polling'
  | 'offline'
  /** Connected, but a channel a screen follows is refused or ended; being retried (QA BUG-02). */
  | 'limited';

/** Someone else following the same record channel (a connection; one person may have several). */
export interface PresenceMember {
  clientId: string;
  userId: string;
  name: string;
}
