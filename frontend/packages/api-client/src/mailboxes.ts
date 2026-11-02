import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, call } from './client';
import { ApiError } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// WP-024: Admin › Mail (mailboxes.manage). Every write is audited server-side; the password goes
// in and never comes back (`has_password`). The page follows `integrations.mailboxes_changed` on
// the tenant channel and refetches.

const ifMatch = (version: number) => ({ 'If-Match': `"${String(version)}"` });

export type Mailbox = components['schemas']['MailboxOut'];
export type MailboxInput = components['schemas']['MailboxIn'];
export type MailboxChange = components['schemas']['MailboxPatch'];
export type MailboxTest = components['schemas']['ConnectionTestOut'];
export type WaitingMail = components['schemas']['WaitingOut'];
export type ReleasedMail = components['schemas']['ReleasedOut'];

/** Every mailbox with its state and held messages. */
export function useMailboxes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.mailboxes.all,
    queryFn: () => call(api.GET('/api/v1/integrations/mailboxes')),
    enabled,
  });
}

function useMailboxesChanged() {
  const queryClient = useQueryClient();
  return () => void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes.all });
}

/** A stale change: fetch the saved version, so the conflict dialog can compare. */
function onConflict(refresh: () => void) {
  return (error: unknown) => {
    if (error instanceof ApiError && error.isConflict) refresh();
  };
}

/** Add a mailbox; `key` is the Idempotency-Key of this attempt. */
export function useCreateMailbox() {
  const changed = useMailboxesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ body, key }: { body: MailboxInput; key: string }) =>
      call(
        api.POST('/api/v1/integrations/mailboxes', {
          params: { header: { 'Idempotency-Key': key } },
          body,
        }),
      ),
    onSuccess: changed,
  });
}

/** Change a mailbox (leave `password` out to keep the stored one). */
export function useUpdateMailbox() {
  const changed = useMailboxesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, body, version }: { id: string; body: MailboxChange; version: number }) =>
      call(
        api.PATCH('/api/v1/integrations/mailboxes/{mailbox_id}', {
          params: { path: { mailbox_id: id }, header: ifMatch(version) },
          body,
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Stop reading a mailbox (the records it made keep their history). */
export function useRemoveMailbox() {
  const changed = useMailboxesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, version }: { id: string; version: number }) =>
      call(
        api.DELETE('/api/v1/integrations/mailboxes/{mailbox_id}', {
          params: { path: { mailbox_id: id }, header: ifMatch(version) },
        }),
      ),
    onSuccess: changed,
    onError: onConflict(changed),
  });
}

/** Connect and look for new mail, changing nothing; `reason` is a code shown as its label. */
export function useTestMailbox() {
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ id, password }: { id: string; password?: string }) =>
      call(
        api.POST('/api/v1/integrations/mailboxes/{mailbox_id}/test', {
          params: { path: { mailbox_id: id } },
          body: password === undefined ? {} : { password },
        }),
      ),
  });
}

/**
 * Start signing in as the mailbox (Gmail; Microsoft 365 with delegated permission): the address
 * of Microsoft's or Google's sign-in page, valid ten minutes for this admin. The provider sends
 * the browser back to Admin › Mail with `?sign_in=ok` or a reason code.
 */
export function useStartMailboxSignIn() {
  return useMutation({
    mutationFn: ({ id }: { id: string }) =>
      call(
        api.POST('/api/v1/integrations/mailboxes/{mailbox_id}/sign-in', {
          params: { path: { mailbox_id: id } },
        }),
      ),
  });
}

/** The mailbox's review queue: held mail is never invisible (D-109). */
export function useWaitingMail(mailboxId: string | null) {
  return useQuery({
    queryKey: queryKeys.mailboxes.waiting(mailboxId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/integrations/mailboxes/{mailbox_id}/waiting', {
          params: { path: { mailbox_id: mailboxId ?? '' } },
        }),
      ),
    enabled: mailboxId !== null,
  });
}

/** Hand a held message in again; the answer says what it became (or why it waits again). */
export function useReleaseMail() {
  const changed = useMailboxesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ mailboxId, messageId }: { mailboxId: string; messageId: string }) =>
      call(
        api.POST('/api/v1/integrations/mailboxes/{mailbox_id}/waiting/release', {
          params: { path: { mailbox_id: mailboxId } },
          body: { message_id: messageId },
        }),
      ),
    onSettled: changed,
  });
}

/** Discard a waiting message. */
export function useDiscardMail() {
  const changed = useMailboxesChanged();
  return useMutation({
    meta: { silent: true },
    mutationFn: ({ mailboxId, messageId }: { mailboxId: string; messageId: string }) =>
      call(
        api.POST('/api/v1/integrations/mailboxes/{mailbox_id}/waiting/discard', {
          params: { path: { mailbox_id: mailboxId } },
          body: { message_id: messageId },
        }),
      ),
    onSettled: changed,
  });
}
