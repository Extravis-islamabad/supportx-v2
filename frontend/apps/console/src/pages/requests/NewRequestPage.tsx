import { Button, Flex, Form, Input, List, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  useCatalogItem,
  useCatalogItems,
  useRaiseServiceRequest,
  useSession,
} from '@supportx/api-client';
import {
  lengthLimit,
  PageHeader,
  QuestionField,
  reportError,
  requesterQuestions,
  sentAnswers,
  startingAnswers,
  textIn,
  useAppearance,
  useLabel,
  type QuestionValue,
} from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { itemName } from './items';

const SUBJECT_MAX = 250;

/**
 * Raise a service request from the catalog (WP-030, REQ-SR-010): search the items the technician
 * may raise (technician-only items included), then the item's form with the requester picked.
 * The item decides the status, priority and group on the server; one Idempotency-Key per form.
 */
export function NewRequestPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const itemId = params.get('item') ?? undefined;
  const items = useCatalogItems();
  const item = useCatalogItem(itemId);
  const me = useSession().data?.user.id ?? null;
  const raise = useRaiseServiceRequest();
  const key = useMemo(() => crypto.randomUUID(), []);
  const [search, setSearch] = useState('');
  const [subject, setSubject] = useState('');
  const [requester, setRequester] = useState<string | null>(me);
  const [answers, setAnswers] = useState<Record<string, QuestionValue> | null>(null);

  if (itemId === undefined || item.data === undefined) {
    const term = search.trim().toLocaleLowerCase(locale);
    const found = (items.data ?? []).filter(
      (i) =>
        // Only what can be raised now: published service items (WP-031 plan D3, D10).
        i.status === 'published' &&
        i.kind === 'service' &&
        (term === '' || itemName(i, locale).toLocaleLowerCase(locale).includes(term)),
    );
    return (
      <Flex vertical gap={16}>
        <PageHeader
          title={t('requests.new')}
          back={{ label: t('nav.requests'), onClick: () => void navigate('/requests') }}
        />
        <Input.Search
          allowClear
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder={t('requests.search_catalog')}
          aria-label={t('requests.search_catalog')}
          data-testid="sr-catalog-search"
          style={{ maxWidth: 420 }}
        />
        <List
          loading={items.isLoading}
          dataSource={found}
          data-testid="sr-catalog"
          renderItem={(i) => (
            <List.Item key={i.id}>
              <Button
                type="link"
                onClick={() => {
                  setParams({ item: i.id });
                }}
                data-testid={`sr-item-${i.id}`}
              >
                {itemName(i, locale)}
              </Button>
              {i.audience === 'technicians' && (
                <Typography.Text type="secondary">
                  {t('catalog_item_audience.technicians')}
                </Typography.Text>
              )}
            </List.Item>
          )}
        />
      </Flex>
    );
  }

  const chosen = item.data;
  // The questions the requester answers (a technician raises it as them, WP-031 plan D6).
  const questions = requesterQuestions(chosen.questions);
  const shown = answers ?? startingAnswers(questions);
  const missing = questions.some((q) => {
    const value = shown[q.key];
    return (
      q.required && (value == null || value === '' || (Array.isArray(value) && value.length === 0))
    );
  });
  const ready = subject.trim() !== '' && requester !== null && !missing;
  return (
    <Flex vertical gap={16} style={{ maxWidth: 760 }}>
      <PageHeader
        title={itemName(chosen, locale)}
        back={{
          label: t('requests.back_to_catalog'),
          onClick: () => {
            setParams({});
          },
        }}
      />
      <Form
        layout="vertical"
        onFinish={() => {
          if (!ready) return;
          raise.mutate(
            {
              key,
              body: {
                subject: subject.trim(),
                requester_id: requester,
                catalog_item_id: chosen.id,
                answers: sentAnswers(shown),
                confirm_lose_access: false,
              },
            },
            {
              onSuccess: (made) => void navigate(`/requests/${made.id}`, { replace: true }),
              onError: reportError,
            },
          );
        }}
      >
        <Form.Item label={t('work_item.field.subject')} htmlFor="sr-subject" required>
          <Input
            id="sr-subject"
            value={subject}
            count={lengthLimit(SUBJECT_MAX)}
            onChange={(e) => {
              setSubject(e.target.value);
            }}
            data-testid="sr-subject"
          />
        </Form.Item>
        <Form.Item label={t('requests.requested_for')} htmlFor="sr-requester" required>
          <UserPicker
            id="sr-requester"
            value={requester}
            onChange={setRequester}
            testId="sr-requester"
            ariaLabel={t('requests.requested_for')}
          />
        </Form.Item>
        {questions.map((q) => (
          <Form.Item
            key={q.key}
            label={textIn(q.label, locale) || q.key}
            extra={textIn(q.help, locale) || undefined}
            htmlFor={`sr-q-${q.key}`}
            required={q.required}
          >
            <QuestionField
              question={q}
              value={shown[q.key] ?? null}
              onChange={(value) => {
                setAnswers({ ...shown, [q.key]: value });
              }}
              locale={locale}
              renderPerson={({ id, value, onChange, disabled }) => (
                <UserPicker
                  id={id}
                  value={value}
                  onChange={onChange}
                  disabled={disabled}
                  testId={id}
                  ariaLabel={textIn(q.label, locale) || q.key}
                />
              )}
            />
          </Form.Item>
        ))}
        <Button
          type="primary"
          htmlType="submit"
          disabled={!ready}
          loading={raise.isPending}
          data-testid="sr-send"
        >
          {t('requests.send')}
        </Button>
        <Link to="/requests" style={{ marginInlineStart: 12 }}>
          {t('actions.cancel')}
        </Link>
      </Form>
    </Flex>
  );
}
