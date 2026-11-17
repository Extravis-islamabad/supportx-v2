import { Typography } from 'antd';

import { useUser } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

// Small shared parts of the erasure screens (ADR-052); the words themselves are erasureText.ts.

/** "3/8", read out as "Step 3 of 8" (lane C: never a bare progress bar). */
export function StepProgress({ step, steps }: { step: number; steps: number }) {
  const t = useLabel();
  return (
    <span aria-label={t('people_erasure.progress_aria', { step, steps })}>
      <bdi dir="ltr">{t('people_erasure.progress', { step, steps })}</bdi>
    </span>
  );
}

/**
 * A person by name. While loading, or when you may not see them, a neutral word; an erased
 * person shows as "Erased person" (the screen never shows an ID).
 */
export function PersonName({ id, erased = false }: { id: string | null; erased?: boolean }) {
  const t = useLabel();
  const person = useUser(id === null || erased ? undefined : id, { silent: true });
  if (erased) return <span>{t('people_erasure.erased_person')}</span>;
  if (id === null) return null;
  const name = person.data?.display_name;
  return name === undefined ? (
    <Typography.Text type="secondary">{t('people_erasure.unknown_person')}</Typography.Text>
  ) : (
    <bdi dir="auto">{name}</bdi>
  );
}
