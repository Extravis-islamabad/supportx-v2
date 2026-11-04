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
import { useState } from 'react';
import { Link } from 'react-router';

import { ApiError, useActionLink, usePeekActionLink } from '@supportx/api-client';
import { describeError, lengthLimit, PageHeader, useLabel } from '@supportx/ui';

const COMMENT_MAX = 4000;

/**
 * The token from the URL fragment, read once and then removed from the address bar and the
 * history, so it never sits in a bookmark, a shared screen or a Referer (lane B's condition 3).
 */
function useFragmentToken(): string | undefined {
  const [token] = useState(() => {
    const found = window.location.hash.replace(/^#/, '');
    if (found !== '') {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    return found === '' ? undefined : found;
  });
  return token;
}

/** A summary field as text (the server sends strings; anything else shows nothing). */
function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

/** Words for a refusal (its code's label), never a code or a status. */
function refusalText(t: ReturnType<typeof useLabel>, error: unknown): string {
  return error instanceof ApiError ? describeError(error, t).title : t('errors.internal_error');
}

/**
 * Approve or reject from an e-mail link (WP-030 s3, REQ-SR-026). Opening it never decides
 * (condition 1): the page shows the request and the approver chooses; the server checks the
 * link and the approval again when they do. Sign-in is required (plan D7 interim default).
 */
export function ActionLinkPage() {
  const t = useLabel();
  const token = useFragmentToken();
  const peek = usePeekActionLink(token);
  const act = useActionLink();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const [done, setDone] = useState<'approve' | 'reject'>();

  if (token === undefined) {
    return <Result status="warning" title={t('errors.action_link_not_found')} />;
  }
  if (peek.isLoading) return <Skeleton active />;
  if (peek.error) {
    return (
      <div data-testid="action-link-refused">
        <Result
          status="info"
          title={refusalText(t, peek.error)}
          extra={<Link to="/requests">{t('nav.requests')}</Link>}
        />
      </div>
    );
  }
  const summary = peek.data?.summary ?? {};
  const recordId = typeof summary.record_id === 'string' ? summary.record_id : '';
  const commentsRequired = summary.comments_required === true;
  if (done !== undefined) {
    return (
      <div data-testid="action-link-done">
        <Result
          status="success"
          title={t(done === 'approve' ? 'requests.link_approved' : 'requests.link_rejected')}
          extra={<Link to={`/requests/${recordId}`}>{t('requests.open_request')}</Link>}
        />
      </div>
    );
  }
  const send = (decision: 'approve' | 'reject') => {
    act.mutate(
      { token, body: { decision, comment: comment.trim() || null, private: isPrivate } },
      {
        onSuccess: () => {
          setDone(decision);
        },
      },
    );
  };
  const reasonMissing = comment.trim() === '';
  return (
    <Flex vertical gap={16} style={{ maxWidth: 640 }}>
      <PageHeader title={t('requests.approval_by_link')} />
      <Card data-testid="action-link-summary">
        <Typography.Paragraph>
          <span dir="ltr">{text(summary.display_id)}</span> · <bdi>{text(summary.subject)}</bdi>
        </Typography.Paragraph>
        <Link to={`/requests/${recordId}`}>{t('requests.open_request')}</Link>
      </Card>
      <Form layout="vertical">
        <Form.Item
          label={t('requests.decision_comment')}
          htmlFor="action-link-comment"
          extra={t('requests.reject_needs_reason')}
          validateStatus={act.error ? 'error' : undefined}
          help={act.error ? refusalText(t, act.error) : undefined}
        >
          <Input.TextArea
            id="action-link-comment"
            data-testid="action-link-comment"
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
          loading={act.isPending}
          disabled={commentsRequired && reasonMissing}
          onClick={() => {
            send('approve');
          }}
          data-testid="action-link-approve"
        >
          {t('requests.approve')}
        </Button>
        <Button
          danger
          loading={act.isPending}
          disabled={reasonMissing}
          onClick={() => {
            send('reject');
          }}
          data-testid="action-link-reject"
        >
          {t('requests.reject')}
        </Button>
      </Space>
    </Flex>
  );
}
