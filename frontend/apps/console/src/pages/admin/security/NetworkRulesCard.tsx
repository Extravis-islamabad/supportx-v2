import { App, Button, Card, Flex, Input, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  useNetworkRules,
  useSaveNetworkRules,
  type NetworkRules,
  type NetworkRulesInput,
} from '@supportx/api-client';
import { FormProblem, markHandled, useFormProblem, useLabel, WriteButton } from '@supportx/ui';

import { FieldNote } from './FieldNote';

type ListField = keyof NetworkRulesInput;
const LISTS: ListField[] = ['console_ip_allow', 'portal_ip_allow', 'api_ip_allow'];
const MAX_ENTRIES = 50; // the server's cap (REQ-SEC-034; lane B's review)

/** One entry per line; blank lines dropped. */
function entries(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((line) => line.trim())
    .filter((line) => line !== '');
}

function draftFrom(saved: NetworkRules): Record<ListField, string> {
  return {
    console_ip_allow: saved.console_ip_allow.join('\n'),
    portal_ip_allow: saved.portal_ip_allow.join('\n'),
    api_ip_allow: saved.api_ip_allow.join('\n'),
  };
}

/**
 * IP allow-lists (WP-057 S1a, REQ-SEC-034): who may sign in to the console and the portal, and
 * call the API, by address. Empty = everyone. A list that would shut you out is refused (AC2),
 * so the card shows your address and offers to add it. Saving is audited; signed-in sessions
 * follow at their next refresh.
 */
export function NetworkRulesCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const rules = useNetworkRules();
  const save = useSaveNetworkRules();
  const [edited, setDraft] = useState<Record<ListField, string> | null>(null);
  const [refused, setRefused] = useState<Partial<Record<ListField, string>>>({});
  const problem = useFormProblem();
  if (rules.data === undefined) return <Card loading data-testid="security-network" />;
  const saved = rules.data;
  const draft = edited ?? draftFrom(saved);
  const typed: Partial<Record<ListField, string>> = {};
  for (const field of LISTS) {
    if (entries(draft[field]).length > MAX_ENTRIES) {
      typed[field] = t('errors.field.ip_allow_too_many', { max: MAX_ENTRIES });
    }
  }
  const shown = { ...refused, ...typed };
  const update = (field: ListField, text: string) => {
    setDraft({ ...draft, [field]: text });
    setRefused((current) => ({ ...current, [field]: undefined }));
  };
  const submit = () => {
    problem.clear();
    const body: NetworkRulesInput = {
      console_ip_allow: entries(draft.console_ip_allow),
      portal_ip_allow: entries(draft.portal_ip_allow),
      api_ip_allow: entries(draft.api_ip_allow),
    };
    save.mutate(
      { body, version: saved.version },
      {
        onSuccess: (next) => {
          setDraft(draftFrom(next));
          setRefused({});
          void message.success(t('security.network.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.status === 422 && error.fieldErrors.length > 0) {
            markHandled(error);
            setRefused(
              Object.fromEntries(
                error.fieldErrors.map((f) => [f.field, t(f.message_key, f.params ?? {})]),
              ),
            );
            return;
          }
          if (error instanceof ApiError && error.isConflict) {
            // Another admin saved first: their lists are fetched; yours stay to compare.
            markHandled(error);
            problem.show(error);
            return;
          }
          problem.show(error);
        },
      },
    );
  };
  const here = saved.your_address;
  return (
    <Card title={t('security.network.title')} data-testid="security-network">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.network.intro')}
        </Typography.Paragraph>
        {here !== null && (
          <Typography.Text data-testid="security-network-here">
            {t('security.network.your_address')}{' '}
            <Typography.Text code dir="ltr">
              {here}
            </Typography.Text>
          </Typography.Text>
        )}
        {LISTS.map((field) => (
          <FieldNote key={field} id={`security-${field}`} message={shown[field] ?? null}>
            <Flex justify="space-between" align="center" wrap gap={8}>
              <label htmlFor={`security-${field}`}>
                <Typography.Text strong>{t(`security.network.${field}`)}</Typography.Text>
              </label>
              {here !== null && !entries(draft[field]).includes(here) && (
                <Button
                  size="small"
                  type="link"
                  onClick={() => {
                    update(field, [...entries(draft[field]), here].join('\n'));
                  }}
                  data-testid={`security-${field}-add-here`}
                >
                  {t('security.network.add_here')}
                </Button>
              )}
            </Flex>
            <Input.TextArea
              id={`security-${field}`}
              dir="ltr"
              autoSize={{ minRows: 2, maxRows: 8 }}
              value={draft[field]}
              placeholder={t('security.network.placeholder')}
              onChange={(event) => {
                update(field, event.target.value);
              }}
              status={shown[field] ? 'error' : undefined}
              aria-describedby={`security-${field}-help security-${field}-problem`}
              data-testid={`security-${field}`}
            />
            <Typography.Text type="secondary" id={`security-${field}-help`}>
              {t(
                entries(draft[field]).length === 0
                  ? 'security.network.open'
                  : 'security.network.restricted',
                { count: entries(draft[field]).length },
              )}
            </Typography.Text>
          </FieldNote>
        ))}
        <div>
          <FormProblem problem={problem} />
          <WriteButton
            loading={save.isPending}
            disabled={Object.keys(typed).length > 0 || edited === null}
            onClick={submit}
            data-testid="security-network-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
      </Flex>
    </Card>
  );
}
