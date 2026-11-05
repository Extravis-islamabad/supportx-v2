import { CameraOutlined, CloseOutlined, PaperClipOutlined } from '@ant-design/icons';
import { Button, Flex, Space, Typography, Upload } from 'antd';

import { useLabel } from '@supportx/ui';

/** The chosen files with "add files" and "take a photo" (phones open the camera). */
export function AttachFiles({
  files,
  keep,
  remove,
  testId,
}: {
  files: File[];
  keep: (file: File) => boolean;
  remove: (at: number) => void;
  testId: string;
}) {
  const t = useLabel();
  return (
    <Flex vertical gap={8}>
      {files.map((file, at) => (
        <Flex key={`${file.name}-${String(at)}`} align="center" gap={8}>
          <Typography.Text ellipsis style={{ flex: 1, minWidth: 0 }}>
            {file.name}
          </Typography.Text>
          <Button
            type="text"
            icon={<CloseOutlined />}
            aria-label={t('portal.report.remove_file', { name: file.name })}
            onClick={() => {
              remove(at);
            }}
          />
        </Flex>
      ))}
      <Space wrap>
        <Upload multiple showUploadList={false} beforeUpload={keep}>
          <Button size="large" icon={<PaperClipOutlined />} data-testid={`${testId}-files`}>
            {t('portal.report.add_files')}
          </Button>
        </Upload>
        <Upload accept="image/*" capture="environment" showUploadList={false} beforeUpload={keep}>
          <Button size="large" icon={<CameraOutlined />} data-testid={`${testId}-camera`}>
            {t('files.take_photo')}
          </Button>
        </Upload>
      </Space>
    </Flex>
  );
}
