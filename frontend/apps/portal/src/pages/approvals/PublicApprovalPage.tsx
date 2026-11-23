import {
  Button,
  Card,
  Checkbox,
  Flex,
  Form,
  Input,
  Result,
  Skeleton,
  Space,
  Typography,
} from 'antd';
import { useEffect, useState } from 'react';

import {
  ApiError,
  loginUrl,
  usePublicActionLink,
  usePublicPeekActionLink,
} from '@supportx/api-client';
import { describeError, lengthLimit, useLabel } from '@supportx/ui';

import { HANDOVER_KEY } from './handover';
import { linkTenant, useFragmentToken } from '../publicLink';

const COMMENT_MAX = 4000;
const SIGN_IN_REQUIRED = 'action_link_sign_in_required';

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function refusalText(t: ReturnType<typeof useLabel>, error: unknown): string {
  return error instanceof ApiError ? describeError(error, t).title : t('errors.internal_error');
}

/**
 * Approve or reject from an e-mail without signing in (D-132, the default): a confirmation
 * page first, since mail scanners open links; nothing is decided until a button is pressed.
 * When the tenant asks for a signed-in approver, the page sends the person to sign in and on to
 * the signed-in page with the same link. No third-party resources; the token never leaves the
 * page except in the POST body (lane B's review).
 */
export function PublicApprovalPage() {
  const t = useLabel();
  const token = useFragmentToken();
  const [tenant] = useState(linkTenant);
  const peek = usePublicPeekActionLink(token, tenant);
  const act = usePublicActionLink();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const [done, setDone] = useState<'approve' | 'reject'>();
  const signIn =
    peek.error instanceof ApiError && peek.error.code === SIGN_IN_REQUIRED && token !== undefined;
  useEffect(() => {
    if (!signIn) return;
    // The token stays in this tab only, never in the sign-in URL, its stored state or a log;
    // the signed-in page takes it and removes it at once.
    try {
      window.sessionStorage.setItem(HANDOVER_KEY, token);
    } catch {
      // Storage blocked: the person signs in and opens the e-mail's link again.
    }
    window.location.assign(loginUrl('portal', '/requests/approval-link'));
  }, [signIn, token]);

  let content;
  if (token === undefined) {
    content = <Result status="warning" title={t('errors.action_link_not_found')} />;
  } else if (peek.isLoading || signIn) {
    content = <Skeleton active />;
  } else if (peek.error) {
    content = (
      <div data-testid="public-approval-refused">
        <Result status="info" title={refusalText(t, peek.error)} />
      </div>
    );
  } else if (done !== undefined) {
    content = (
      <div data-testid="public-approval-done">
        <Result
          status="success"
          title={t(done === 'approve' ? 'requests.link_approved' : 'requests.link_rejected')}
        />
      </div>
    );
  } else {
    const summary = peek.data?.summary ?? {};
    const reasonMissing = comment.trim() === '';
    const send = (decision: 'approve' | 'reject') => {
      act.mutate(
        {
          token,
          tenant,
          body: { decision, comment: comment.trim() || null, private: isPrivate },
        },
        {
          onSuccess: () => {
            setDone(decision);
          },
        },
      );
    };
    content = (
      <Flex vertical gap={16}>
        <Typography.Title level={1}>{t('requests.approval_by_link')}</Typography.Title>
        <Card data-testid="public-approval-summary">
          <span dir="ltr">{text(summary.display_id)}</span> · <bdi>{text(summary.subject)}</bdi>
        </Card>
        <Form layout="vertical">
          <Form.Item
            label={t('requests.decision_comment')}
            htmlFor="public-approval-comment"
            extra={t('requests.reject_needs_reason')}
            validateStatus={act.error ? 'error' : undefined}
            help={act.error ? refusalText(t, act.error) : undefined}
          >
            <Input.TextArea
              id="public-approval-comment"
              data-testid="public-approval-comment"
              value={comment}
              count={lengthLimit(COMMENT_MAX)}
              autoSize={{ minRows: 3 }}
              onChange={(e) => {
                setComment(e.target.value);
              }}
            />
          </Form.Item>
          <Checkbox
            checked={isPrivate}
            onChange={(e) => {
              setPrivate(e.target.checked);
            }}
          >
            {t('requests.private_comment')}
          </Checkbox>
        </Form>
        <Space>
          <Button
            type="primary"
            size="large"
            loading={act.isPending}
            disabled={summary.comments_required === true && reasonMissing}
            onClick={() => {
              send('approve');
            }}
            data-testid="public-approval-approve"
          >
            {t('requests.approve')}
          </Button>
          <Button
            danger
            size="large"
            loading={act.isPending}
            disabled={reasonMissing}
            onClick={() => {
              send('reject');
            }}
            data-testid="public-approval-reject"
          >
            {t('requests.reject')}
          </Button>
        </Space>
      </Flex>
    );
  }
  return (
    <main style={{ maxWidth: 640, margin: '0 auto', padding: 16 }} data-testid="public-approval">
      {content}
    </main>
  );
}
