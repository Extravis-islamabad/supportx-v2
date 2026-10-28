import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type Query,
} from '@tanstack/react-query';

import {
  API_BASE,
  CLIENT_HEADER,
  CSRF_HEADER,
  IDEMPOTENCY_HEADER,
  REQUEST_ID_HEADER,
  api,
  call,
  currentClientApp,
  currentCsrfToken,
  reportConnectivity,
} from './client';
import { ApiError, asProblem } from './errors';
import { queryKeys } from './keys';
import type { components } from './schema';

// Files and safe attachments (WP-022, ADR-028). Uploads send the raw file (no multipart) with
// progress; everything else goes through the typed client. Screens hear `files.changed` on the
// record channel (drafts: on the uploader's personal channel) and refetch through these hooks.
export type StoredFile = components['schemas']['FileOut'];
export type FileState = components['schemas']['FileState'];
export type FileOwnerType = components['schemas']['OwnerType'];
export type FileRules = components['schemas']['RulesOut'];
export type FileRulesInput = components['schemas']['RulesIn'];
export type FileUsage = components['schemas']['UsageOut'];
export type FileStatus = components['schemas']['StatusOut'];
export type FileDisposition = components['schemas']['Disposition'];

export interface UploadTarget {
  ownerType: FileOwnerType;
  ownerId: string;
  /** Pasted or dropped into an editor: shown inside the text. */
  inline?: boolean;
}

export interface UploadHandle {
  /** Resolves with the stored file (state `scanning` at first), or rejects with an ApiError. */
  done: Promise<StoredFile>;
  cancel: () => void;
}

/**
 * Upload one file with progress (0..1). XMLHttpRequest, because fetch cannot report upload
 * progress; the headers are the same conventions the typed client adds (CSRF, client, request
 * and idempotency IDs). The body is the file itself: the API streams it into encrypted storage.
 */
export function uploadFile(
  file: Blob & { name?: string },
  target: UploadTarget,
  onProgress?: (fraction: number) => void,
): UploadHandle {
  const request = new XMLHttpRequest();
  const params = new URLSearchParams({
    owner_type: target.ownerType,
    owner_id: target.ownerId,
    name: file.name ?? 'file',
  });
  if (target.inline === true) params.set('inline', 'true');
  const done = new Promise<StoredFile>((resolve, reject) => {
    request.open('POST', `${API_BASE}/files?${params.toString()}`);
    request.setRequestHeader('Accept', 'application/json');
    request.setRequestHeader(REQUEST_ID_HEADER, crypto.randomUUID());
    request.setRequestHeader(IDEMPOTENCY_HEADER, crypto.randomUUID());
    const app = currentClientApp();
    if (app !== null) request.setRequestHeader(CLIENT_HEADER, app);
    const csrf = currentCsrfToken();
    if (csrf !== null) request.setRequestHeader(CSRF_HEADER, csrf);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress !== undefined) {
        onProgress(event.loaded / event.total);
      }
    };
    request.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(request.responseText) as unknown;
      } catch {
        body = null;
      }
      if (request.status === 201) {
        reportConnectivity('online');
        resolve(body as StoredFile);
        return;
      }
      if ([502, 503, 504].includes(request.status)) reportConnectivity('offline');
      reject(
        new ApiError(request.status, asProblem(body), request.getResponseHeader(REQUEST_ID_HEADER)),
      );
    };
    request.onerror = () => {
      reportConnectivity('offline');
      reject(new ApiError(0, null, null, 'network'));
    };
    request.onabort = () => {
      reject(new ApiError(0, null, null, 'network'));
    };
    request.send(file);
  });
  return {
    done,
    cancel: () => {
      request.abort();
    },
  };
}

/** Every file on a record (its replies and notes too) the user may see. */
export function useRecordFiles(recordType: string, recordId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.files.record(recordType, recordId ?? ''),
    queryFn: () =>
      call(
        api.GET('/api/v1/files/records/{record_type}/{record_id}', {
          params: { path: { record_type: recordType, record_id: recordId ?? '' } },
        }),
      ),
    enabled: recordId !== undefined,
  });
}

/** One file (an editor draft waiting for its scan); poll with `refetchInterval` while checking. */
export function useFile(
  id: string | undefined,
  refetchInterval?: number | false | ((query: Query<StoredFile>) => number | false | undefined),
) {
  return useQuery({
    queryKey: queryKeys.files.detail(id ?? ''),
    queryFn: () =>
      call(api.GET('/api/v1/files/{file_id}', { params: { path: { file_id: id ?? '' } } })),
    enabled: id !== undefined,
    refetchInterval,
    meta: { silent: true },
  });
}

/** Several files by ID (a composer's draft files), each kept fresh like `useFile`. */
export function useFiles(ids: string[]): StoredFile[] {
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.files.detail(id),
      queryFn: () =>
        call(api.GET('/api/v1/files/{file_id}', { params: { path: { file_id: id } } })),
      refetchInterval: (query: Query<StoredFile>) =>
        query.state.data?.state === 'scanning' ? 2000 : false,
      meta: { silent: true },
    })),
    combine: (results) =>
      results.flatMap((result) => (result.data === undefined ? [] : [result.data])),
  });
}

/** A short-lived link (minutes, bound to the user): open it at once, never store it. */
export async function fileLink(id: string, disposition: FileDisposition): Promise<string> {
  const found = await call(
    api.POST('/api/v1/files/{file_id}/link', {
      params: { path: { file_id: id } },
      body: { disposition },
    }),
  );
  return found.url;
}

/** The image routes (session cookie; the API checks access): inline in text, and thumbnails. */
export function fileImageUrl(id: string, kind: 'inline' | 'thumbnail'): string {
  return `${API_BASE}/files/${id}/${kind}`;
}

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      call(api.DELETE('/api/v1/files/{file_id}', { params: { path: { file_id: id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.files.all });
    },
  });
}

/** Move editor drafts (pasted images, composer files) onto the entry or record just saved. */
export async function attachDrafts(
  ownerType: Exclude<FileOwnerType, 'draft'>,
  ownerId: string,
  fileIds: string[],
): Promise<string[]> {
  if (fileIds.length === 0) return [];
  return call(
    api.POST('/api/v1/files/attach', {
      body: { owner_type: ownerType, owner_id: ownerId, file_ids: fileIds },
    }),
  );
}

/** The tenant's rules: everyone reads them to refuse too-large or blocked files early (AC2). */
export function useFileRules() {
  return useQuery({
    queryKey: queryKeys.files.rules,
    queryFn: () => call(api.GET('/api/v1/files/settings/rules')),
    staleTime: 60_000,
  });
}

export function useUpdateFileRules() {
  const queryClient = useQueryClient();
  return useMutation({
    // The page says what went wrong (a conflict in the conflict dialog, the rest reported).
    meta: { silent: true },
    mutationFn: ({ body, version }: { body: FileRulesInput; version: number }) =>
      call(
        api.PUT('/api/v1/files/settings/rules', {
          params: { header: { 'If-Match': `"${String(version)}"` } },
          body,
        }),
      ),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.files.rules, saved);
    },
    onError: (error) => {
      // A stale save: fetch the saved rules, so the conflict dialog can compare (QA WP-029 BUG-05).
      if (error instanceof ApiError && error.isConflict) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.files.rules });
      }
    },
  });
}

export function useFileUsage(enabled = true) {
  return useQuery({
    queryKey: queryKeys.files.usage,
    queryFn: () => call(api.GET('/api/v1/files/settings/usage')),
    enabled,
  });
}

/** Scanning status (administrators): drives Admin › Files and the warning banner. */
export function useFileStatus(enabled = true) {
  return useQuery({
    queryKey: queryKeys.files.status,
    queryFn: () => call(api.GET('/api/v1/files/settings/status')),
    enabled,
    refetchInterval: 300_000,
    meta: { silent: true },
  });
}

export function useRescanFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      call(api.POST('/api/v1/files/{file_id}/rescan', { params: { path: { file_id: id } } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.files.all });
    },
  });
}
