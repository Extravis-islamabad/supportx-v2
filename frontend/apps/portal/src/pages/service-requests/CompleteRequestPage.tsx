import { Alert, Button, Flex, Form, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import {
  ApiError,
  useCatalogItem,
  useCompletePortalAnswers,
  usePortalMissingAnswers,
} from '@supportx/api-client';
import {
  QuestionField,
  markHandled,
  reportError,
  requesterQuestions,
  sentAnswers,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  type QuestionValue,
} from '@supportx/ui';

import { FormCard } from '../FormCard';
import { FORM_COLUMN } from '../formColumn';

/**
 * A request made from mail that waits for answers (WP-047a S4; REQ-SR-017 AC2): only the item's
 * required questions still unanswered, then the request goes ahead as any other (AC3). The link
 * comes in the request's mail; anything not yours, or no longer waiting, reads as not found.
 */
export function CompleteRequestPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const id = useParams().id ?? '';
  const missing = usePortalMissingAnswers(id);
  const item = useCatalogItem(missing.data?.catalog_item_id ?? '');
  const complete = useCompletePortalAnswers(id);
  const asked = useMemo(() => {
    const keys = new Set(missing.data?.missing ?? []);
    return requesterQuestions(item.data?.questions ?? []).filter((q) => keys.has(q.key));
  }, [missing.data, item.data]);
  const [answers, setAnswers] = useState<Record<string, QuestionValue> | null>(null);
  const [problems, setProblems] = useState<Record<string, string>>({});
  if (missing.isError) {
    return (
      <Flex vertical gap={16} style={FORM_COLUMN}>
        <Alert type="info" showIcon message={t('portal.complete.not_waiting')} />
        <Link to={`/service-requests/${id}`}>{t('portal.complete.open_request')}</Link>
      </Flex>
    );
  }
  if (missing.data === undefined || item.data === undefined) {
    return <Skeleton active />;
  }
  const shown = answers ?? startingAnswers(asked);
  const unanswered = asked.filter((q) => {
    const value = shown[q.key];
    return value == null || value === '' || (Array.isArray(value) && value.length === 0);
  });
  const version = missing.data.version;
  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.complete.title')}
      </Typography.Title>
      <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
        {t('portal.complete.intro', { item: textIn(item.data.names, locale) })}
      </Typography.Paragraph>
      <FormCard testId="portal-complete">
        <Form
          layout="vertical"
          requiredMark
          onFinish={() => {
            if (unanswered.length > 0) return;
            setProblems({});
            complete.mutate(
              { answers: sentAnswers(shown), version },
              {
                onSuccess: () => {
                  void navigate(`/service-requests/${id}?submitted=1`, { replace: true });
                },
                onError: (error) => {
                  if (error instanceof ApiError && error.status === 422) {
                    markHandled(error);
                    setProblems(
                      Object.fromEntries(
                        error.fieldErrors.map((f) => [
                          f.field.replace(/^(body\.)?answers\./, ''),
                          t(f.message_key, f.params ?? {}),
                        ]),
                      ),
                    );
                    return;
                  }
                  reportError(error);
                },
              },
            );
          }}
        >
          {asked.map((q) => (
            <Form.Item
              key={q.key}
              label={textIn(q.label, locale) || q.key}
              required
              extra={textIn(q.help, locale) || undefined}
              htmlFor={`sr-q-${q.key}`}
              validateStatus={problems[q.key] !== undefined ? 'error' : undefined}
              help={problems[q.key]}
            >
              <QuestionField
                question={q}
                value={shown[q.key] ?? null}
                onChange={(value) => {
                  setAnswers({ ...shown, [q.key]: value });
                }}
                locale={locale}
              />
            </Form.Item>
          ))}
          <Flex gap={8} align="center" wrap>
            <Button
              type="primary"
              htmlType="submit"
              loading={complete.isPending}
              disabled={unanswered.length > 0}
              data-testid="portal-complete-send"
            >
              {t('portal.complete.send')}
            </Button>
            {unanswered.length > 0 && (
              <Typography.Text type="secondary">{t('requests.why.answers')}</Typography.Text>
            )}
          </Flex>
        </Form>
      </FormCard>
    </Flex>
  );
}
