import { Select } from 'antd';
import { useState } from 'react';

import { useAssetPicker } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/**
 * The assets a request or issue is about (REQ-AST-025 AC1): only the person's own (or, when the
 * tenant allows, their department's) assets, as the picker offers them to requesters; a
 * requester never searches the organisation's assets. Asked once the list is opened.
 */
export function AssetsField({
  value,
  onChange,
  forUser,
  testId,
  id,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  forUser: string | null;
  testId: string;
  id?: string;
}) {
  const t = useLabel();
  const [opened, setOpened] = useState(false);
  const picker = useAssetPicker('', forUser, opened);
  return (
    <Select
      id={id}
      size="large"
      mode="multiple"
      allowClear
      value={value}
      onChange={onChange}
      onOpenChange={(open) => {
        if (open) setOpened(true);
      }}
      loading={picker.isFetching}
      placeholder={t('assets.link.portal_placeholder')}
      notFoundContent={picker.isFetching ? undefined : t('assets.link.none_held')}
      options={(picker.data ?? []).map((a) => {
        const label = [a.tag, a.name].filter(Boolean).join(' · ');
        return { value: a.id, label, 'aria-label': label };
      })}
      maxCount={20}
      style={{ width: '100%' }}
      data-testid={testId}
    />
  );
}
