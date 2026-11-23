import { Alert, App, Card, Flex, Segmented, Switch, Table, Tag, Typography } from 'antd';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  ApiError,
  queryKeys,
  useSaveSsoPolicy,
  useSession,
  useSetBreakGlass,
  useSsoPolicy,
  type SsoPolicy,
  type SsoRequired,
  type TenantAdmin,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import {
  FormProblem,
  markHandled,
  reportError,
  useFormProblem,
  useLabel,
  WriteButton,
} from '@supportx/ui';

const MODES: SsoRequired[] = ['off', 'technicians', 'everyone'];

interface Draft {
  sso_required: SsoRequired;
  sso_also_require_mfa: boolean;
}

const draftFrom = (saved: SsoPolicy): Draft => ({
  sso_required: saved.sso_required,
  sso_also_require_mfa: saved.sso_also_require_mfa,
});

/**
 * Single sign-on required (WP-057 S1b; REQ-SEC-009, REQ-SEC-026): for nobody, technicians or
 * everyone, and whether SupportX asks its own two-step code after single sign-on. Requiring it
 * needs an emergency (break-glass) administrator: another tenant admin with two-step sign-in,
 * who keeps a password for when the identity provider fails. Every emergency sign-in alerts the
 * other admins. Changes another admin makes show here without a reload.
 */
export function SsoPolicyCard() {
  const t = useLabel();
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const policy = useSsoPolicy();
  const save = useSaveSsoPolicy();
  const setBreakGlass = useSetBreakGlass();
  const me = useSession().data?.user.id;
  const [edited, setDraft] = useState<Draft | null>(null);
  const problem = useFormProblem();
  // A person's marks change on their user record: the users channel says so (rule 5c).
  useListChannel('users', () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.identity.ssoPolicy });
  });
  if (policy.data === undefined) return <Card loading data-testid="security-sso-policy" />;
  const saved = policy.data;
  const draft = edited ?? draftFrom(saved);
  const changed =
    draft.sso_required !== saved.sso_required ||
    draft.sso_also_require_mfa !== saved.sso_also_require_mfa;
  const submit = () => {
    problem.clear();
    save.mutate(
      { body: draft, version: saved.version },
      {
        onSuccess: (next) => {
          setDraft(draftFrom(next));
          void message.success(t('security.sso_policy.saved'));
        },
        onError: (error) => {
          if (error instanceof ApiError && error.isConflict) markHandled(error);
          problem.show(error); // the reason in words: no emergency admin, or saved by someone else
        },
      },
    );
  };
  const mark = (admin: TenantAdmin, breakGlass: boolean, ipExempt: boolean) => {
    const run = () => {
      setBreakGlass.mutate(
        {
          userId: admin.user_id,
          body: { break_glass: breakGlass, break_glass_ip_exempt: breakGlass && ipExempt },
          version: admin.version,
        },
        {
          onSuccess: () => {
            void message.success(
              t('security.sso_policy.admin_saved', { name: admin.display_name }),
            );
          },
          onError: reportError,
        },
      );
    };
    if (breakGlass && !admin.break_glass) {
      // Naming someone who may bypass single sign-on is asked first.
      modal.confirm({
        title: t('security.sso_policy.confirm_title', { name: admin.display_name }),
        content: t('security.sso_policy.confirm_body'),
        okText: t('security.sso_policy.confirm_ok'),
        cancelText: t('actions.cancel'),
        onOk: run,
      });
      return;
    }
    run();
  };
  const reason = (admin: TenantAdmin): string | null => {
    if (admin.user_id === me) return t('security.sso_policy.not_yourself');
    if (!admin.mfa_enrolled && !admin.break_glass) return t('security.sso_policy.needs_mfa');
    return null;
  };
  return (
    <Card title={t('security.sso_policy.title')} data-testid="security-sso-policy">
      <Flex vertical gap={16}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          {t('security.sso_policy.intro')}
        </Typography.Paragraph>
        <Flex vertical gap={8}>
          <Typography.Text strong id="security-sso-required-label">
            {t('security.sso_policy.required')}
          </Typography.Text>
          <Segmented<SsoRequired>
            value={draft.sso_required}
            aria-labelledby="security-sso-required-label"
            data-testid="security-sso-required"
            options={MODES.map((value) => ({ value, label: t(`sso_required_mode.${value}`) }))}
            onChange={(value) => {
              setDraft({ ...draft, sso_required: value });
            }}
          />
          {draft.sso_required !== 'off' && (
            <Alert
              type="info"
              showIcon
              message={t(`security.sso_policy.effect_${draft.sso_required}`)}
              data-testid="security-sso-required-effect"
            />
          )}
        </Flex>
        <Flex gap={12} align="start">
          <Switch
            id="security-sso-also-mfa"
            checked={draft.sso_also_require_mfa}
            onChange={(checked) => {
              setDraft({ ...draft, sso_also_require_mfa: checked });
            }}
            aria-describedby="security-sso-also-mfa-help"
            data-testid="security-sso-also-mfa"
          />
          <Flex vertical>
            <label htmlFor="security-sso-also-mfa">
              <Typography.Text>{t('security.sso_policy.also_mfa')}</Typography.Text>
            </label>
            <Typography.Text type="secondary" id="security-sso-also-mfa-help">
              {t('security.sso_policy.also_mfa_help')}
            </Typography.Text>
          </Flex>
        </Flex>
        <div>
          <FormProblem problem={problem} />
          <WriteButton
            loading={save.isPending}
            disabled={!changed}
            onClick={submit}
            data-testid="security-sso-policy-save"
          >
            {t('actions.save')}
          </WriteButton>
        </div>
        <Flex vertical gap={8}>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {t('security.sso_policy.admins_title')}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t('security.sso_policy.admins_intro', { count: saved.break_glass_admins })}
          </Typography.Text>
          <Table<TenantAdmin>
            rowKey="user_id"
            size="small"
            pagination={false}
            scroll={{ x: true }}
            dataSource={saved.admins}
            data-testid="security-break-glass-admins"
            locale={{ emptyText: t('security.sso_policy.no_admins') }}
            columns={[
              {
                key: 'name',
                title: t('security.sso_policy.admin'),
                render: (_, admin) => admin.display_name,
              },
              {
                key: 'mfa',
                title: t('security.sso_policy.mfa'),
                render: (_, admin) =>
                  admin.mfa_enrolled ? (
                    <Tag color="success">{t('security.sso_policy.mfa_on')}</Tag>
                  ) : (
                    <Tag>{t('security.sso_policy.mfa_off')}</Tag>
                  ),
              },
              {
                key: 'break_glass',
                title: t('security.sso_policy.break_glass'),
                render: (_, admin) => {
                  const why = reason(admin);
                  return (
                    <Flex vertical gap={2}>
                      <Switch
                        size="small"
                        checked={admin.break_glass}
                        disabled={why !== null || setBreakGlass.isPending}
                        aria-label={t('security.sso_policy.break_glass_for', {
                          name: admin.display_name,
                        })}
                        data-testid={`security-break-glass-${admin.user_id}`}
                        onChange={(checked) => {
                          mark(admin, checked, admin.break_glass_ip_exempt);
                        }}
                      />
                      {why !== null && <Typography.Text type="secondary">{why}</Typography.Text>}
                    </Flex>
                  );
                },
              },
              {
                key: 'ip_exempt',
                title: t('security.sso_policy.ip_exempt'),
                render: (_, admin) => (
                  <Switch
                    size="small"
                    checked={admin.break_glass_ip_exempt}
                    disabled={!admin.break_glass || admin.user_id === me || setBreakGlass.isPending}
                    aria-label={t('security.sso_policy.ip_exempt_for', {
                      name: admin.display_name,
                    })}
                    data-testid={`security-break-glass-ip-${admin.user_id}`}
                    onChange={(checked) => {
                      mark(admin, true, checked);
                    }}
                  />
                ),
              },
            ]}
          />
        </Flex>
      </Flex>
    </Card>
  );
}
