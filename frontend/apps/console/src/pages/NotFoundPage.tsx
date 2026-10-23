import { Button, Result } from 'antd';
import { useNavigate } from 'react-router';

import { useLabel } from '@supportx/ui';

export function NotFoundPage() {
  const t = useLabel();
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title={<h1 style={{ fontSize: 'inherit', margin: 0 }}>{t('shell.not_found')}</h1>}
      subTitle={t('shell.not_found_body')}
      extra={
        <Button type="primary" onClick={() => void navigate('/')}>
          {t('shell.go_home')}
        </Button>
      }
    />
  );
}
