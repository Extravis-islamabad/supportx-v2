import { App as AntApp } from 'antd';
import { useState } from 'react';

import { uploadFile } from '@supportx/api-client';
import { useLabel } from '@supportx/ui';

/**
 * Files chosen on a portal form, kept until the record exists and then sent to it (WP-022;
 * the server checks type, size and malware). WP-032 D4: the catalog item form uses it too.
 */
export function useFilesToAttach() {
  const t = useLabel();
  const { message } = AntApp.useApp();
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);
  const keep = (file: File) => {
    setFiles((all) => [...all, file]);
    return false;
  };
  const remove = (at: number) => {
    setFiles((all) => all.filter((_, i) => i !== at));
  };
  const attach = async (recordId: string) => {
    if (files.length === 0) return;
    setSending(true);
    const sent = await Promise.allSettled(
      files.map((file) => uploadFile(file, { ownerType: 'work_item', ownerId: recordId }).done),
    );
    setSending(false);
    const failed = sent.filter((r) => r.status === 'rejected').length;
    if (failed > 0) void message.warning(t('portal.report.files_failed', { count: failed }));
  };
  return { files, keep, remove, attach, sending };
}
