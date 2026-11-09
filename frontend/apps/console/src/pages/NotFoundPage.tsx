import { CompassOutlined } from '@ant-design/icons';
import { Button, Result, theme } from 'antd';
import { useNavigate } from 'react-router';

import { useLabel } from '@supportx/ui';

export function NotFoundPage() {
  const t = useLabel();
  const navigate = useNavigate();
  const { token } = theme.useToken();
  // An icon in the theme's colours, not Ant Design's 404 picture, which is drawn for light
  // backgrounds only (QA9-V-03).
  return (
    <Result
      icon={<CompassOutlined aria-hidden style={{ fontSize: 72, color: token.colorPrimary }} />}
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
