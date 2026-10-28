import { Button, Card, Flex, Input, Result, Typography } from 'antd';
import { useState, type FormEvent } from 'react';

import { loginUrl, useRequestPasswordReset, type App } from '@supportx/api-client';

import { useLabel } from './appearance';
import { BrandedPage } from './brand';
import { FormProblem, useFormProblem } from './errors';

export const PASSWORD_RESET_PATH = '/password-reset';

// A light check only: the server answers the same for every address (nothing to learn from it).
const LOOKS_LIKE_EMAIL = /^[^\s@]+@[^\s@]+$/;

/**
 * "Forgot password?" (WP-039 session 2; REQ-SEC-006, REQ-SEC-035; D-099), outside the session
 * gate: the sign-in page links here. The person types their email and always sees the same
 * answer; Keycloak sends the set-password e-mail in the tenant's brand, valid 60 minutes, once.
 * The new password is chosen on the sign-in service's page and never passes through SupportX.
 */
export function PasswordResetPage({ app }: { app: App }) {
  const t = useLabel();
  const request = useRequestPasswordReset();
  const [email, setEmail] = useState('');
  const [touched, setTouched] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  // A refusal (too many requests, a rule) is shown in the form (QA WP-029 BUG-02).
  const problem = useFormProblem();
  const valid = LOOKS_LIKE_EMAIL.test(email.trim());
  const back = (
    <Button href={loginUrl(app, '/')} data-testid="reset-back">
      {t('reset.back')}
    </Button>
  );
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid) return;
    const address = email.trim();
    problem.clear();
    request.mutate(address, {
      onSuccess: () => {
        setSentTo(address);
      },
      onError: problem.show,
    });
  };

  return (
    <BrandedPage>
      <main style={{ width: '100%', maxWidth: 440, padding: 16 }} data-testid="password-reset">
        {sentTo === null ? (
          <Card>
            <form onSubmit={submit} noValidate>
              <Flex vertical gap={16}>
                <Typography.Title level={1} style={{ fontSize: 24, margin: 0 }}>
                  {t('reset.title')}
                </Typography.Title>
                <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
                  {t('reset.intro')}
                </Typography.Paragraph>
                <Flex vertical gap={4}>
                  <label htmlFor="reset-email">{t('reset.email')}</label>
                  <Input
                    id="reset-email"
                    type="email"
                    autoComplete="email"
                    dir="ltr"
                    value={email}
                    onChange={(event) => {
                      setEmail(event.target.value);
                    }}
                    status={touched && !valid ? 'error' : undefined}
                    aria-describedby="reset-email-problem"
                    data-testid="reset-email"
                  />
                  {touched && !valid && (
                    <Typography.Text type="danger" role="alert" id="reset-email-problem">
                      {t('reset.email_invalid')}
                    </Typography.Text>
                  )}
                </Flex>
                <FormProblem problem={problem} />
                <Flex gap={8} wrap>
                  <Button
                    type="primary"
                    htmlType="submit"
                    loading={request.isPending}
                    data-testid="reset-send"
                  >
                    {t('reset.send')}
                  </Button>
                  {back}
                </Flex>
              </Flex>
            </form>
          </Card>
        ) : (
          <div data-testid="reset-sent">
            <Result
              status="success"
              title={t('reset.sent_title')}
              subTitle={t('reset.sent', { email: sentTo })}
              extra={back}
            />
          </div>
        )}
      </main>
    </BrandedPage>
  );
}
