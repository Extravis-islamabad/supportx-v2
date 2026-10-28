import type { IdentitySettings, Invitation, SsoProvider } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

// The sign-in settings a person changes, by the name each card gives them (QA WP-029 BUG-05).
// Every card saves into the same settings, so a conflict names a change made on another card too.
const NAMES = {
  console_idle_seconds: 'security.field.console_idle',
  console_absolute_seconds: 'security.field.console_absolute',
  portal_idle_seconds: 'security.field.portal_idle',
  portal_absolute_seconds: 'security.field.portal_absolute',
  create_people_on_sign_in: 'security.people.create',
  invitation_valid_days: 'security.invitations.valid_days',
  mfa_grace_days: 'security.mfa.grace',
  password_min_length: 'security.password.min_length',
  password_upper: 'security.password.upper',
  password_lower: 'security.password.lower',
  password_digits: 'security.password.digits',
  password_special: 'security.password.special',
  password_history: 'security.password.history',
  password_expiry_days: 'security.password.expiry',
  password_breached_check: 'security.password.breached',
} as const;
type Field = keyof typeof NAMES;

/** The settings people change (not the policy's apply state), for the conflict dialog. */
export function editable(settings: IdentitySettings | undefined): object | undefined {
  if (settings === undefined) return undefined;
  return Object.fromEntries((Object.keys(NAMES) as Field[]).map((f) => [f, settings[f]]));
}

/** A sign-in setting's name in words. */
export function useSettingName(): (field: string) => string {
  const t = useLabel();
  return (field) => (field in NAMES ? t(NAMES[field as Field]) : t('nav.admin_security'));
}

const INVITATION_NAMES = {
  status: 'security.invitations.status',
  sent_at: 'security.invitations.sent',
  expires_at: 'security.invitations.expires',
} as const;
type InvitationField = keyof typeof INVITATION_NAMES;

/** What a person sees of an invitation, for the conflict dialog. */
export function invitationView(invitation: Invitation | undefined): object | undefined {
  if (invitation === undefined) return undefined;
  return Object.fromEntries(
    (Object.keys(INVITATION_NAMES) as InvitationField[]).map((f) => [f, invitation[f]]),
  );
}

/** An invitation's field in words. */
export function useInvitationFieldName(): (field: string) => string {
  const t = useLabel();
  return (field) =>
    t(
      field in INVITATION_NAMES
        ? INVITATION_NAMES[field as InvitationField]
        : 'security.invitations.title',
    );
}

// A single sign-on set-up's settings, by the names the editor gives them.
const SSO_NAMES = {
  preset: 'security.sso.preset',
  display_name: 'security.sso.display_name',
  domains: 'security.sso.domains',
  email_redirect: 'security.sso.email_redirect',
  state: 'security.sso.state',
  issuer: 'security.sso.issuer',
  client_id: 'security.sso.client_id',
  scopes: 'security.sso.scopes',
  metadata_url: 'security.sso.metadata_url',
  sso_url: 'security.sso.sso_url',
  certificate: 'security.sso.certificate',
  // Read from the provider's metadata.
  entity_id: 'security.sso.metadata',
  mapping: 'security.sso.mapping',
} as const;
type SsoField = keyof typeof SSO_NAMES;

/** A set-up as the admin sees it (its connection settings beside its name), for the dialog. */
export function ssoView(provider: SsoProvider | null | undefined): object | undefined {
  if (provider == null) return undefined;
  const all: Record<string, unknown> = { ...provider.settings, ...provider };
  return Object.fromEntries((Object.keys(SSO_NAMES) as SsoField[]).map((f) => [f, all[f]]));
}

/** A set-up's setting in words. */
export function useSsoFieldName(): (field: string) => string {
  const t = useLabel();
  return (field) => t(field in SSO_NAMES ? SSO_NAMES[field as SsoField] : 'security.sso.title');
}
