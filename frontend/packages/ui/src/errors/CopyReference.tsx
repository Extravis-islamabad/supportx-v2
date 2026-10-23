import { CopyOutlined } from '@ant-design/icons';
import { App, Button } from 'antd';

import { useLabel } from '../appearance';

/** Copies the support reference (request ID) of a failed action to the clipboard. */
export function CopyReference({ reference }: { reference: string }) {
  const t = useLabel();
  const { message } = App.useApp();
  return (
    <Button
      size="small"
      icon={<CopyOutlined />}
      data-reference={reference}
      onClick={() => {
        navigator.clipboard.writeText(reference).then(
          () => void message.success(t('errors.reference_copied')),
          () => void message.info(t('errors.reference_is', { reference })),
        );
      }}
    >
      {t('errors.copy_reference')}
    </Button>
  );
}
