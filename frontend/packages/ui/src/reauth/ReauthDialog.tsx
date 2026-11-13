import { Button, Modal, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import { setReauthConfirmer, type ReauthOutcome } from '@supportx/api-client';

import { useLabel } from '../appearance';
import { startConfirmation, type Confirmation, type ConfirmationDeps } from './confirmation';

type Phase = 'ask' | 'waiting' | 'unavailable';

export interface ReauthDialogProps {
  /** For tests: the browser's window, channel and clock stand-ins. */
  deps?: Partial<ConfirmationDeps>;
}

/**
 * The console's and portal's answer to 403 `reauth_required` (REQ-SEC-027; WP-057 S2a): asks the
 * person to sign in again in a pop-up, waits for the pop-up's answer, then the api-client sends
 * the refused change once more. Mounted inside the session gate: only a signed-in browser
 * confirms. The mobile app mounts none, so the refusal reaches its screen as it is.
 */
export function ReauthDialog({ deps }: ReauthDialogProps) {
  const t = useLabel();
  const [phase, setPhase] = useState<Phase | null>(null);
  const answer = useRef<((outcome: ReauthOutcome) => void) | null>(null);
  const running = useRef<Confirmation | null>(null);

  useEffect(() => {
    setReauthConfirmer(
      () =>
        new Promise<ReauthOutcome>((resolve) => {
          answer.current = resolve;
          setPhase('ask');
        }),
    );
    return () => {
      setReauthConfirmer(null);
      running.current?.cancel();
    };
  }, []);

  const finish = (outcome: ReauthOutcome) => {
    running.current = null;
    answer.current?.(outcome);
    answer.current = null;
    setPhase(outcome === 'unavailable' ? 'unavailable' : null);
  };

  const confirm = () => {
    // From this click: a pop-up blocker lets it open.
    const started = startConfirmation(deps);
    if (started === null) return; // blocked: the whole page goes to confirm and comes back
    running.current = started;
    setPhase('waiting');
    void started.outcome.then(finish);
  };

  const dismiss = () => {
    setPhase(null);
  };

  const cancel = () => {
    if (running.current !== null) running.current.cancel();
    else finish('failed');
  };

  const body =
    phase === 'unavailable'
      ? t('errors.reauth_unavailable')
      : phase === 'waiting'
        ? t('reauth.waiting')
        : t('reauth.body');
  const footer =
    phase === 'unavailable' ? (
      <Button type="primary" onClick={dismiss} data-testid="reauth-close">
        {t('actions.close')}
      </Button>
    ) : (
      <>
        <Button onClick={cancel} data-testid="reauth-cancel">
          {t('actions.cancel')}
        </Button>
        {phase === 'ask' && (
          <Button type="primary" onClick={confirm} data-testid="reauth-confirm">
            {t('reauth.confirm')}
          </Button>
        )}
      </>
    );
  return (
    <Modal
      open={phase !== null}
      title={t('reauth.title')}
      onCancel={phase === 'unavailable' ? dismiss : cancel}
      footer={footer}
      maskClosable={false}
      destroyOnHidden
    >
      <Typography.Paragraph data-testid={`reauth-${phase ?? 'closed'}`}>
        {body}
      </Typography.Paragraph>
    </Modal>
  );
}
