import { Button, DatePicker, Flex, Form, Input, InputNumber, List, Select, Typography } from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  useCatalogItem,
  useCatalogItems,
  useRaiseServiceRequest,
  useSession,
  type CatalogQuestion,
} from '@supportx/api-client';
import { lengthLimit, PageHeader, reportError, useAppearance, useLabel } from '@supportx/ui';

import { UserPicker } from '../incidents/pickers';
import { itemName } from './items';

const SUBJECT_MAX = 250;
const TEXT_MAX = 2000;

type Answers = Record<string, string | number | null>;

/** One form question, by its kind (REQ-SR-003). */
function Question({
  question,
  value,
  onChange,
  locale,
}: {
  question: CatalogQuestion;
  value: string | number | null;
  onChange: (value: string | number | null) => void;
  locale: string;
}) {
  const label = question.label[locale] ?? question.label.en ?? question.key;
  const id = `sr-q-${question.key}`;
  const common = { id, 'aria-label': label, 'data-testid': id };
  let input;
  if (question.kind === 'choice') {
    input = (
      <Select
        {...common}
        value={typeof value === 'string' ? value : undefined}
        onChange={(v: string) => {
          onChange(v);
        }}
        options={(question.options ?? []).map((o) => ({ value: o, label: o }))}
      />
    );
  } else if (question.kind === 'number') {
    input = (
      <InputNumber
        {...common}
        value={typeof value === 'number' ? value : null}
        onChange={(v) => {
          onChange(v);
        }}
      />
    );
  } else if (question.kind === 'date') {
    input = (
      <DatePicker
        {...common}
        onChange={(_, text) => {
          onChange(typeof text === 'string' && text !== '' ? text : null);
        }}
      />
    );
  } else if (question.kind === 'long_text') {
    input = (
      <Input.TextArea
        {...common}
        value={typeof value === 'string' ? value : ''}
        count={lengthLimit(TEXT_MAX)}
        autoSize={{ minRows: 3 }}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
    );
  } else {
    input = (
      <Input
        {...common}
        value={typeof value === 'string' ? value : ''}
        count={lengthLimit(TEXT_MAX)}
        onChange={(e) => {
          onChange(e.target.value);
        }}
      />
    );
  }
  return (
    <Form.Item label={label} htmlFor={id} required={question.required}>
      {input}
    </Form.Item>
  );
}

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
  const [answers, setAnswers] = useState<Answers>({});

  if (itemId === undefined || item.data === undefined) {
    const term = search.trim().toLocaleLowerCase(locale);
    const found = (items.data ?? []).filter(
      (i) =>
        i.enabled && (term === '' || itemName(i, locale).toLocaleLowerCase(locale).includes(term)),
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
  const missing = chosen.questions.some(
    (q) => q.required && (answers[q.key] == null || answers[q.key] === ''),
  );
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
          const given = Object.fromEntries(
            Object.entries(answers).filter(([, v]) => v !== null && v !== ''),
          );
          raise.mutate(
            {
              key,
              body: {
                subject: subject.trim(),
                requester_id: requester,
                catalog_item_id: chosen.id,
                answers: given,
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
        <Form.Item label={t('incidents.col.subject')} htmlFor="sr-subject" required>
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
        {chosen.questions.map((q) => (
          <Question
            key={q.key}
            question={q}
            locale={locale}
            value={answers[q.key] ?? null}
            onChange={(value) => {
              setAnswers((all) => ({ ...all, [q.key]: value }));
            }}
          />
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
