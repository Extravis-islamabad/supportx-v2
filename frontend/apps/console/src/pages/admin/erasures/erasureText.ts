import { createElement, type ReactNode } from 'react';

import { ApiError, type ErasureState } from '@supportx/api-client';
import { hasLabel, useListFormat } from '@supportx/labels';
import { useLabel, type Tone } from '@supportx/ui';

// Words for the erasure screens (ADR-052). Codes from the API never reach the screen: module
// keys, record types, fields, holdings and counts go through labels, and an unknown code shows
// a neutral label, never itself (rule 5d).

type T = ReturnType<typeof useLabel>;

/** The right to see and act on erasures. */
export const ERASE = 'people.erase';
/** The legal-hold right (the audit module's). */
export const MANAGE_HOLDS = 'audit.manage_holds';

export const STATE_TONES: Record<ErasureState, Tone> = {
  requested: 'warning',
  approved: 'warning',
  running: 'warning',
  failed: 'error',
  done: 'success',
  rejected: 'default',
  expired: 'default',
};

function known(key: string, fallback: string): string {
  return hasLabel(key) ? key : fallback;
}

export const moduleLabel = (t: T, code: string) =>
  t(known(`people_erasure.module.${code}`, 'people_erasure.module.other'));
export const recordTypeLabel = (t: T, code: string) =>
  t(known(`people_erasure.record_type_of.${code}`, 'people_erasure.record_type_of.other'));
export const fieldLabel = (t: T, code: string) =>
  t(known(`people_erasure.field.${code}`, 'people_erasure.field.other'));
export const holdingLabel = (t: T, code: string) =>
  t(known(`erasure_holding.${code}`, 'erasure_holding.other'));
export const countLabel = (t: T, code: string) =>
  t(known(`erasure_count.${code}`, 'erasure_count.other'));
export const stepLabel = (t: T, code: string | null) =>
  code === null ? '' : t(known(`errors.${code}`, 'errors.erasure_step_failed'));
export const fileOwnerLabel = (t: T, code: string) =>
  t(known(`file_owner_type.${code}`, 'people_erasure.file_owner_other'));

/** The same comparison as the server's: spaces collapsed, case ignored. */
export function sameName(typed: string, name: string): boolean {
  const norm = (s: string) => s.trim().split(/\s+/u).join(' ').toLocaleLowerCase();
  return typed.trim() !== '' && norm(typed) === norm(name);
}

/** The text with each term marked (`<mark>`: the match never rests on colour alone). */
export function marked(text: string, terms: readonly string[]): ReactNode[] {
  const wanted = terms.map((s) => s.trim()).filter((s) => s !== '');
  if (wanted.length === 0) return [text];
  const escaped = wanted.map((s) => s.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'));
  const parts = text.split(new RegExp(`(${escaped.join('|')})`, 'giu'));
  const lowered = new Set(wanted.map((s) => s.toLocaleLowerCase()));
  return parts.map((part, index) =>
    lowered.has(part.toLocaleLowerCase()) ? createElement('mark', { key: index }, part) : part,
  );
}

/**
 * A refusal in words. `erasure_port_missing` names the missing parts of the product by label,
 * never by key (lane C's condition 7); its `missing_ports` is a comma-separated list.
 */
export function useErasureProblem() {
  const t = useLabel();
  const list = useListFormat();
  return (error: unknown): string => {
    if (!(error instanceof ApiError)) return t('errors.internal_error');
    const base = t(error.messageKey, error.params);
    if (error.code === 'erasure_port_missing') {
      const raw = error.params.missing_ports;
      const ports =
        typeof raw === 'string'
          ? raw
              .split(',')
              .map((p) => p.trim())
              .filter((p) => p !== '')
          : [];
      if (ports.length > 0) {
        return `${base} ${t('people_erasure.report.ports_missing', {
          modules: list(ports.map((p) => moduleLabel(t, p))),
        })}`;
      }
    }
    const fields = error.fieldErrors.map((f) => t(f.message_key, f.params ?? {}));
    return fields.length > 0 ? fields.join(' ') : base;
  };
}
