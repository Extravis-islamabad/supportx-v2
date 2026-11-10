import { App as AntApp, Alert, Button, Flex, Form, Input, Skeleton, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';

import { ApiError, useCatalogItem, useRaiseServiceRequest, useSession } from '@supportx/api-client';
import {
  FormFooter,
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
  useLicence,
} from '@supportx/ui';

import { AttachFiles } from '../requests/attachFiles';
import { useFilesToAttach } from '../requests/useFilesToAttach';
import { ForWhom } from '../requests/ForWhom';
import { FormCard } from '../FormCard';
import { deliveryText } from './delivery';
import { FORM_COLUMN } from '../formColumn';
import { AssetsField } from '../requests/AssetsField';

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
  const files = useFilesToAttach();
  const [assetIds, setAssetIds] = useState<string[]>([]);
  const hasAssets = useLicence().has('assets');
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
  // What is still missing, said beside the disabled button (Haider, 2026-11-10).
  const why =
    typed.trim() === ''
      ? t('requests.why.subject')
      : missing.length > 0
        ? t('requests.why.answers')
        : null;
  // What is included: the steps a requester may see; and who approves it first.
  const included = item.plan
    .filter((step) => !step.internal)
    .map((step) => textIn(step.title, locale))
    .filter((title) => title !== '');
  const delivery = deliveryText(t, item.expected_delivery);
  const approval =
    item.approval === null || item.approval.approvers.length === 0
      ? null
      : item.approval.approvers.some((a) => a.kind === 'requested_for_manager')
        ? t('portal.catalog.manager_approves')
        : t('portal.catalog.someone_approves');

  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
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
      {(included.length > 0 || approval !== null || delivery !== null) && (
        <FormCard testId="portal-cat-context">
          {included.length > 0 && (
            <div data-testid="portal-cat-included">
              <Typography.Text strong>{t('requests.context.included')}</Typography.Text>
              <ul style={{ marginTop: 4, marginBottom: approval === null ? 0 : 12 }}>
                {included.map((title) => (
                  <li key={title}>
                    <bdi dir="auto">{title}</bdi>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {approval !== null && (
            <Typography.Paragraph style={{ margin: 0 }} data-testid="portal-cat-approval">
              {approval}
            </Typography.Paragraph>
          )}
          {delivery !== null && (
            <Typography.Paragraph
              style={{ margin: approval === null ? 0 : '8px 0 0' }}
              data-testid="portal-cat-delivery"
            >
              {delivery}
            </Typography.Paragraph>
          )}
        </FormCard>
      )}
      <FormCard testId="portal-cat-form">
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
                  ...(assetIds.length > 0 ? { asset_ids: assetIds } : {}),
                },
              },
              {
                onSuccess: (made) => {
                  void message.success(t('portal.catalog.sent', { id: made.display_id }));
                  // The files go to the new request, then what happens next (WP-032 D4, D5).
                  void files
                    .attach(made.id)
                    .then(() =>
                      navigate(`/service-requests/${made.id}?submitted=1`, { replace: true }),
                    );
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
          <Form.Item label={t('portal.request.subject')} htmlFor="portal-cat-subject" required>
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
          {/* REQ-AST-025: the assets it is about, the person's own only (AC1). */}
          {hasAssets && (
            <Form.Item label={t('work_item.field.asset_ids')} htmlFor="portal-cat-assets">
              <AssetsField
                id="portal-cat-assets"
                value={assetIds}
                onChange={setAssetIds}
                forUser={onBehalf}
                testId="portal-cat-assets"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.files')}>
            <AttachFiles
              files={files.files}
              keep={files.keep}
              remove={files.remove}
              testId="portal-cat"
            />
          </Form.Item>
          {/* Template B's footer (D-147, Haider 2026-11-10): Cancel, then the request. */}
          <FormFooter
            testId="portal-cat-footer"
            notice={
              why === null ? undefined : (
                <Typography.Text type="secondary" id="portal-cat-why" data-testid="portal-cat-why">
                  {why}
                </Typography.Text>
              )
            }
            cancel={
              <Button
                size="large"
                onClick={() => void navigate('/catalog')}
                data-testid="portal-cat-cancel"
              >
                {t('actions.cancel')}
              </Button>
            }
            primary={
              <Button
                type="primary"
                size="large"
                htmlType="submit"
                disabled={!ready}
                loading={raise.isPending || files.sending}
                aria-describedby={why === null ? undefined : 'portal-cat-why'}
                data-testid="portal-cat-send"
              >
                {t('portal.catalog.send')}
              </Button>
            }
          />
        </Form>
      </FormCard>
    </Flex>
  );
}
