import { Button, Flex, Typography, theme } from 'antd';
import { useEffect } from 'react';

import { useLabel } from '../appearance';
import { SPACE } from '../density';
import { WriteButton } from '../licence/WriteButton';

export interface StickySaveBarProps {
  /** How many fields differ from what is saved; the bar shows only while there are some. */
  changes: number;
  saving?: boolean;
  onDiscard: () => void;
  onSave: () => void;
  testId?: string;
}

/**
 * The one save area of a settings form page (QA6S-SHELL-05): "3 unsaved changes · Discard ·
 * Save", fixed at the bottom while the form differs from what is saved. Save is disabled only
 * while saving (validation runs on save). Closing or reloading the tab asks first; leaving for
 * another page inside the app is guarded by the console's `useLeaveGuard`.
 */
export function StickySaveBar({
  changes,
  saving = false,
  onDiscard,
  onSave,
  testId,
}: StickySaveBarProps) {
  const t = useLabel();
  const { token } = theme.useToken();
  useEffect(() => {
    if (changes === 0) return undefined;
    const ask = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener('beforeunload', ask);
    return () => {
      window.removeEventListener('beforeunload', ask);
    };
  }, [changes]);
  if (changes === 0) return null;
  return (
    <div
      role="region"
      aria-label={t('settings.unsaved_region')}
      data-testid={testId ?? 'settings-save-bar'}
      style={{
        position: 'sticky',
        bottom: 0,
        zIndex: 10,
        marginTop: SPACE.md,
        padding: `${String(SPACE.sm)}px ${String(SPACE.md)}px`,
        background: token.colorBgContainer,
        borderTop: `1px solid ${token.colorBorderSecondary}`,
        boxShadow: token.boxShadowSecondary,
      }}
    >
      <Flex justify="space-between" align="center" wrap gap={SPACE.sm}>
        <Typography.Text strong aria-live="polite">
          {t('settings.unsaved', { count: changes })}
        </Typography.Text>
        <Flex gap={SPACE.xs}>
          <Button onClick={onDiscard} disabled={saving} data-testid="settings-discard">
            {t('settings.discard')}
          </Button>
          {/* A read-only licence disables Save with its reason (coverage 2026-11-09 §17). */}
          <WriteButton type="primary" onClick={onSave} loading={saving} data-testid="settings-save">
            {t('actions.save')}
          </WriteButton>
        </Flex>
      </Flex>
    </div>
  );
}
