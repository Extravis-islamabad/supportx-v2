import type { Mailbox } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

// A mailbox's settings by the name the editor gives them, for the shared conflict dialog.
const NAMES = {
  display_name: 'mail.field.display_name',
  directory_id: 'mail.field.directory_id',
  client_id: 'mail.field.client_id',
  auth_model: 'mail.field.auth_model',
  credential_kind: 'mail.field.credential_kind',
  credential_expires_at: 'mail.field.credential_expires_at',
  signed_in: 'mail.oauth.sign_in',
  host: 'mail.field.host',
  port: 'mail.field.port',
  security: 'mail.field.security',
  allow_plain: 'mail.field.allow_plain',
  username: 'mail.field.username',
  has_password: 'mail.field.password',
  folder: 'mail.field.folder',
  after_fetch: 'mail.field.after_fetch',
  move_to: 'mail.field.move_to',
  creates: 'mail.field.creates',
  unknown_senders: 'mail.field.unknown_senders',
  allowed_domains: 'mail.field.allowed_domains',
  enabled: 'mail.field.enabled',
} as const;
type Field = keyof typeof NAMES;

/** What an admin changes of a mailbox (not its fetch state), for the conflict dialog. */
export function mailboxView(mailbox: Mailbox | null | undefined): object | undefined {
  if (mailbox == null) return undefined;
  return Object.fromEntries((Object.keys(NAMES) as Field[]).map((f) => [f, mailbox[f]]));
}

/** A mailbox setting in words. */
export function useMailboxFieldName(): (field: string) => string {
  const t = useLabel();
  return (field) => t(field in NAMES ? NAMES[field as Field] : 'nav.admin_mail');
}
