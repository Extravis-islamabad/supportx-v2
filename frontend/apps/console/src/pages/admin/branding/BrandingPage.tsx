import {
  Alert,
  App,
  Button,
  Card,
  Col,
  ColorPicker,
  Flex,
  Input,
  Modal,
  Row,
  Space,
  Switch,
  Tabs,
  Typography,
} from 'antd';
import { useEffect, useMemo, useState } from 'react';

import {
  uploadFile,
  useBrandingColourCheck,
  useBrandingSettings,
  useFile,
  useSaveBranding,
  useSession,
  type BrandingInput,
  type BrandingSettings,
} from '@supportx/api-client';
import type { Locale } from '@supportx/labels';
import {
  ConflictDialog,
  FormProblem,
  lengthLimit,
  markHandled,
  reportError,
  SUPPORTX_LOGOS,
  ToneTag,
  useConflict,
  useFormProblem,
  useLabel,
  WriteButton,
  type Branding,
} from '@supportx/ui';

import { useDebounced } from '../../../useDebounced';
import { BrandPreview } from './BrandPreview';
import {
  brandImageProblem,
  coloursToSave,
  fieldProblems,
  normaliseHex,
  type Problems,
} from './checks';
import { DomainsCard } from './DomainsCard';
import { FieldProblem } from './FieldProblem';

const LOCALES: Locale[] = ['en', 'ar', 'ur'];
const TEXT_FIELDS = ['product_name', 'portal_name', 'welcome_text'] as const;
type TextField = (typeof TEXT_FIELDS)[number];
type Texts = Record<TextField, Partial<Record<Locale, string>>>;
const IMAGE_FIELDS = ['logo_file_id', 'logo_dark_file_id', 'icon_file_id'] as const;
type ImageField = (typeof IMAGE_FIELDS)[number];
const ACCEPT = 'image/png,image/jpeg,image/webp,image/x-icon,image/vnd.microsoft.icon';
const LIMITS: Record<TextField, number> = { product_name: 60, portal_name: 60, welcome_text: 500 };
/** What each image card stands for while nothing is uploaded (QA BUG-06: shown, not named). */
const DEFAULT_IMAGES: Record<ImageField, string | undefined> = {
  logo_file_id: SUPPORTX_LOGOS.full,
  logo_dark_file_id: SUPPORTX_LOGOS.fullOnDark,
  icon_file_id: SUPPORTX_LOGOS.icon,
};

interface Draft {
  primary: string | null;
  gradient: [string, string] | null;
  texts: Texts;
  images: Record<ImageField, string | null>;
}

/** A just-chosen image: shown from the browser until saved, uploaded and scanned meanwhile. */
interface Picked {
  fileId: string | null;
  previewUrl: string;
  failed: boolean;
}

function draftFrom(settings: BrandingSettings): Draft {
  return {
    primary: settings.chosen_primary_colour ?? null,
    gradient:
      settings.chosen_gradient == null
        ? null
        : [settings.chosen_gradient[0] ?? '', settings.chosen_gradient[1] ?? ''],
    texts: {
      product_name: settings.product_name,
      portal_name: settings.portal_name,
      welcome_text: settings.welcome_text,
    },
    images: {
      logo_file_id: settings.logo_file_id ?? null,
      logo_dark_file_id: settings.logo_dark_file_id ?? null,
      icon_file_id: settings.icon_file_id ?? null,
    },
  };
}

/** The branding as a person sees it, flat, for the conflict dialog (QA WP-029 BUG-05). */
function brandingView(settings: BrandingSettings | undefined): object | undefined {
  if (settings === undefined) return undefined;
  const { primary, gradient, texts, images } = draftFrom(settings);
  return { primary, gradient, ...texts, ...images };
}

/** A branding setting in words. */
function brandingPart(t: ReturnType<typeof useLabel>, field: string): string {
  if (field === 'primary') return t('branding.primary');
  if (field === 'gradient') return t('branding.own_gradient');
  if ((TEXT_FIELDS as readonly string[]).includes(field)) return t(`branding.text.${field}`);
  return t(`branding.image.${field}`);
}

/** Server problems each edit makes obsolete (field paths of the last save's refusal). */
const PROBLEM_FIELDS: Record<keyof Draft, (path: string) => boolean> = {
  primary: (path) => path === 'primary_colour',
  gradient: (path) => path === 'gradient',
  texts: (path) => TEXT_FIELDS.some((field) => path.startsWith(`${field}.`)),
  images: (path) => (IMAGE_FIELDS as readonly string[]).includes(path),
};

function bodyFrom(draft: Draft): BrandingInput {
  return {
    primary_colour: draft.primary === null ? null : (normaliseHex(draft.primary) ?? draft.primary),
    gradient: draft.gradient,
    product_name: draft.texts.product_name,
    portal_name: draft.texts.portal_name,
    welcome_text: draft.texts.welcome_text,
    ...draft.images,
  };
}

/** Waits for the scan of one upload; reports its state up. */
function ScanWatcher({
  fileId,
  onState,
}: {
  fileId: string;
  onState: (state: string | undefined) => void;
}) {
  const file = useFile(fileId, (query) => (query.state.data?.state === 'scanning' ? 1500 : false));
  const state = file.data?.state;
  useEffect(() => {
    onState(state);
  }, [state, onState]);
  return null;
}

/**
 * Admin › Branding (WP-017, REQ-ADM-055, REQ-PRT-016): the tenant's logo, icon, colours, product
 * and portal names and welcome text. Colours are checked against WCAG AA as they are chosen (the
 * server decides; a failing colour cannot be saved and the nearest passing one is offered), and a
 * preview shows the console, portal and sign-in page in light, dark and high contrast before
 * saving. Saved changes reach every open screen without a reload; saving is audited.
 */
export function BrandingPage() {
  const t = useLabel();
  const { message } = App.useApp();
  const tenantId = useSession().data?.tenant.id ?? '';
  const settings = useBrandingSettings();
  const save = useSaveBranding();
  // Edits start from what is saved; until the first edit the saved values are the draft.
  const [edited, setDraft] = useState<Draft | null>(null);
  const draft = edited ?? (settings.data === undefined ? null : draftFrom(settings.data));
  const [picked, setPicked] = useState<Partial<Record<ImageField, Picked>>>({});
  const [scans, setScans] = useState<Record<string, string | undefined>>({});
  // Refusals: of the last save, by field path (server), and of chosen images (on selection).
  const [problems, setProblems] = useState<Problems>({});
  const [imageProblems, setImageProblems] = useState<Partial<Record<ImageField, string>>>({});
  // A refusal with no field to point at (a rule, a limit) is shown above Save (QA WP-029 BUG-02).
  const problem = useFormProblem();
  // A save another admin beat (409): the shared dialog says who, when and what (BUG-05); the
  // branding as it was when the edit began, and the save it stopped (to send again).
  const conflict = useConflict();
  const [opened, setOpened] = useState<BrandingSettings>();
  const [stopped, setStopped] = useState<{ body: BrandingInput; after: string }>();

  // A typed colour that is not one is said at once and never sent to the check (QA BUG-03).
  const primaryInvalid = draft?.primary != null && normaliseHex(draft.primary) === null;
  const primary = useDebounced(
    draft?.primary == null || primaryInvalid ? null : normaliseHex(draft.primary),
  );
  const gradient = useDebounced(draft?.gradient ?? null);
  const check = useBrandingColourCheck(primary, gradient, draft !== null && !primaryInvalid);
  const report = primaryInvalid ? undefined : check.data;

  const candidate = useMemo<Partial<Branding>>(() => {
    const saved = settings.data;
    if (draft === null || saved === undefined) return {};
    const logos = saved.logos;
    const url = (field: ImageField, savedUrl: string | null | undefined) =>
      picked[field]?.previewUrl ??
      (draft.images[field] === null ? undefined : (savedUrl ?? undefined));
    const full = url('logo_file_id', logos.full);
    // Exactly what a save makes (QA BUG-01), never the colours saved before.
    const colours = coloursToSave(draft.primary, draft.gradient);
    return {
      colorPrimary: colours.primary,
      gradient: colours.gradient,
      texts: {
        productName: draft.texts.product_name,
        portalName: draft.texts.portal_name,
        welcomeText: draft.texts.welcome_text,
      },
      ...(full === undefined
        ? {}
        : {
            logos: {
              full,
              fullOnDark: url('logo_dark_file_id', logos.full_on_dark) ?? full,
              fullHighContrast:
                picked.logo_file_id === undefined ? (logos.full_high_contrast ?? full) : full,
              icon: url('icon_file_id', logos.icon),
            },
          }),
    };
  }, [draft, picked, settings.data]);

  if (settings.data === undefined || draft === null) {
    return <Card loading data-testid="admin-branding" />;
  }
  const version = settings.data.version;
  const update = (change: Partial<Draft>) => {
    if (edited === null) setOpened(settings.data);
    setDraft({ ...draft, ...change });
    const changed = Object.keys(change) as (keyof Draft)[];
    setProblems((current) =>
      Object.fromEntries(
        Object.entries(current).filter(
          ([path]) => !changed.some((key) => PROBLEM_FIELDS[key](path)),
        ),
      ),
    );
  };
  const problemAt = (path: string): string | null => {
    const found = problems[path];
    return found === undefined ? null : found.map((p) => t(p.key, p.params)).join(' ');
  };
  const scanning = Object.values(picked).some(
    (item) => item.fileId !== null && (scans[item.fileId] ?? 'scanning') === 'scanning',
  );
  const blocked = Object.values(picked).some(
    (item) =>
      item.failed ||
      (item.fileId !== null && ['infected', 'scan_failed'].includes(scans[item.fileId] ?? '')),
  );
  const colourFails = report !== undefined && !report.passes;

  const choose = async (field: ImageField, file: File) => {
    // Type, size and real image content are checked on selection (QA BUG-09): a refused file
    // is never uploaded, and what was there stays.
    const problem = await brandImageProblem(file);
    setImageProblems((current) => ({ ...current, [field]: problem ?? undefined }));
    if (problem !== null) return;
    const previewUrl = URL.createObjectURL(file);
    setPicked((current) => ({ ...current, [field]: { fileId: null, previewUrl, failed: false } }));
    uploadFile(file, { ownerType: 'branding', ownerId: tenantId })
      .done.then((stored) => {
        setPicked((current) => ({
          ...current,
          [field]: { fileId: stored.id, previewUrl, failed: false },
        }));
        setDraft((current) => {
          const base = current ?? draft;
          return { ...base, images: { ...base.images, [field]: stored.id } };
        });
      })
      .catch((error: unknown) => {
        setPicked((current) => ({
          ...current,
          [field]: { fileId: null, previewUrl, failed: true },
        }));
        reportError(error);
      });
  };
  const removeImage = (field: ImageField) => {
    // Without a logo there is nothing to pair a dark version or an icon with (the API agrees),
    // so their uploads go too, waiting ones included (QA BUG-07).
    const gone: string[] =
      field === 'logo_file_id' ? ['logo_file_id', 'logo_dark_file_id', 'icon_file_id'] : [field];
    const keep = <T,>(record: Partial<Record<ImageField, T>>) =>
      Object.fromEntries(Object.entries(record).filter(([key]) => !gone.includes(key)));
    setPicked(keep);
    setImageProblems(keep);
    update({ images: { ...draft.images, ...Object.fromEntries(gone.map((key) => [key, null])) } });
  };

  const submit = (body: BrandingInput, after: string, at = version) => {
    problem.clear();
    const shown = settings.data;
    save.mutate(
      { body, version: at },
      {
        onSuccess: (saved) => {
          setDraft(draftFrom(saved));
          setPicked({});
          setProblems({});
          void message.success(t(after));
        },
        // A refusal says why at its fields (QA BUG-03); anything else is reported.
        onError: (error) => {
          if (conflict.take(error)) {
            // A save with no edits (reset) compares with the branding shown when it was made.
            setOpened((was) => was ?? shown);
            setStopped({ body, after });
            return;
          }
          const found = fieldProblems(error);
          if (Object.keys(found).length === 0) problem.show(error);
          else markHandled(error);
          setProblems(found);
        },
      },
    );
  };

  const imageCard = (field: ImageField) => {
    const current = picked[field];
    const savedUrl =
      field === 'logo_file_id'
        ? settings.data.logos.full
        : field === 'logo_dark_file_id'
          ? settings.data.logos.full_on_dark
          : settings.data.logos.icon;
    const shown = current?.previewUrl ?? (draft.images[field] === null ? null : (savedUrl ?? null));
    const disabled = field !== 'logo_file_id' && draft.images.logo_file_id === null;
    const state = current?.fileId == null ? undefined : scans[current.fileId];
    const refusal = imageProblems[field];
    const refused = refusal === undefined ? problemAt(field) : t(`errors.field.${refusal}`);
    return (
      <Card size="small" title={t(`branding.image.${field}`)} data-testid={`branding-${field}`}>
        <Flex vertical gap={8}>
          <Typography.Text type="secondary">{t(`branding.image.${field}_hint`)}</Typography.Text>
          <div
            style={{
              minHeight: 64,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: field === 'logo_dark_file_id' ? '#141414' : 'transparent',
              borderRadius: 6,
              padding: 8,
            }}
          >
            {shown === null ? (
              <img
                src={DEFAULT_IMAGES[field]}
                alt={t('branding.image.default')}
                style={{ maxHeight: field === 'icon_file_id' ? 48 : 32, maxWidth: '100%' }}
              />
            ) : (
              <img
                src={shown}
                alt={t(`branding.image.${field}`)}
                style={{ maxHeight: 64, maxWidth: '100%' }}
              />
            )}
          </div>
          {shown === null && (
            <Typography.Text type="secondary">{t('branding.image.default')}</Typography.Text>
          )}
          {refused !== null && (
            <Typography.Text type="danger" role="alert">
              {refused}
            </Typography.Text>
          )}
          {current !== undefined && (
            <Typography.Text type={current.failed ? 'danger' : 'secondary'} role="status">
              {t(
                current.failed
                  ? 'branding.image.upload_failed'
                  : current.fileId === null
                    ? 'branding.image.uploading'
                    : (state ?? 'scanning') === 'scanning'
                      ? 'branding.image.scanning'
                      : state === 'infected' || state === 'scan_failed'
                        ? 'branding.image.blocked'
                        : 'branding.image.ready',
              )}
            </Typography.Text>
          )}
          <Space wrap>
            <Button disabled={disabled} data-testid={`branding-${field}-choose`}>
              <label style={{ cursor: disabled ? 'not-allowed' : 'pointer' }}>
                {t('branding.image.choose')}
                <input
                  type="file"
                  accept={ACCEPT}
                  hidden
                  disabled={disabled}
                  data-testid={`branding-${field}-input`}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file !== undefined) void choose(field, file);
                    event.target.value = '';
                  }}
                />
              </label>
            </Button>
            {shown !== null && (
              <Button
                onClick={() => {
                  removeImage(field);
                }}
                data-testid={`branding-${field}-remove`}
              >
                {t('branding.image.remove')}
              </Button>
            )}
          </Space>
        </Flex>
      </Card>
    );
  };

  return (
    <Flex vertical gap={16} data-testid="admin-branding">
      {Object.values(picked).map(
        (item) =>
          item.fileId !== null && (
            <ScanWatcher
              key={item.fileId}
              fileId={item.fileId}
              onState={(state) => {
                const id = item.fileId ?? '';
                setScans((current) =>
                  current[id] === state ? current : { ...current, [id]: state },
                );
              }}
            />
          ),
      )}
      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
        {t('branding.intro')}
      </Typography.Paragraph>
      <Row gutter={[16, 16]}>
        <Col xs={24} xl={12}>
          <Flex vertical gap={16}>
            <Card title={t('branding.colours')}>
              <Flex vertical gap={12}>
                <Flex gap={12} align="center" wrap>
                  <Typography.Text id="branding-primary-label">
                    {t('branding.primary')}
                  </Typography.Text>
                  <ColorPicker
                    value={
                      (draft.primary === null ? null : normaliseHex(draft.primary)) ??
                      settings.data.primary_colour
                    }
                    disabledAlpha
                    format="hex"
                    onChangeComplete={(colour) => {
                      update({ primary: colour.toHexString() });
                    }}
                    aria-labelledby="branding-primary-label"
                    data-testid="branding-primary"
                  />
                  <FieldProblem
                    testId="branding-primary-field"
                    id="branding-primary-problem"
                    message={
                      primaryInvalid
                        ? t('errors.field.invalid_colour')
                        : problemAt('primary_colour')
                    }
                  >
                    <Input
                      value={draft.primary ?? ''}
                      placeholder={settings.data.primary_colour}
                      onChange={(event) => {
                        update({ primary: event.target.value === '' ? null : event.target.value });
                      }}
                      count={lengthLimit(7)}
                      status={primaryInvalid || 'primary_colour' in problems ? 'error' : undefined}
                      aria-invalid={primaryInvalid || 'primary_colour' in problems}
                      aria-describedby="branding-primary-problem"
                      style={{ width: 120 }}
                      aria-label={t('branding.primary')}
                      data-testid="branding-primary-input"
                    />
                  </FieldProblem>
                  {draft.primary !== null && (
                    <Button
                      type="link"
                      onClick={() => {
                        update({ primary: null, gradient: null });
                      }}
                    >
                      {t('branding.use_default')}
                    </Button>
                  )}
                </Flex>
                <Flex gap={12} align="center" wrap>
                  <Switch
                    checked={draft.gradient !== null}
                    onChange={(on) => {
                      update({
                        gradient: on
                          ? [
                              settings.data.gradient[0] ?? '#000000',
                              settings.data.gradient[1] ?? '#000000',
                            ]
                          : null,
                      });
                    }}
                    aria-label={t('branding.own_gradient')}
                    data-testid="branding-gradient-switch"
                  />
                  <Typography.Text>{t('branding.own_gradient')}</Typography.Text>
                  {draft.gradient !== null &&
                    ([0, 1] as const).map((end) => (
                      <ColorPicker
                        key={end}
                        value={draft.gradient?.[end]}
                        disabledAlpha
                        format="hex"
                        onChangeComplete={(colour) => {
                          const next: [string, string] = [...(draft.gradient ?? ['', ''])];
                          next[end] = colour.toHexString();
                          update({ gradient: next });
                        }}
                        aria-label={t(
                          end === 0 ? 'branding.gradient_start' : 'branding.gradient_end',
                        )}
                      />
                    ))}
                </Flex>
                {'gradient' in problems && (
                  <Typography.Text type="danger" role="alert">
                    {problemAt('gradient')}
                  </Typography.Text>
                )}
                <Typography.Text type="secondary">{t('branding.gradient_hint')}</Typography.Text>
                {report !== undefined && (
                  <ul
                    aria-label={t('branding.checks')}
                    style={{ margin: 0, paddingInlineStart: 0, listStyle: 'none' }}
                    data-testid="branding-checks"
                  >
                    {report.checks.map((item) => (
                      <li key={item.code} style={{ marginBlock: 4 }}>
                        <ToneTag tone={item.passed ? 'success' : 'error'}>
                          {t(item.passed ? 'branding.check_passed' : 'branding.check_failed')}
                        </ToneTag>
                        {t(`branding.check.${item.code}`)}{' '}
                        <Typography.Text type="secondary">
                          {t('branding.ratio', {
                            ratio: item.ratio.toFixed(2),
                            required: item.required.toFixed(1),
                          })}
                        </Typography.Text>
                      </li>
                    ))}
                  </ul>
                )}
                {colourFails && (
                  <Alert
                    type="error"
                    showIcon
                    message={t('errors.brand_colour_contrast')}
                    data-testid="branding-contrast-alert"
                    action={
                      <Space direction="vertical">
                        {report.suggested_primary != null && (
                          <Button
                            size="small"
                            onClick={() => {
                              update({ primary: report.suggested_primary ?? null });
                            }}
                            data-testid="branding-use-suggested"
                          >
                            {t('branding.use_suggested', { colour: report.suggested_primary })}
                          </Button>
                        )}
                        {report.suggested_gradient != null && (
                          <Button
                            size="small"
                            onClick={() => {
                              update({
                                gradient: [
                                  report.suggested_gradient?.[0] ?? '',
                                  report.suggested_gradient?.[1] ?? '',
                                ],
                              });
                            }}
                            data-testid="branding-use-suggested-gradient"
                          >
                            {t('branding.use_suggested_gradient')}
                          </Button>
                        )}
                      </Space>
                    }
                  />
                )}
              </Flex>
            </Card>
            <Card title={t('branding.images')}>
              <Row gutter={[12, 12]}>
                {IMAGE_FIELDS.map((field) => (
                  <Col key={field} xs={24} md={8}>
                    {imageCard(field)}
                  </Col>
                ))}
              </Row>
            </Card>
            <Card title={t('branding.texts')}>
              <Tabs
                items={LOCALES.map((locale) => ({
                  key: locale,
                  label: t(`locale.${locale}`),
                  children: (
                    <Flex vertical gap={12} dir={locale === 'en' ? 'ltr' : 'rtl'}>
                      {TEXT_FIELDS.map((field) => {
                        const value = draft.texts[field][locale] ?? '';
                        const set = (text: string) => {
                          update({
                            texts: {
                              ...draft.texts,
                              [field]: { ...draft.texts[field], [locale]: text },
                            },
                          });
                        };
                        const id = `branding-${field}-${locale}`;
                        const problem = problemAt(`${field}.${locale}`);
                        return (
                          <FieldProblem
                            key={field}
                            testId={`${id}-field`}
                            id={`${id}-problem`}
                            message={problem}
                          >
                            <Flex vertical gap={4}>
                              <label htmlFor={id}>{t(`branding.text.${field}`)}</label>
                              {field === 'welcome_text' ? (
                                <Input.TextArea
                                  id={id}
                                  value={value}
                                  count={lengthLimit(LIMITS[field], true)}
                                  status={problem === null ? undefined : 'error'}
                                  aria-describedby={`${id}-problem`}
                                  autoSize={{ minRows: 2, maxRows: 5 }}
                                  onChange={(event) => {
                                    set(event.target.value);
                                  }}
                                  data-testid={id}
                                />
                              ) : (
                                <Input
                                  id={id}
                                  value={value}
                                  count={lengthLimit(LIMITS[field])}
                                  status={problem === null ? undefined : 'error'}
                                  aria-describedby={`${id}-problem`}
                                  onChange={(event) => {
                                    set(event.target.value);
                                  }}
                                  data-testid={id}
                                />
                              )}
                            </Flex>
                          </FieldProblem>
                        );
                      })}
                      {locale === 'en' && (
                        <Typography.Text type="secondary">
                          {t('branding.text.english_hint')}
                        </Typography.Text>
                      )}
                    </Flex>
                  ),
                }))}
              />
            </Card>
            <FormProblem problem={problem} />
            <Flex gap={8} wrap>
              <WriteButton
                type="primary"
                loading={save.isPending}
                disabled={colourFails || primaryInvalid || scanning || blocked || check.isFetching}
                onClick={() => {
                  submit(bodyFrom(draft), 'branding.saved');
                }}
                data-testid="branding-save"
              >
                {t('branding.save')}
              </WriteButton>
              <WriteButton
                disabled={!settings.data.customised && version === 0}
                onClick={() =>
                  Modal.confirm({
                    title: t('branding.reset_title'),
                    content: t('branding.reset_body'),
                    okText: t('branding.reset'),
                    cancelText: t('actions.cancel'),
                    onOk: () => {
                      submit(
                        {
                          primary_colour: null,
                          gradient: null,
                          product_name: {},
                          portal_name: {},
                          welcome_text: {},
                          logo_file_id: null,
                          logo_dark_file_id: null,
                          icon_file_id: null,
                        },
                        'branding.reset_done',
                      );
                    },
                  })
                }
                data-testid="branding-reset"
              >
                {t('branding.reset')}
              </WriteButton>
              {scanning && (
                <Typography.Text type="secondary" role="status">
                  {t('branding.wait_for_scan')}
                </Typography.Text>
              )}
            </Flex>
          </Flex>
        </Col>
        <Col xs={24} xl={12}>
          <BrandPreview branding={candidate} />
        </Col>
      </Row>
      <DomainsCard />
      <ConflictDialog
        open={conflict.open}
        error={conflict.error}
        fieldLabel={(field) => brandingPart(t, field)}
        opened={brandingView(opened)}
        latest={brandingView(settings.data)}
        onReload={() => {
          conflict.clear();
          setDraft(null);
          setPicked({});
          setProblems({});
          setOpened(undefined);
          setStopped(undefined);
        }}
        onKeepMine={() => {
          conflict.clear();
          setOpened(settings.data);
          if (stopped !== undefined) {
            submit(stopped.body, stopped.after, conflict.latestVersion ?? version);
          }
          setStopped(undefined);
        }}
      />
    </Flex>
  );
}
