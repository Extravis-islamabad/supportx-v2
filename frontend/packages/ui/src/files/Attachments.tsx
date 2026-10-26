import {
  CloseOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  FileOutlined,
  FilePdfOutlined,
  InboxOutlined,
  LockOutlined,
  RedoOutlined,
} from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Flex,
  List,
  Progress,
  Tag,
  Tooltip,
  Typography,
  Upload,
} from 'antd';
import { useState, type ClipboardEvent } from 'react';

import {
  fileImageUrl,
  fileLink,
  useDeleteFile,
  useFileRules,
  useRescanFile,
  type StoredFile,
  type UploadTarget,
} from '@supportx/api-client';

import { useAppearance, useLabel } from '../appearance';
import { reportError } from '../errors';
import { FilePreview } from './FilePreview';
import { FileStateTag } from './FileStateTag';
import { formatSize } from './format';
import { useUploads } from './useUploads';

export interface AttachmentsProps {
  /** The files to show (already filtered to this owner by the caller). */
  files: StoredFile[];
  /** Where new files go; null = no drop zone (no permission, or nothing to attach to yet). */
  target?: UploadTarget | null;
  /** Called after each file is stored (the caller refetches or keeps the ID, e.g. a draft). */
  onStored?: (file: StoredFile) => void;
  /** Called after a file was deleted here. */
  onRemoved?: (file: StoredFile) => void;
  /** Whether the user may remove files here. */
  canRemove?: boolean;
  /** Whether the user may ask for a file to be checked again (files.manage). */
  canRescan?: boolean;
  /** Marks the files as visible to staff only (a private note's). */
  staffOnly?: boolean;
  /** Smaller drop zone (inside a composer). */
  compact?: boolean;
  testId?: string;
}

function Icon({ file }: { file: StoredFile }) {
  if (file.has_thumbnail) {
    return (
      <img
        src={fileImageUrl(file.id, 'thumbnail')}
        alt=""
        width={48}
        height={48}
        style={{ objectFit: 'cover', borderRadius: 4 }}
      />
    );
  }
  const style = { fontSize: 32 };
  return file.kind === 'pdf' ? (
    <FilePdfOutlined style={style} aria-hidden />
  ) : (
    <FileOutlined style={style} aria-hidden />
  );
}

/**
 * Attachments of one owner (an incident, a reply, a note): the files with their scan state, and a
 * drop zone (drag and drop, the file picker, or paste) that refuses too-large and blocked files
 * before sending (REQ-INC-079 AC2), uploads several at once with progress, and shows each file's
 * state live ("Checking for malware" → "Ready", or "Blocked: malware found"). Files open only
 * when ready: previews for images and PDFs (AC4), downloads through short-lived links (AC3).
 */
export function Attachments({
  files,
  target = null,
  onStored,
  onRemoved,
  canRemove = false,
  canRescan = false,
  staffOnly = false,
  compact = false,
  testId = 'attachments',
}: AttachmentsProps) {
  const t = useLabel();
  const { locale } = useAppearance();
  const { modal, message } = AntApp.useApp();
  const rules = useFileRules();
  const remove = useDeleteFile();
  const rescan = useRescanFile();
  const [preview, setPreview] = useState<StoredFile | null>(null);
  const uploads = useUploads(target, rules.data, t, (stored) => {
    onStored?.(stored);
  });

  const download = async (file: StoredFile) => {
    try {
      window.location.assign(await fileLink(file.id, 'attachment'));
    } catch (error) {
      reportError(error);
    }
  };
  const confirmRemove = (file: StoredFile) => {
    modal.confirm({
      title: t('files.delete_confirm', { name: file.name }),
      okText: t('files.delete'),
      okButtonProps: { danger: true },
      cancelText: t('files.cancel'),
      onOk: async () => {
        await remove.mutateAsync(file.id);
        onRemoved?.(file);
        void message.success(t('files.deleted'));
      },
    });
  };
  const onPaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const pasted = Array.from(event.clipboardData.files);
    if (target === null || pasted.length === 0) return;
    event.preventDefault();
    uploads.add(pasted);
  };

  return (
    <Flex vertical gap={8} data-testid={testId} onPaste={onPaste}>
      {staffOnly && files.length > 0 && (
        <Tag icon={<LockOutlined />} style={{ alignSelf: 'flex-start' }}>
          {t('files.staff_only')}
        </Tag>
      )}
      {files.length > 0 && (
        <List
          size="small"
          dataSource={files}
          rowKey="id"
          renderItem={(file) => (
            <List.Item
              data-testid={`file-${file.id}`}
              actions={[
                file.previewable && (
                  <Tooltip title={t('files.preview')} key="preview">
                    <Button
                      type="text"
                      icon={<EyeOutlined />}
                      aria-label={`${t('files.preview')}: ${file.name}`}
                      onClick={() => {
                        setPreview(file);
                      }}
                    />
                  </Tooltip>
                ),
                file.openable && (
                  <Tooltip title={t('files.download')} key="download">
                    <Button
                      type="text"
                      icon={<DownloadOutlined />}
                      aria-label={`${t('files.download')}: ${file.name}`}
                      onClick={() => void download(file)}
                    />
                  </Tooltip>
                ),
                canRescan && (file.state === 'scan_failed' || file.state === 'not_scanned') && (
                  <Tooltip title={t('files.rescan')} key="rescan">
                    <Button
                      type="text"
                      icon={<RedoOutlined />}
                      aria-label={`${t('files.rescan')}: ${file.name}`}
                      onClick={() => {
                        rescan.mutate(file.id, { onError: reportError });
                      }}
                    />
                  </Tooltip>
                ),
                canRemove && (
                  <Tooltip title={t('files.delete')} key="delete">
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      aria-label={`${t('files.delete')}: ${file.name}`}
                      onClick={() => {
                        confirmRemove(file);
                      }}
                    />
                  </Tooltip>
                ),
              ].filter(Boolean)}
            >
              <List.Item.Meta
                avatar={<Icon file={file} />}
                title={<Typography.Text>{file.name}</Typography.Text>}
                description={
                  <Flex gap={8} align="center" wrap>
                    <Typography.Text type="secondary">
                      {formatSize(file.size, locale)}
                    </Typography.Text>
                    <FileStateTag state={file.state} />
                  </Flex>
                }
              />
            </List.Item>
          )}
        />
      )}
      {uploads.pending.map((item) => (
        <Flex
          key={item.key}
          align="center"
          gap={8}
          data-testid="file-upload-pending"
          aria-live="polite"
        >
          <Typography.Text style={{ flex: 1, minWidth: 0 }} ellipsis>
            {item.name}
          </Typography.Text>
          {item.error === null ? (
            <Progress
              percent={Math.round(item.progress * 100)}
              size="small"
              style={{ width: 160 }}
              aria-label={t('files.uploading', { name: item.name })}
            />
          ) : (
            <Typography.Text type="danger" role="alert">
              {item.error}
            </Typography.Text>
          )}
          <Button
            type="text"
            size="small"
            icon={<CloseOutlined />}
            aria-label={`${t('files.cancel')}: ${item.name}`}
            onClick={() => {
              uploads.dismiss(item.key);
            }}
          />
        </Flex>
      ))}
      {target !== null && (
        <div data-testid={`${testId}-drop`}>
          <Upload.Dragger
            multiple
            showUploadList={false}
            // We send the files ourselves (raw body, progress, the tenant's rules checked first).
            beforeUpload={(_file, list) => {
              if (_file === list[0]) uploads.add(list);
              return false;
            }}
            style={compact ? { padding: 4 } : undefined}
          >
            {!compact && (
              <p className="ant-upload-drag-icon">
                <InboxOutlined aria-hidden />
              </p>
            )}
            <p className="ant-upload-text">{t('files.drop')}</p>
            {rules.data !== undefined && (
              <p className="ant-upload-hint">
                {t('files.drop_hint', { limit: rules.data.max_file_mb })}
              </p>
            )}
          </Upload.Dragger>
        </div>
      )}
      <FilePreview
        file={preview}
        onClose={() => {
          setPreview(null);
        }}
      />
    </Flex>
  );
}
