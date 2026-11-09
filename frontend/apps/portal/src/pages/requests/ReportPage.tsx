import { CameraOutlined, CloseOutlined, PaperClipOutlined } from '@ant-design/icons';
import {
  App as AntApp,
  Button,
  Flex,
  Form,
  Input,
  Select,
  Skeleton,
  Space,
  Typography,
  Upload,
} from 'antd';
import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import {
  uploadFile,
  usePortalTemplates,
  useReportIssue,
  type PortalTemplate,
} from '@supportx/api-client';
import { lengthLimit, reportError, RichTextField, useAppearance, useLabel } from '@supportx/ui';

import { ForWhom } from './ForWhom';
import { FormCard } from '../FormCard';
import { FORM_COLUMN } from '../formColumn';

const SUBJECT_MAX = 250;

function templateName(
  template: PortalTemplate,
  locale: string,
  t: ReturnType<typeof useLabel>,
): string {
  const own = template.labels?.[locale] ?? template.labels?.en;
  if (own) return own;
  return template.code ? t(`incident_template.${template.code}`) : t('portal.report.form');
}

/**
 * Report an issue (REQ-INC-028): the form of a template offered to requesters, with only the
 * fields they may fill in. The new ID shows at once: the record opens as soon as it is saved.
 * One Idempotency-Key per form, so a double tap or a retry never makes two incidents.
 */
export function ReportPage() {
  const t = useLabel();
  const { locale } = useAppearance();
  const navigate = useNavigate();
  const templates = usePortalTemplates();
  const report = useReportIssue();
  // A catalog "report a problem" entry opens this form with its template (WP-031 plan D10).
  const [params] = useSearchParams();
  const [templateId, setTemplateId] = useState<string | undefined>(
    params.get('template') ?? undefined,
  );
  const [subject, setSubject] = useState(params.get('subject') ?? ''); // from search (WP-032 D2)
  const [onBehalf, setOnBehalf] = useState<string | null>(null);
  const [description, setDescription] = useState('');
  const key = useMemo(() => crypto.randomUUID(), []);
  const [chosenFiles, setChosenFiles] = useState<File[]>([]);
  const [attaching, setAttaching] = useState(false);
  const { message } = AntApp.useApp();
  // Kept here until the record exists, then sent to it (the server checks type, size, malware).
  const keep = (file: File) => {
    setChosenFiles((all) => [...all, file]);
    return false;
  };
  const attach = async (recordId: string) => {
    if (chosenFiles.length === 0) return;
    setAttaching(true);
    const sent = await Promise.allSettled(
      chosenFiles.map(
        (file) => uploadFile(file, { ownerType: 'work_item', ownerId: recordId }).done,
      ),
    );
    setAttaching(false);
    const failed = sent.filter((r) => r.status === 'rejected').length;
    if (failed > 0) void message.warning(t('portal.report.files_failed', { count: failed }));
  };

  if (templates.isLoading) return <Skeleton active />;
  const offered = templates.data ?? [];
  const chosen = offered.find((x) => x.id === templateId) ?? offered[0];
  const fields = new Set((chosen?.fields ?? []).map((f) => f.name));
  const required = new Set((chosen?.fields ?? []).filter((f) => f.required).map((f) => f.name));
  const empty = (html: string) => html.replace(/<[^>]*>/g, '').trim() === '';
  const ready =
    chosen !== undefined &&
    subject.trim() !== '' &&
    !(required.has('description') && empty(description));

  return (
    <Flex vertical gap={16} style={FORM_COLUMN}>
      <Link to="/requests">{t('portal.request.back')}</Link>
      <Typography.Title level={1} style={{ margin: 0 }}>
        {t('portal.report.title')}
      </Typography.Title>
      <FormCard testId="portal-report-form">
        <Form
          layout="vertical"
          requiredMark
          onFinish={() => {
            if (!ready) return;
            report.mutate(
              {
                key,
                body: {
                  template_id: chosen.id,
                  subject: subject.trim(),
                  ...(fields.has('description') && !empty(description) ? { description } : {}),
                  ...(onBehalf !== null ? { on_behalf_of_id: onBehalf } : {}),
                },
              },
              {
                onSuccess: (made) => {
                  void attach(made.id).then(() =>
                    navigate(`/requests/${made.id}`, { replace: true }),
                  );
                },
                onError: reportError,
              },
            );
          }}
        >
          {offered.length > 1 && (
            <Form.Item label={t('portal.report.form')} htmlFor="portal-report-template">
              <Select
                id="portal-report-template"
                value={chosen?.id}
                onChange={(value: string) => {
                  setTemplateId(value);
                }}
                options={offered.map((x) => ({ value: x.id, label: templateName(x, locale, t) }))}
                data-testid="portal-report-template"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.for_whom')}>
            <ForWhom value={onBehalf} onChange={setOnBehalf} />
          </Form.Item>
          <Form.Item label={t('portal.report.subject')} htmlFor="portal-report-subject" required>
            <Input
              id="portal-report-subject"
              size="large"
              value={subject}
              count={lengthLimit(SUBJECT_MAX)}
              onChange={(event) => {
                setSubject(event.target.value);
              }}
              data-testid="portal-report-subject"
            />
          </Form.Item>
          {fields.has('description') && (
            <Form.Item
              label={t('portal.report.description')}
              required={required.has('description')}
            >
              <RichTextField
                value={description}
                onChange={setDescription}
                label={t('portal.report.description')}
                placeholder={t('portal.report.description_hint')}
                testId="portal-report-description"
              />
            </Form.Item>
          )}
          <Form.Item label={t('portal.report.files')}>
            <Flex vertical gap={8}>
              {chosenFiles.map((file, at) => (
                <Flex key={`${file.name}-${String(at)}`} align="center" gap={8}>
                  <Typography.Text ellipsis style={{ flex: 1, minWidth: 0 }}>
                    {file.name}
                  </Typography.Text>
                  <Button
                    type="text"
                    icon={<CloseOutlined />}
                    aria-label={t('portal.report.remove_file', { name: file.name })}
                    onClick={() => {
                      setChosenFiles((all) => all.filter((_, i) => i !== at));
                    }}
                  />
                </Flex>
              ))}
              <Space wrap>
                <Upload multiple showUploadList={false} beforeUpload={keep}>
                  <Button
                    size="large"
                    icon={<PaperClipOutlined />}
                    data-testid="portal-report-files"
                  >
                    {t('portal.report.add_files')}
                  </Button>
                </Upload>
                <Upload
                  accept="image/*"
                  capture="environment"
                  showUploadList={false}
                  beforeUpload={keep}
                >
                  <Button size="large" icon={<CameraOutlined />} data-testid="portal-report-camera">
                    {t('files.take_photo')}
                  </Button>
                </Upload>
              </Space>
            </Flex>
          </Form.Item>
          <Button
            type="primary"
            size="large"
            htmlType="submit"
            disabled={!ready}
            loading={report.isPending || attaching}
            data-testid="portal-report-send"
          >
            {t('portal.report.send')}
          </Button>
        </Form>
      </FormCard>
    </Flex>
  );
}
