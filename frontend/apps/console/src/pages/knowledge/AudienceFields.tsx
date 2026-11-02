import { Form, Radio, Select, Space } from 'antd';
import { useStructure, useUnits } from '@supportx/api-client';
import { useListFormat } from '@supportx/labels';
import { useLabel } from '@supportx/ui';

import { useUnitNames } from './audience';
import { audienceWords, type Audience } from './model';

/** "Technicians: Network group · Requesters: Riyadh site" (REQ-KB-078). */
export function AudienceSummary({ audience, testId }: { audience: Audience; testId?: string }) {
  const t = useLabel();
  const list = useListFormat();
  const units = useUnitNames();
  const words = audienceWords(audience, units, t, list);
  return (
    <Space direction="vertical" size={0} data-testid={testId}>
      <span>
        {t('knowledge.audience.technicians')}: {words.technicians}
      </span>
      <span>
        {t('knowledge.audience.requesters')}: {words.requesters}
      </span>
    </Space>
  );
}

/** Audience inputs inside an Ant Design form (names prefixed by `prefix`). */
export function AudienceFields({ prefix = [] }: { prefix?: string[] }) {
  const t = useLabel();
  const groups = useUnits('groups');
  const sites = useUnits('sites');
  const departments = useStructure('departments', true, true);
  const form = Form.useFormInstance();
  const techAll = Form.useWatch([...prefix, 'tech_all'], form) as boolean | undefined;
  const requesters = Form.useWatch([...prefix, 'requesters'], form) as string | undefined;
  const options = (rows: { id: string; name: string }[] | undefined) =>
    (rows ?? []).map((row) => ({ value: row.id, label: row.name }));
  return (
    <>
      <Form.Item label={t('knowledge.audience.technicians')} name={[...prefix, 'tech_all']}>
        <Radio.Group
          options={[
            { value: true, label: t('knowledge.audience.all_technicians') },
            { value: false, label: t('knowledge.audience.chosen_groups') },
          ]}
          data-testid="kb-tech-all"
        />
      </Form.Item>
      {techAll === false && (
        <Form.Item
          label={t('knowledge.audience.groups_label')}
          name={[...prefix, 'tech_groups']}
          rules={[{ required: true, message: t('errors.field.technician_audience_empty') }]}
        >
          <Select
            mode="multiple"
            optionFilterProp="label"
            options={options(groups.data)}
            data-testid="kb-tech-groups"
          />
        </Form.Item>
      )}
      <Form.Item label={t('knowledge.audience.requesters')} name={[...prefix, 'requesters']}>
        <Radio.Group
          options={(['none', 'all', 'selected'] as const).map((value) => ({
            value,
            label: t(`kb_requesters.${value}`),
          }))}
          data-testid="kb-requesters"
        />
      </Form.Item>
      {requesters === 'selected' && (
        <>
          <Form.Item label={t('knowledge.audience.req_groups')} name={[...prefix, 'req_groups']}>
            <Select mode="multiple" optionFilterProp="label" options={options(groups.data)} />
          </Form.Item>
          <Form.Item label={t('knowledge.audience.req_sites')} name={[...prefix, 'req_sites']}>
            <Select mode="multiple" optionFilterProp="label" options={options(sites.data)} />
          </Form.Item>
          <Form.Item
            label={t('knowledge.audience.req_departments')}
            name={[...prefix, 'req_departments']}
          >
            <Select
              mode="multiple"
              optionFilterProp="label"
              options={options(departments.data?.filter((d) => !d.disabled))}
            />
          </Form.Item>
        </>
      )}
    </>
  );
}
