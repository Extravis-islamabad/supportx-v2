import { Alert, Button, Card, Flex, Input, Result, Skeleton, Typography } from 'antd';
import { useState, type FormEvent } from 'react';

import {
  ApiError,
  loginUrl,
  useAcceptInviteLink,
  usePeekInviteLink,
  type App,
} from '@supportx/api-client';

import { useLabel } from './appearance';
import { BrandedPage } from './brand';
import { describeError } from './errors';
import { linkTenant, useFragmentToken } from './publicLink';

/**
 * A copied invite link (WP-057 S2b-2; REQ-SEC-021), outside the session gate: where outgoing
 * mail is not set up, an admin passes the link on and the person sets their first password here.
 *
 * Lane B's conditions: the token is read from the fragment and the fragment cleared before any
 * request (`useFragmentToken`, which also sets no-referrer); it is posted in the body, never put
 * in a URL; nothing from a third party loads here. A link that does not work gets one message;
 * a password rule is told only once the link checked out. Nobody is signed in by this page: the
 * person signs in as usual afterwards.
 */
export function InvitePage({ app }: { app: App }) {
  const t = useLabel();
  const token = useFragmentToken();
  const [tenant] = useState(linkTenant);
  const peek = usePeekInviteLink(token, tenant);
  const accept = useAcceptInviteLink();
  const [password, setPassword] = useState('');
  const [again, setAgain] = useState('');
  const [touched, setTouched] = useState(false);
  const [done, setDone] = useState(false);

  const dead = (error: unknown) => error instanceof ApiError && error.status === 404;
  const failed = (error: unknown) =>
    error instanceof ApiError ? describeError(error, t).title : t('errors.internal_error');
  const fieldProblem =
    accept.error instanceof ApiError && accept.error.status === 422
      ? accept.error.fieldErrors[0]
      : undefined;
  const mismatch = touched && again !== password;
  const signIn = (
    <Button type="primary" href={loginUrl(peek.data?.app ?? app, '/')} data-testid="invite-sign-in">
      {t('invite_page.sign_in')}
    </Button>
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (token === undefined || password === '' || again !== password) return;
    accept.mutate(
      { token, tenant, password },
      {
        onSuccess: () => {
          setPassword('');
          setAgain('');
          setDone(true);
        },
      },
    );
  };

  let content;
  if (token === undefined || dead(peek.error) || dead(accept.error)) {
    content = (
      <div data-testid="invite-gone">
        <Result status="info" title={t('errors.invite_link_invalid')} />
      </div>
    );
  } else if (peek.error !== null) {
    // An outage or a lost connection: the link may well work, so try again (never "dead").
    content = (
      <Flex vertical gap={12} align="start" data-testid="invite-failed">
        <Alert type="error" showIcon message={failed(peek.error)} />
        <Button onClick={() => void peek.refetch()}>{t('actions.retry')}</Button>
      </Flex>
    );
  } else if (peek.isLoading || peek.data === undefined) {
    content = <Skeleton active />;
  } else if (done) {
    content = (
      <div data-testid="invite-done">
        <Result
          status="success"
          title={t('invite_page.done_title')}
          subTitle={t('invite_page.done_body')}
          extra={signIn}
        />
      </div>
    );
  } else {
    const rules = peek.data.rules;
    const needs = [
      t('invite_page.rule_length', { count: rules.min_length }),
      ...(rules.upper ? [t('invite_page.rule_upper')] : []),
      ...(rules.lower ? [t('invite_page.rule_lower')] : []),
      ...(rules.digits ? [t('invite_page.rule_digit')] : []),
      ...(rules.special ? [t('invite_page.rule_special')] : []),
    ];
    content = (
      <Card>
        <form onSubmit={submit} noValidate>
          <Flex vertical gap={16}>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t('invite_page.intro')}
            </Typography.Paragraph>
            <ul style={{ margin: 0, paddingInlineStart: 20 }} data-testid="invite-rules">
              {needs.map((need) => (
                <li key={need}>{need}</li>
              ))}
            </ul>
            <Flex vertical gap={4}>
              <label htmlFor="invite-password">{t('invite_page.password')}</label>
              <Input.Password
                id="invite-password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  accept.reset();
                }}
                status={fieldProblem === undefined ? undefined : 'error'}
                aria-describedby={
                  fieldProblem === undefined ? undefined : 'invite-password-problem'
                }
                data-testid="invite-password"
              />
              {fieldProblem !== undefined && (
                <Typography.Text
                  type="danger"
                  role="alert"
                  id="invite-password-problem"
                  data-testid="invite-password-problem"
                >
                  {t(fieldProblem.message_key, fieldProblem.params)}
                </Typography.Text>
              )}
            </Flex>
            <Flex vertical gap={4}>
              <label htmlFor="invite-again">{t('invite_page.again')}</label>
              <Input.Password
                id="invite-again"
                autoComplete="new-password"
                value={again}
                onChange={(event) => {
                  setAgain(event.target.value);
                }}
                status={mismatch ? 'error' : undefined}
                aria-describedby={mismatch ? 'invite-again-problem' : undefined}
                data-testid="invite-again"
              />
              {mismatch && (
                <Typography.Text type="danger" role="alert" id="invite-again-problem">
                  {t('invite_page.mismatch')}
                </Typography.Text>
              )}
            </Flex>
            {accept.error !== null && fieldProblem === undefined && !dead(accept.error) && (
              <Alert type="error" showIcon message={failed(accept.error)} />
            )}
            <Button
              type="primary"
              htmlType="submit"
              loading={accept.isPending}
              disabled={password === ''}
              data-testid="invite-submit"
            >
              {t('invite_page.submit')}
            </Button>
          </Flex>
        </form>
      </Card>
    );
  }

  return (
    <BrandedPage>
      <main style={{ width: '100%', maxWidth: 480, padding: 16 }} data-testid="invite-page">
        <Flex vertical gap={16}>
          <Typography.Title level={1} style={{ fontSize: 24, margin: 0 }}>
            {t('invite_page.title')}
          </Typography.Title>
          {content}
        </Flex>
      </main>
    </BrandedPage>
  );
}
