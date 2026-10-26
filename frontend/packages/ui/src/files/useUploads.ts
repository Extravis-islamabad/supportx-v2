import { useEffect, useState } from 'react';

import {
  uploadFile,
  type FileRules,
  type StoredFile,
  type UploadHandle,
  type UploadTarget,
} from '@supportx/api-client';
import type { LabelInput, LabelParams } from '@supportx/labels';

import { describeError } from '../errors';
import { extensionOf } from './format';

/** At most this many uploads run at once; the rest wait their turn. */
export const PARALLEL_UPLOADS = 3;
const MB = 1_000_000;

export interface PendingUpload {
  key: string;
  name: string;
  size: number;
  /** 0..1 while sending. */
  progress: number;
  /** Translated reason when it was refused (here or by the server). */
  error: string | null;
}

type Translate = (key: LabelInput, params?: LabelParams) => string;

/** Why a file is refused before sending (AC2: refused before upload, with the limit), or null. */
export function refusal(file: File, rules: FileRules | undefined, t: Translate): string | null {
  if (rules === undefined) return null;
  if (file.size > rules.max_file_mb * MB) {
    return t('files.too_large_local', { name: file.name, limit: rules.max_file_mb });
  }
  const extension = extensionOf(file.name);
  if (extension !== '' && rules.blocked_extensions.includes(extension)) {
    return t('files.blocked_local', { name: file.name, extension });
  }
  return null;
}

interface Settings {
  target: UploadTarget | null;
  rules: FileRules | undefined;
  t: Translate;
  onStored: (file: StoredFile) => void;
}

type Change = (update: (items: PendingUpload[]) => PendingUpload[]) => void;

/** One drop zone's queue: what waits, what runs, and what each upload is doing. */
class UploadQueue {
  private waiting: { key: string; file: File }[] = [];
  private readonly running = new Map<string, UploadHandle>();
  private settings: Settings | null = null;

  constructor(private readonly change: Change) {}

  /** The zone's current target, rules, language and callback (set after every render). */
  configure(settings: Settings): void {
    this.settings = settings;
  }

  add(files: File[]): void {
    const settings = this.settings;
    if (settings === null) return;
    const batch = settings.rules?.max_batch ?? 20;
    const added = files.map((file, index) => {
      const key = crypto.randomUUID();
      const error =
        index >= batch
          ? settings.t('files.too_many', { max: batch })
          : refusal(file, settings.rules, settings.t);
      if (error === null) this.waiting.push({ key, file });
      return { key, name: file.name, size: file.size, progress: 0, error };
    });
    this.change((items) => [...items, ...added]);
    this.pump();
  }

  dismiss(key: string): void {
    this.running.get(key)?.cancel();
    this.waiting = this.waiting.filter((item) => item.key !== key);
    this.change((items) => items.filter((item) => item.key !== key));
  }

  stop(): void {
    for (const handle of this.running.values()) handle.cancel();
  }

  private update(key: string, values: Partial<PendingUpload>): void {
    this.change((items) => items.map((item) => (item.key === key ? { ...item, ...values } : item)));
  }

  private pump(): void {
    while (this.running.size < PARALLEL_UPLOADS && this.waiting.length > 0) {
      const next = this.waiting.shift();
      const target = this.settings?.target ?? null;
      if (next === undefined || target === null) return;
      const handle = uploadFile(next.file, target, (fraction) => {
        this.update(next.key, { progress: fraction });
      });
      this.running.set(next.key, handle);
      handle.done
        .then((stored) => {
          this.change((items) => items.filter((item) => item.key !== next.key));
          this.settings?.onStored(stored);
        })
        .catch((error: unknown) => {
          const t = this.settings?.t;
          if (t !== undefined) this.update(next.key, { error: describeError(error, t).title });
        })
        .finally(() => {
          this.running.delete(next.key);
          this.pump();
        });
    }
  }
}

/**
 * The upload queue of one drop zone: refuses what the rules forbid before sending, sends at most
 * PARALLEL_UPLOADS at a time with progress, and reports each stored file. Failed and refused files
 * stay listed with their reason until dismissed.
 */
export function useUploads(
  target: UploadTarget | null,
  rules: FileRules | undefined,
  t: Translate,
  onStored: (file: StoredFile) => void,
) {
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [queue] = useState(() => new UploadQueue(setPending));
  useEffect(() => {
    queue.configure({ target, rules, t, onStored });
  });
  useEffect(
    () => () => {
      queue.stop();
    },
    [queue],
  );
  return {
    pending,
    add: (files: File[]) => {
      queue.add(files);
    },
    dismiss: (key: string) => {
      queue.dismiss(key);
    },
  };
}
