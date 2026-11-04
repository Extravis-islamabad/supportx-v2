import { Radio, Select, Space } from 'antd';
import { useState } from 'react';

import { usePortalOnBehalfPeople } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/**
 * "For me" or "for someone else" (WP-030, REQ-SR-011). The search lists only the people the
 * tenant's scope lets this person report for, by name (the server decides; a stranger is
 * never offered and is refused if sent anyway).
 */
export function ForWhom({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (person: string | null) => void;
}) {
  const t = useLabel();
  const [other, setOther] = useState(value !== null);
  const [search, setSearch] = useState('');
  const found = usePortalOnBehalfPeople(search);
  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Radio.Group
        value={other ? 'other' : 'me'}
        onChange={(e) => {
          const next = e.target.value === 'other';
          setOther(next);
          if (!next) onChange(null);
        }}
        data-testid="portal-for-whom"
      >
        <Radio value="me">{t('portal.report.for_me')}</Radio>
        <Radio value="other">{t('portal.report.for_someone_else')}</Radio>
      </Radio.Group>
      {other && (
        <Select
          showSearch
          allowClear
          value={value ?? undefined}
          placeholder={t('portal.report.search_person')}
          aria-label={t('portal.report.search_person')}
          filterOption={false}
          onSearch={setSearch}
          onChange={(person: string | undefined) => {
            onChange(person ?? null);
          }}
          notFoundContent={search.trim().length < 2 ? t('portal.report.type_two') : undefined}
          loading={found.isFetching}
          options={(found.data ?? []).map((p) => ({ value: p.id, label: p.display_name }))}
          data-testid="portal-on-behalf"
        />
      )}
    </Space>
  );
}
