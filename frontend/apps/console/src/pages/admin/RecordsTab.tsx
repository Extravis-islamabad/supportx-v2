import {
  Alert,
  App,
  Button,
  Card,
  Flex,
  Form,
  Modal,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd';
import { useMemo, useState } from 'react';

import {
  ApiError,
  resourceAccessKeys,
  useAssetProductTypes,
  useCiTypes,
  useResourceCriteria,
  useResourceRules,
  useSaveResourceRule,
  useUnits,
  type AccessResource,
  type ResourceRule,
} from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { refreshList, useListChannel } from '@supportx/realtime';
import {
  FormProblem,
  useAccess,
  useAppearance,
  useFormProblem,
  useLabel,
  useLicence,
} from '@supportx/ui';
import { useQueryClient } from '@tanstack/react-query';

import { nameOf as ciName } from '../cmdb/names';
import { nameOf as productTypeName } from './assets/shared';

// ADR-053: which assets and CIs a role shows, narrow-only (D-172). A rule names what passes;
// every criterion it names must hold, a role's rules add up, and the server decides everything.

const RESOURCES: AccessResource[] = ['ci', 'asset'];
type Criteria = Record<string, string[] | string>;

interface Option {
  value: string;
  label: string;
}

/** Each criterion's choices, by key: types, sites, groups (ceilings come from the server). */
function useChoices(): Record<string, Option[]> {
  const t = useLabel();
  const { locale } = useAppearance();
  const { can } = useAccess();
  const ciTypes = useCiTypes();
  const productTypes = useAssetProductTypes();
  const sites = useUnits('sites', can('sites.view'));
  const groups = useUnits('groups', can('groups.view'));
  return useMemo(() => {
    const units = (found: readonly { id: string; name: string }[] | undefined): Option[] =>
      (found ?? []).map((u) => ({ value: u.id, label: u.name }));
    const groupOptions = units(groups.data);
    return {
      type_ids: (ciTypes.data?.items ?? []).map((x) => ({
        value: x.id,
        label: ciName(t, locale, x, 'cmdb_ci_type'),
      })),
      product_type_ids: (productTypes.data ?? []).map((x) => ({
        value: x.id,
        label: productTypeName(x.names, locale),
      })),
      site_ids: units(sites.data),
      owner_group_ids: groupOptions,
      managed_by_group_ids: groupOptions,
    };
  }, [ciTypes.data, productTypes.data, sites.data, groups.data, t, locale]);
}

export function RecordsTab({ roleId }: { roleId: string }) {
  const t = useLabel();
  const list = useListFormat();
  const { message, modal } = App.useApp();
  const { can } = useAccess();
  const licence = useLicence();
  const queryClient = useQueryClient();
  const criteria = useResourceCriteria();
  const rules = useResourceRules(roleId);
  const save = useSaveResourceRule(roleId);
  const problem = useFormProblem();
  const choices = useChoices();
  const [editing, setEditing] = useState<{ resource: AccessResource; rule?: ResourceRule }>();
  // Live: a rule set elsewhere (another admin, another tab) shows here at once.
  useListChannel(
    'resource_access',
    (m) => {
      if (m.covered !== true) refreshList(queryClient, resourceAccessKeys.all);
    },
    { covers: [resourceAccessKeys.all] },
  );
  const manage = can('roles.manage');
  // A lapsed plan keeps every rule applied; rules can only be viewed and removed (ADR-053 §5).
  const licensed = licence.has('fine_grained_access');

  const nameOfValue = (key: string, value: string): string =>
    choices[key]?.find((o) => o.value === value)?.label ?? t('resource_access.unknown_value');

  const remove = (rule: ResourceRule) => {
    modal.confirm({
      title: t('resource_access.remove_confirm'),
      okText: t('resource_access.remove'),
      okButtonProps: { danger: true },
      onOk: () =>
        save.mutateAsync(
          { resource: rule.resource, criteria: null, current: rule, key: crypto.randomUUID() },
          {
            onSuccess: () => {
              void message.success(t('resource_access.removed'));
            },
            onError: (error) => {
              problem.show(error);
            },
          },
        ),
    });
  };

  if (criteria.isPending || rules.isPending) return <Spin />;
  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Typography.Text type="secondary" data-testid="records-help">
        {t('resource_access.help')}
      </Typography.Text>
      <Typography.Text type="secondary">{t('resource_access.clearest_wins')}</Typography.Text>
      {!licensed && (
        <Alert
          type="info"
          showIcon
          role="status"
          message={t('resource_access.unlicensed')}
          data-testid="records-unlicensed"
        />
      )}
      <FormProblem problem={problem} />
      {RESOURCES.map((resource) => {
        const offered = criteria.data?.find((c) => c.resource === resource);
        if (offered === undefined) return null;
        const mine = (rules.data ?? []).filter((r) => r.resource === resource);
        return (
          <Card
            key={resource}
            size="small"
            title={t(`resource_access_resource.${resource}`)}
            data-testid={`records-${resource}`}
            extra={
              manage && licensed ? (
                <Button
                  size="small"
                  onClick={() => {
                    setEditing({ resource });
                  }}
                  data-testid={`records-add-${resource}`}
                >
                  {t('resource_access.add')}
                </Button>
              ) : undefined
            }
          >
            {mine.length === 0 ? (
              <Typography.Text type="secondary">{t('resource_access.none')}</Typography.Text>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {mine.map((rule) => (
                  <Flex
                    key={rule.id}
                    justify="space-between"
                    align="center"
                    gap={8}
                    wrap
                    data-testid={`records-rule-${rule.id}`}
                  >
                    <Flex gap={4} wrap>
                      {Object.entries(rule.criteria).map(([key, value]) => (
                        <Tag key={key}>
                          {t(`resource_access_criterion.${key}`)}:{' '}
                          <bdi>
                            {Array.isArray(value)
                              ? list(value.map((v) => nameOfValue(key, String(v))))
                              : t(`cmdb_impact.${String(value)}`)}
                          </bdi>
                        </Tag>
                      ))}
                    </Flex>
                    {manage && (
                      <Space>
                        {licensed && (
                          <Button
                            size="small"
                            onClick={() => {
                              setEditing({ resource, rule });
                            }}
                          >
                            {t('resource_access.edit')}
                          </Button>
                        )}
                        <Button
                          size="small"
                          danger
                          onClick={() => {
                            remove(rule);
                          }}
                          data-testid={`records-remove-${rule.id}`}
                        >
                          {t('resource_access.remove')}
                        </Button>
                      </Space>
                    )}
                  </Flex>
                ))}
              </Space>
            )}
          </Card>
        );
      })}
      {editing !== undefined && (
        <RuleDialog
          resource={editing.resource}
          rule={editing.rule}
          offered={(
            criteria.data?.find((c) => c.resource === editing.resource)?.criteria ?? []
          ).map((c) => ({ ...c, values: c.values ?? [] }))}
          choices={choices}
          onClose={() => {
            setEditing(undefined);
          }}
          onSave={(next) =>
            save.mutateAsync(
              {
                resource: editing.resource,
                criteria: next,
                current: editing.rule,
                key: crypto.randomUUID(),
              },
              {
                onSuccess: () => {
                  void message.success(t('resource_access.saved'));
                  setEditing(undefined);
                },
                onError: (error) => {
                  if (!(error instanceof ApiError && error.isConflict)) problem.show(error);
                },
              },
            )
          }
        />
      )}
    </Space>
  );
}

function RuleDialog({
  resource,
  rule,
  offered,
  choices,
  onClose,
  onSave,
}: {
  resource: AccessResource;
  rule: ResourceRule | undefined;
  offered: { key: string; kind: string; values: string[] }[];
  choices: Record<string, Option[]>;
  onClose: () => void;
  onSave: (criteria: Criteria) => Promise<unknown>;
}) {
  const t = useLabel();
  const [values, setValues] = useState<Criteria>(
    () => (rule?.criteria as Criteria | undefined) ?? {},
  );
  const named = Object.entries(values).filter(([, v]) =>
    Array.isArray(v) ? v.length > 0 : v !== '',
  );
  return (
    <Modal
      open
      title={t(rule === undefined ? 'resource_access.add_title' : 'resource_access.edit_title', {
        resource: t(`resource_access_resource.${resource}`),
      })}
      onCancel={onClose}
      okText={t('resource_access.save')}
      okButtonProps={{ disabled: named.length === 0 }}
      onOk={() => {
        void onSave(Object.fromEntries(named));
      }}
      data-testid="records-dialog"
    >
      <Typography.Paragraph type="secondary">
        {t('resource_access.all_must_hold')}
      </Typography.Paragraph>
      <Form layout="vertical" component="div">
        {offered.map((c) => (
          <Form.Item key={c.key} label={t(`resource_access_criterion.${c.key}`)}>
            {c.kind === 'ceiling' ? (
              <Select
                allowClear
                aria-label={t(`resource_access_criterion.${c.key}`)}
                value={typeof values[c.key] === 'string' ? (values[c.key] as string) : undefined}
                onChange={(next?: string) => {
                  setValues((v) => ({ ...v, [c.key]: next ?? '' }));
                }}
                options={c.values.map((code) => ({ value: code, label: t(`cmdb_impact.${code}`) }))}
                data-testid={`records-criterion-${c.key}`}
              />
            ) : (
              <Select
                mode="multiple"
                allowClear
                optionFilterProp="label"
                aria-label={t(`resource_access_criterion.${c.key}`)}
                value={Array.isArray(values[c.key]) ? (values[c.key] as string[]) : []}
                onChange={(next: string[]) => {
                  setValues((v) => ({ ...v, [c.key]: next }));
                }}
                options={choices[c.key] ?? []}
                data-testid={`records-criterion-${c.key}`}
              />
            )}
          </Form.Item>
        ))}
      </Form>
    </Modal>
  );
}
