import { Tooltip } from 'antd';
import type { ReactNode } from 'react';

import type { Ci } from '@supportx/api-client';
import { useDateTime, useLabel } from '@supportx/ui';

/**
 * A CI attribute's label with where its value came from (REQ-CMDB-016 AC1): hovering or focusing
 * it shows the source and the time. The server sends a source only for fields the reader may
 * read (never a hidden, masked or sealed one), so a label without one is shown plain.
 */
export function SourceLabel({
  ci,
  field,
  children,
}: {
  ci: Ci;
  field: string;
  children: ReactNode;
}) {
  const t = useLabel();
  const dateTime = useDateTime();
  const stamp = ci.sources?.[field];
  if (stamp === undefined) return <>{children}</>;
  const text = t('cmdb.source.hint', {
    source: t(`cmdb_attribute_source.${stamp.source}`),
    at: dateTime.format(stamp.at),
  });
  return (
    <Tooltip title={text}>
      <span
        tabIndex={0}
        aria-label={`${typeof children === 'string' ? children : ''} ${text}`.trim()}
        data-testid={`ci-source-${field}`}
        style={{ textDecoration: 'underline dotted', textUnderlineOffset: 3, cursor: 'help' }}
      >
        {children}
      </span>
    </Tooltip>
  );
}
