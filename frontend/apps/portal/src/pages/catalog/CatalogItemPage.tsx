import { App as AntApp, Alert, Button, Flex, Form, Input, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { ApiError, useCatalogItem, useRaiseServiceRequest, useSession } from '@supportx/api-client';
import {
  QuestionField,
  RichTextView,
  lengthLimit,
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

import { ForWhom } from '../requests/ForWhom';

const SUBJECT_MAX = 250;

/**
 * Request one catalog item in the portal (WP-031; REQ-SR-001..003): its summary, then its
 * description first (self-service before the form, D-138), then the questions meant for the
 * requester, for themselves or someone they may raise for. The new request opens at once.
 * One Idempotency-Key per form, so a double tap never makes two.
 */
export function CatalogItemPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();
  const { id } = useParams();
  const session = useSession().data;
  const loaded = useCatalogItem(id);
  const raise = useRaiseServiceRequest();
  const [key] = useState(() => crypto.randomUUID());
  const item = loaded.data;
  const questions = useMemo(() => requesterQuestions(item?.questions ?? []), [item]);
  const [answers, setAnswers] = useState<Record<string, QuestionValue> | null>(null);
  const [subject, setSubject] = useState<string | null>(null);
  const [onBehalf, setOnBehalf] = useState<string | null>(null);
  const [problems, setProblems] = useState<Record<string, string>>({});

  if (loaded.isLoading) return <Skeleton active />;
  if (item === undefined || session == null) {
    return (
      <Flex vertical gap={12}>
        <Link to="/catalog">{t('portal.catalog.back')}</Link>
        <Alert type="warning" showIcon message={t('errors.catalog_item_not_found')} />
      </Flex>
    );
  }
  const shown = answers ?? startingAnswers(questions);
  const name = textIn(item.names, locale);
  const typed = subject ?? name;
  const description = textIn(item.descriptions, locale);
  const missing = questions.filter((q) => {
    const value = shown[q.key];
    return (
      q.required && (value == null || value === '' || (Array.isArray(value) && value.length === 0))
    );
  });
  const ready = typed.trim() !== '' && missing.length === 0;

  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      <Link to="/catalog">{t('portal.catalog.back')}</Link>
      <Flex vertical gap={4}>
        <Typography.Title level={1} style={{ margin: 0 }}>
          {name}
        </Typography.Title>
        <Typography.Text type="secondary">{textIn(item.summaries, locale)}</Typography.Text>
      </Flex>
      {description !== '' && (
        <section aria-label={t('portal.catalog.about')} data-testid="portal-cat-description">
          <RichTextView html={description} />
        </section>
      )}
      <Form
        layout="vertical"
        requiredMark
        onFinish={() => {
          if (!ready) return;
          setProblems({});
          raise.mutate(
            {
              key,
              body: {
                subject: typed.trim(),
                requester_id: session.user.id,
                catalog_item_id: item.id,
                answers: sentAnswers(shown),
                confirm_lose_access: false,
                ...(onBehalf !== null ? { on_behalf_of_id: onBehalf } : {}),
              },
            },
            {
              onSuccess: (made) => {
                void message.success(t('portal.catalog.sent', { id: made.display_id }));
                void navigate(`/service-requests/${made.id}`, { replace: true });
              },
              onError: (error) => {
                if (error instanceof ApiError && error.status === 422) {
                  markHandled(error);
                  setProblems(
                    Object.fromEntries(
                      error.fieldErrors.map((f) => [
                        f.field.replace(/^body\.answers\./, ''),
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
        <Form.Item label={t('portal.report.for_whom')}>
          <ForWhom value={onBehalf} onChange={setOnBehalf} />
        </Form.Item>
        <Form.Item label={t('portal.report.subject')} htmlFor="portal-cat-subject" required>
          <Input
            id="portal-cat-subject"
            size="large"
            value={typed}
            count={lengthLimit(SUBJECT_MAX)}
            onChange={(event) => {
              setSubject(event.target.value);
            }}
            data-testid="portal-cat-subject"
          />
        </Form.Item>
        {questions.map((q) => (
          <Form.Item
            key={q.key}
            label={textIn(q.label, locale) || q.key}
            required={q.required}
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
        <Button
          type="primary"
          size="large"
          htmlType="submit"
          disabled={!ready}
          loading={raise.isPending}
          data-testid="portal-cat-send"
        >
          {t('portal.catalog.send')}
        </Button>
      </Form>
    </Flex>
  );
}
