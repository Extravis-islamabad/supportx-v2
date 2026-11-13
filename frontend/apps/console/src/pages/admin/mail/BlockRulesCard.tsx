import { useQueryClient } from '@tanstack/react-query';
import { App, Flex, Input, List, Popconfirm, Select, Switch, Typography } from 'antd';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useAddMailBlockRule,
  useMailBlockRules,
  useRemoveMailBlockRule,
  useSwitchMailBlockRule,
  type MailBlockKind,
  type MailBlockRule,
} from '@supportx/api-client';
import { useTenantChannel } from '@supportx/realtime';
import {
  EmptyText,
  lengthLimit,
  markHandled,
  reportError,
  SettingsCard,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const KINDS: MailBlockKind[] = ['sender', 'domain', 'subject', 'body'];

/**
 * Block rules for unwanted mail (WP-046a S6; REQ-INC-026): a sender, a domain, or plain text in
 * the subject or body. Matching mail creates nothing and waits in each mailbox's review queue
 * as blocked, for its quarantine days. Live: `integrations.mail_block_rules_changed`.
 */
export function BlockRulesCard() {
  const t = useLabel();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const rules = useMailBlockRules();
  const add = useAddMailBlockRule();
  const toggle = useSwitchMailBlockRule();
  const remove = useRemoveMailBlockRule();
  const [kind, setKind] = useState<MailBlockKind>('domain');
  const [value, setValue] = useState('');
  const [problem, setProblem] = useState<{ key: string; params: ApiError['params'] }>();
  useTenantChannel((event) => {
    if (event.type === 'integrations.mail_block_rules_changed') {
      void queryClient.invalidateQueries({ queryKey: queryKeys.mailboxes.blockRules });
    }
  });

  const submit = () => {
    setProblem(undefined);
    add.mutate(
      { kind, value: value.trim(), key: crypto.randomUUID() },
      {
        onSuccess: () => {
          setValue('');
          void message.success(t('mail.block_rules.added'));
        },
        onError: (error: unknown) => {
          // Said at the field: a duplicate, or a value that is not an address or domain.
          if (error instanceof ApiError && (error.status === 422 || error.status === 409)) {
            markHandled(error);
            const field = error.fieldErrors[0];
            setProblem(
              field === undefined
                ? { key: `errors.${error.code}`, params: error.params }
                : { key: field.message_key, params: field.params ?? {} },
            );
            return;
          }
          reportError(error);
        },
      },
    );
  };

  return (
    <SettingsCard title={t('mail.block_rules.title')} testId="mail-block-rules">
      <Flex vertical gap={12}>
        <Typography.Text type="secondary">{t('mail.block_rules.intro')}</Typography.Text>
        <Flex gap={8} wrap align="start">
          <Select
            aria-label={t('mail.block_rules.kind')}
            style={{ minWidth: 180 }}
            value={kind}
            options={KINDS.map((code) => ({ value: code, label: t(`mail_block_kind.${code}`) }))}
            onChange={setKind}
            data-testid="mail-block-kind"
          />
          <Flex vertical style={{ flex: 1, minWidth: 200 }}>
            <Input
              aria-label={t('mail.block_rules.value')}
              value={value}
              count={lengthLimit(320)}
              status={problem === undefined ? undefined : 'error'}
              aria-describedby={problem === undefined ? undefined : 'mail-block-value-problem'}
              onChange={(event) => {
                setValue(event.target.value);
                setProblem(undefined);
              }}
              onPressEnter={submit}
              data-testid="mail-block-value"
            />
            {problem !== undefined && (
              <Typography.Text
                type="danger"
                role="alert"
                id="mail-block-value-problem"
                data-testid="mail-block-value-problem"
              >
                {t(problem.key, problem.params)}
              </Typography.Text>
            )}
          </Flex>
          <WriteButton
            type="primary"
            disabled={value.trim() === ''}
            loading={add.isPending}
            onClick={submit}
            data-testid="mail-block-add"
          >
            {t('mail.block_rules.add')}
          </WriteButton>
        </Flex>
        <List
          dataSource={rules.data ?? []}
          loading={rules.isLoading}
          locale={{ emptyText: <EmptyText>{t('mail.block_rules.none')}</EmptyText> }}
          renderItem={(rule: MailBlockRule) => (
            <List.Item
              data-testid={`mail-block-rule-${rule.value}`}
              actions={[
                <Switch
                  key="on"
                  checked={rule.enabled}
                  aria-label={t('mail.block_rules.enabled_for', { value: rule.value })}
                  loading={toggle.isPending && toggle.variables.id === rule.id}
                  onChange={(enabled) => {
                    toggle.mutate(
                      { id: rule.id, enabled, version: rule.version },
                      { onError: reportError },
                    );
                  }}
                  data-testid="mail-block-rule-enabled"
                />,
                <Popconfirm
                  key="remove"
                  title={t('mail.block_rules.remove_confirm', { value: rule.value })}
                  okText={t('mail.block_rules.remove')}
                  cancelText={t('actions.cancel')}
                  okButtonProps={{ danger: true }}
                  onConfirm={() => {
                    remove.mutate({ id: rule.id, version: rule.version }, { onError: reportError });
                  }}
                >
                  <WriteButton danger size="small" data-testid="mail-block-rule-remove">
                    {t('mail.block_rules.remove')}
                  </WriteButton>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  // Addresses and domains read left to right; subject and body text as written.
                  <Typography.Text
                    dir={rule.kind === 'sender' || rule.kind === 'domain' ? 'ltr' : 'auto'}
                  >
                    {rule.value}
                  </Typography.Text>
                }
                description={t(`mail_block_kind.${rule.kind}`)}
              />
            </List.Item>
          )}
        />
      </Flex>
    </SettingsCard>
  );
}
