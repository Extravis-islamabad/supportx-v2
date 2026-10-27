import { ApiError } from '@supportx/api-client';
import { DEFAULT_BRANDING } from '@supportx/ui';

// Checks the branding screen runs as soon as something is typed or chosen (WP-017-FIX BUG-02,
// BUG-03, BUG-09), mirroring the server's rules so a refusal shows at the field before any
// request. The server still decides: what it refuses is shown at the same field.

/** `#rrggbb` or `#rgb` in any case as `#rrggbb`; null when it is not a colour (branding.py). */
export function normaliseHex(value: string): string | null {
  let text = value.trim().toLowerCase();
  if (/^#[0-9a-f]{3}$/.test(text)) {
    text = `#${text.slice(1).replace(/./g, (ch) => ch + ch)}`;
  }
  return /^#[0-9a-f]{6}$/.test(text) ? text : null;
}

/**
 * The colours a save makes, by the server's rule (service/branding.py): the own gradient, else
 * the chosen primary at both ends, else the SupportX default (BUG-01: the preview shows these).
 */
export function coloursToSave(
  primary: string | null,
  gradient: [string, string] | null,
): { primary: string; gradient: [string, string] } {
  const chosen = primary === null ? null : normaliseHex(primary);
  const ends =
    gradient === null ? null : ([normaliseHex(gradient[0]), normaliseHex(gradient[1])] as const);
  return {
    primary: chosen ?? DEFAULT_BRANDING.colorPrimary,
    gradient:
      ends?.[0] != null && ends[1] != null
        ? [ends[0], ends[1]]
        : chosen === null
          ? [DEFAULT_BRANDING.gradient[0], DEFAULT_BRANDING.gradient[1]]
          : [chosen, chosen],
  };
}

const LABEL = '[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?'; // domains.py _LABEL
const HOST = new RegExp(`^${LABEL}(\\.${LABEL})+$`);
const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;

/** The code the server would refuse a typed domain with, as far as the browser can tell. */
export function domainProblem(value: string): string | null {
  const host = value.trim().toLowerCase().replace(/\.$/, '');
  if (host === '') return null;
  if (/^https?:\/\//.test(host) || host.includes('/') || host.includes(':')) {
    return 'domain_invalid';
  }
  if (IPV4.test(host) || host.length > 253 || !HOST.test(host)) return 'domain_invalid';
  return null;
}

/** PEM blocks the certificate dialog accepts (the server checks the rest: key, host, dates). */
export function pemProblem(kind: 'certificate' | 'private_key', value: string): string | null {
  const text = value.trim();
  if (text === '') return null;
  const block =
    kind === 'certificate'
      ? /-----BEGIN CERTIFICATE-----[\s\S]+-----END CERTIFICATE-----/
      : /-----BEGIN (RSA |EC )?PRIVATE KEY-----[\s\S]+-----END (RSA |EC )?PRIVATE KEY-----/;
  return block.test(text) ? null : `${kind}_unreadable`;
}

// The limits of infra/brand_images.py.
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_PIXELS = 25_000_000;
const MIN_SIDE = 16;

function startsWith(bytes: Uint8Array, signature: number[], offset = 0): boolean {
  return signature.every((value, i) => bytes[offset + i] === value);
}

/** PNG, JPEG, WebP or ICO by their first bytes (never by the name or the browser's type). */
function imageKind(bytes: Uint8Array): 'image' | 'svg' | null {
  if (
    startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) ||
    startsWith(bytes, [0xff, 0xd8, 0xff]) ||
    (startsWith(bytes, [0x52, 0x49, 0x46, 0x46]) &&
      startsWith(bytes, [0x57, 0x45, 0x42, 0x50], 8)) ||
    startsWith(bytes, [0x00, 0x00, 0x01, 0x00])
  ) {
    return 'image';
  }
  const text = new TextDecoder().decode(bytes).trimStart().toLowerCase();
  return text.startsWith('<?xml') || text.startsWith('<svg') || text.includes('<svg')
    ? 'svg'
    : null;
}

async function head(file: Blob, length: number): Promise<Uint8Array> {
  const part = file.slice(0, length);
  const buffer =
    typeof part.arrayBuffer === 'function'
      ? await part.arrayBuffer()
      : await new Response(part).arrayBuffer();
  return new Uint8Array(buffer);
}

/** The picture's size as the browser decodes it; null when it cannot be decoded. */
async function decodedSize(file: Blob): Promise<{ width: number; height: number } | null> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return { width: image.naturalWidth, height: image.naturalHeight };
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * Why a chosen brand image cannot be used (an `errors.field.<code>` code), or null. SVG is
 * refused (D-090: it can carry scripts and there is no sanitiser); the type is read from the
 * file's own bytes; the browser must decode it, within the server's size limits.
 */
export async function brandImageProblem(file: Blob): Promise<string | null> {
  if (file.size > MAX_BYTES) return 'brand_image_too_large';
  const kind = imageKind(await head(file, 512));
  if (kind === 'svg') return 'brand_image_svg';
  if (kind === null) return 'brand_image_unreadable';
  const size = await decodedSize(file);
  if (size === null || size.width === 0 || size.height === 0) return 'brand_image_unreadable';
  if (size.width * size.height > MAX_PIXELS) return 'brand_image_too_large';
  if (Math.min(size.width, size.height) < MIN_SIDE) return 'brand_image_too_small';
  return null;
}

export type Problems = Record<string, { key: string; params: Record<string, string | number> }[]>;

/** A refusal's field problems by the field's path (`host`, `portal_name.en`; no `body.`). */
export function fieldProblems(error: unknown): Problems {
  const found: Problems = {};
  if (!(error instanceof ApiError) || error.status !== 422) return found;
  for (const problem of error.fieldErrors) {
    const params: Record<string, string | number> = {};
    for (const [name, value] of Object.entries(problem.params ?? {})) {
      if (typeof value === 'string' || typeof value === 'number') params[name] = value;
    }
    (found[problem.field.replace(/^body\./, '')] ??= []).push({ key: problem.message_key, params });
  }
  return found;
}
