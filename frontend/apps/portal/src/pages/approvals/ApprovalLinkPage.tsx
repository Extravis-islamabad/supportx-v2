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
import { Link } from 'react-router';

import { ApiError, useActionLink, usePeekActionLink } from '@supportx/api-client';
import { describeError, lengthLimit, useLabel } from '@supportx/ui';

import { HANDOVER_KEY } from './handover';
import { FORM_COLUMN } from '../formColumn';

const COMMENT_MAX = 4000;

/** The token from the URL fragment, read once and removed from the address bar and history. */
/** A token handed over by the public page while the person signed in (never in a URL). */
function handedOver(): string | undefined {
  try {
    return window.sessionStorage.getItem(HANDOVER_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

function useFragmentToken(): string | undefined {
  // Read without side effects: StrictMode calls an initializer twice and keeps one result.
  const [token] = useState(() => {
    const found = window.location.hash.replace(/^#/, '');
    return found === '' ? handedOver() : found;
  });
  // Then off the address bar and the history (lane B's condition 3).
  useEffect(() => {
    if (window.location.hash !== '') {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    try {
      window.sessionStorage.removeItem(HANDOVER_KEY); // taken: gone at once
    } catch {
      // nothing stored
    }
  }, []);
  return token;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function refusalText(t: ReturnType<typeof useLabel>, error: unknown): string {
  return error instanceof ApiError ? describeError(error, t).title : t('errors.internal_error');
}

/**
 * Approve or reject from an e-mail link in the portal (WP-030 s3, REQ-SR-022 AC2: a
 * requester-only approver decides here; D-129 keeps them out of the console). Opening it never
 * decides; the server checks the link and the approval again on the click (lane B's review).
 */
export function ApprovalLinkPage() {
  const t = useLabel();
  const token = useFragmentToken();
  const peek = usePeekActionLink(token);
  const act = useActionLink();
  const [comment, setComment] = useState('');
  const [isPrivate, setPrivate] = useState(false);
  const [done, setDone] = useState<'approve' | 'reject'>();
  const back = <Link to="/approvals">{t('portal.approvals.title')}</Link>;

  if (token === undefined) {
    return <Result status="warning" title={t('errors.action_link_not_found')} extra={back} />;
  }
  if (peek.isLoading) return <Skeleton active />;
  if (peek.error) {
    return (
      <div data-testid="approval-link-refused">
        <Result status="info" title={refusalText(t, peek.error)} extra={back} />
      </div>
    );
  }
  if (done !== undefined) {
    return (
      <div data-testid="approval-link-done">
        <Result
          status="success"
          title={t(done === 'approve' ? 'requests.link_approved' : 'requests.link_rejected')}
          extra={back}
        />
      </div>
    );
  }
  const summary = peek.data?.summary ?? {};
  const commentsRequired = summary.comments_required === true;
  const reasonMissing = comment.trim() === '';
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
  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Typography.Title level={1}>{t('requests.approval_by_link')}</Typography.Title>
      <Card data-testid="approval-link-summary">
        <span dir="ltr">{text(summary.display_id)}</span> · <bdi>{text(summary.subject)}</bdi>
      </Card>
      <Form layout="vertical">
        <Form.Item
          label={t('requests.decision_comment')}
          htmlFor="approval-link-comment"
          extra={t('requests.reject_needs_reason')}
          validateStatus={act.error ? 'error' : undefined}
          help={act.error ? refusalText(t, act.error) : undefined}
        >
          <Input.TextArea
            id="approval-link-comment"
            data-testid="approval-link-comment"
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
          disabled={commentsRequired && reasonMissing}
          onClick={() => {
            send('approve');
          }}
          data-testid="approval-link-approve"
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
          data-testid="approval-link-reject"
        >
          {t('requests.reject')}
        </Button>
      </Space>
    </Flex>
  );
}
