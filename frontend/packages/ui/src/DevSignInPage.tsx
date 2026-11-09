import { Alert, Button, Card, Flex, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';

import { useLabel } from './appearance';
import { BrandedPage } from './brand';

/**
 * Dev-only quick sign-in (D-151): one button per Showcase Company persona, for browser-driven QA.
 *
 * The API answers 404 unless the local dev stack switched it on and the page is on localhost, so
 * anywhere else this page only says it isn't available. Its two endpoints are kept out of the
 * OpenAPI document on purpose (they are not part of the product API), so their shapes are
 * declared here rather than generated.
 */

interface Persona {
  code: string;
  email: string;
  app: 'console' | 'portal';
  enrolled: boolean;
}

interface Problem {
  message_key?: string;
  params?: Record<string, string | number>;
}

// Absolute, as the generated client builds its URLs (a relative one is refused outside a page).
const base = () => `${window.location.origin}/api/v1/auth/dev`;

export function DevSignInPage() {
  const t = useLabel();
  const [personas, setPersonas] = useState<Persona[] | null | undefined>(undefined);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    void fetch(`${base()}/personas`, { credentials: 'same-origin' })
      .then(async (answer) => (answer.ok ? ((await answer.json()) as Persona[]) : null))
      .catch(() => null)
      .then(setPersonas);
  }, []);

  const signIn = async (persona: Persona) => {
    setBusy(persona.code);
    setProblem(null);
    try {
      const answer = await fetch(`${base()}/sign-in`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona: persona.code }),
      });
      if (answer.ok) {
        const { redirect_to } = (await answer.json()) as { redirect_to: string };
        window.location.assign(redirect_to);
        return;
      }
      const body = (await answer.json().catch(() => ({}))) as Problem;
      const reason = body.params?.reason;
      // The refusal in words: Keycloak's reason when it gave one (never a raw code).
      setProblem(
        typeof reason === 'string'
          ? t(`dev_sign_in.reason.${reason}`)
          : t(body.message_key ?? 'errors.internal_error', body.params),
      );
    } catch {
      setProblem(t('errors.internal_error'));
    }
    setBusy(null);
  };

  return (
    <BrandedPage>
      <main style={{ width: '100%', maxWidth: 520, padding: 16 }} data-testid="dev-sign-in">
        <Card>
          <Flex vertical gap={16}>
            <Typography.Title level={1} style={{ fontSize: 24, margin: 0 }}>
              {t('dev_sign_in.title')}
            </Typography.Title>
            <Alert type="warning" showIcon message={t('dev_sign_in.warning')} />
            {personas === undefined && <Spin />}
            {personas === null && (
              <Typography.Paragraph data-testid="dev-sign-in-unavailable" style={{ margin: 0 }}>
                {t('dev_sign_in.unavailable')}
              </Typography.Paragraph>
            )}
            {problem !== null && (
              <Alert
                type="error"
                showIcon
                role="alert"
                message={problem}
                data-testid="dev-sign-in-problem"
              />
            )}
            {personas?.map((persona) => (
              <Button
                key={persona.code}
                size="large"
                block
                loading={busy === persona.code}
                disabled={busy !== null && busy !== persona.code}
                onClick={() => void signIn(persona)}
                data-testid={`dev-sign-in-${persona.code}`}
              >
                <span>
                  {t('dev_sign_in.as', { persona: t(`dev_persona.${persona.code}`) })}
                  {' · '}
                  {t(`dev_sign_in.app_${persona.app}`)}
                  {!persona.enrolled && <> — {t('dev_sign_in.sets_up_mfa')}</>}
                </span>
              </Button>
            ))}
          </Flex>
        </Card>
      </main>
    </BrandedPage>
  );
}
