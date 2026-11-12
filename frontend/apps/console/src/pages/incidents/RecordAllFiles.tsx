import { DownloadOutlined } from '@ant-design/icons';
import { Checkbox, Flex, List, Typography } from 'antd';
import { useState } from 'react';

import { downloadRecordArchive, useRecordFiles } from '@supportx/api-client';
import {
  EmptyText,
  FileStateTag,
  formatSize,
  reportError,
  useAppearance,
  useDateTime,
  useLabel,
  WriteButton,
} from '@supportx/ui';

// Every file of a record in one place (WP-046a S2; REQ-INC-080): its own, and those on its
// replies and notes, newest first; pick several and download them as one zip. Only what you
// may see is listed (the files API filters, lane B's rule), and the server checks each picked
// file again and lists any left out in the zip's manifest, by ID and reason only.

const MAX_PICK = 200;

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function RecordAllFiles({
  recordType,
  recordId,
}: {
  /** The files API's name of the record's type. */
  recordType: string;
  recordId: string;
}) {
  const t = useLabel();
  const dates = useDateTime();
  const { locale } = useAppearance();
  const found = useRecordFiles(recordType, recordId);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const files = [...(found.data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const openable = files.filter((f) => f.openable).map((f) => f.id);
  const chosen = picked.filter((id) => openable.includes(id));
  const all = openable.length > 0 && chosen.length === openable.length;
  const download = () => {
    setBusy(true);
    downloadRecordArchive(recordType, recordId, chosen, locale)
      .then(({ blob, name }) => {
        save(blob, name);
      })
      .catch(reportError)
      .finally(() => {
        setBusy(false);
      });
  };
  const where = (ownerType: string) =>
    t(ownerType === 'work_item' ? 'files.all.on_record' : 'files.all.on_conversation');
  return (
    <Flex vertical gap={12} data-testid="record-all-files">
      <Flex gap={12} align="center" wrap>
        <Checkbox
          checked={all}
          indeterminate={chosen.length > 0 && !all}
          disabled={openable.length === 0}
          onChange={(e) => {
            setPicked(e.target.checked ? openable.slice(0, MAX_PICK) : []);
          }}
          data-testid="all-files-select-all"
        >
          {t('files.all.select_all')}
        </Checkbox>
        <WriteButton
          icon={<DownloadOutlined />}
          onClick={download}
          loading={busy}
          disabled={chosen.length === 0}
          whyDisabled={t('files.all.why.pick')}
          data-testid="all-files-download"
        >
          {t('files.all.download', { count: chosen.length })}
        </WriteButton>
        {chosen.length >= MAX_PICK && (
          <Typography.Text type="secondary">
            {t('files.all.max', { max: MAX_PICK })}
          </Typography.Text>
        )}
      </Flex>
      <List
        dataSource={files}
        loading={found.isPending}
        locale={{ emptyText: <EmptyText>{t('files.empty')}</EmptyText> }}
        renderItem={(file) => (
          <List.Item key={file.id} data-testid={`all-file-${file.id}`}>
            <Checkbox
              checked={chosen.includes(file.id)}
              disabled={!file.openable || (!chosen.includes(file.id) && chosen.length >= MAX_PICK)}
              onChange={(e) => {
                setPicked((now) =>
                  e.target.checked ? [...now, file.id] : now.filter((id) => id !== file.id),
                );
              }}
              aria-label={t('files.all.pick', { name: file.name })}
            >
              <Flex vertical>
                <Typography.Text>{file.name}</Typography.Text>
                <Typography.Text type="secondary">
                  {`${formatSize(file.size, locale)} · ${where(file.owner_type)} · ${dates.format(
                    file.created_at,
                  )}`}
                </Typography.Text>
              </Flex>
            </Checkbox>
            {!file.openable && <FileStateTag state={file.state} />}
          </List.Item>
        )}
      />
    </Flex>
  );
}
