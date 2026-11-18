import { PrinterOutlined } from '@ant-design/icons';
import { Button, Checkbox, Flex, Form, Modal, Radio, Skeleton, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';

import { useIncident, usePrintedConversation, type Incident } from '@supportx/api-client';
import { RichTextView, useDateTime, useLabel } from '@supportx/ui';

import { IncidentApprovals } from './IncidentApprovals';
import { IncidentHistory } from './IncidentHistory';
import { IncidentTime, IncidentWorklogs, IncidentTasks } from './IncidentParts';
import { personName } from './labels';
import { RecordChecklists } from './RecordChecklists';

// WP-046b S4 (REQ-INC-126): print an incident, or save it as PDF with the browser, choosing the
// sections. Every section is read from the API the reader already uses, so it carries what they
// may see and nothing more: field access, masked and sealed values as those calls return them;
// "public notes only" is filtered by the server; attachments are never inlined (lane B). The
// page follows the reader's language and direction; the app's print rules hide the navigation,
// the buttons and the editors.

const PRINT_SECTIONS = [
  'details',
  'requester',
  'conversation',
  'tasks',
  'checklists',
  'worklogs',
  'resolution',
  'approvals',
  'time',
  'history',
] as const;
type PrintSection = (typeof PRINT_SECTIONS)[number];
const DEFAULT_SECTIONS: PrintSection[] = ['details', 'requester', 'conversation', 'resolution'];

/** Choose the sections and whether private notes are included, then open the printable page. */
export function PrintDialog({
  item,
  open,
  onClose,
}: {
  item: Pick<Incident, 'id' | 'display_id'>;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const navigate = useNavigate();
  const [sections, setSections] = useState<PrintSection[]>(DEFAULT_SECTIONS);
  const [notes, setNotes] = useState<'public' | 'all'>('public');
  return (
    <Modal
      open={open}
      title={t('incidents.print.title', { id: item.display_id })}
      okText={t('incidents.print.open')}
      cancelText={t('actions.cancel')}
      okButtonProps={{ disabled: sections.length === 0, 'data-testid': 'inc-print-open' }}
      onCancel={onClose}
      destroyOnHidden
      data-testid="inc-print-dialog"
      onOk={() => {
        const query = new URLSearchParams({ s: sections.join(','), notes });
        onClose();
        void navigate(`/incidents/${item.id}/print?${query.toString()}`);
      }}
    >
      <Form layout="vertical" component="div">
        <Form.Item label={<span id="inc-print-sections">{t('incidents.print.sections')}</span>}>
          <div role="group" aria-labelledby="inc-print-sections">
            <Checkbox.Group<PrintSection>
              value={sections}
              onChange={setSections}
              options={PRINT_SECTIONS.map((s) => ({
                value: s,
                label: t(`incidents.print.section.${s}`),
              }))}
              data-testid="inc-print-sections"
            />
          </div>
        </Form.Item>
        {sections.includes('conversation') && (
          <Form.Item label={<span id="inc-print-notes">{t('incidents.print.notes')}</span>}>
            <Radio.Group
              aria-labelledby="inc-print-notes"
              value={notes}
              onChange={(e) => {
                setNotes(e.target.value as 'public' | 'all');
              }}
              options={[
                { value: 'public', label: t('incidents.print.notes_public') },
                { value: 'all', label: t('incidents.print.notes_all') },
              ]}
              data-testid="inc-print-notes"
            />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function Section({ name, children }: { name: PrintSection; children: React.ReactNode }) {
  const t = useLabel();
  return (
    <section data-testid={`inc-print-${name}`} style={{ breakInside: 'avoid-page' }}>
      <Typography.Title level={4}>{t(`incidents.print.section.${name}`)}</Typography.Title>
      {children}
    </section>
  );
}

function PrintedConversation({ id, publicOnly }: { id: string; publicOnly: boolean }) {
  const t = useLabel();
  const { format } = useDateTime();
  const found = usePrintedConversation(id, publicOnly);
  if (found.data === undefined) return <Skeleton active />;
  const people = found.data.people;
  return (
    <Flex vertical gap={12}>
      {found.data.items.map((entry) => (
        <div key={entry.id} data-testid={`inc-print-entry-${entry.visibility}`}>
          {/* No author (the system's own entry): no name, so no leading separator (lane C). */}
          {entry.created_by !== null && (
            <>
              <Typography.Text strong>
                <bdi>{personName(people, entry.created_by)}</bdi>
              </Typography.Text>{' '}
            </>
          )}
          <Typography.Text type="secondary">
            {entry.created_by !== null && '· '}
            {t(
              entry.kind === 'reply'
                ? 'conversation_entry.reply'
                : `conversation_entry.${entry.visibility}_note`,
            )}{' '}
            · {format(entry.created_at)}
          </Typography.Text>
          <RichTextView html={entry.body} />
        </div>
      ))}
    </Flex>
  );
}

/** The printable incident (`/incidents/:id/print?s=details,…&notes=public`). */
export function IncidentPrintPage() {
  const t = useLabel();
  const { format } = useDateTime();
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const incident = useIncident(id);
  const wanted = new Set(
    (params.get('s') ?? DEFAULT_SECTIONS.join(','))
      .split(',')
      .filter((s): s is PrintSection => (PRINT_SECTIONS as readonly string[]).includes(s)),
  );
  const publicOnly = params.get('notes') !== 'all';
  // A printout of history waits for every page it will load (lane C).
  const [historyLoading, setHistoryLoading] = useState(wanted.has('history'));
  const item = incident.data;
  if (item?.id !== id) return <Skeleton active />;
  return (
    <Flex vertical gap={24} data-testid="inc-print-page" style={{ maxWidth: 900 }}>
      <Flex justify="space-between" align="center" gap={12} wrap data-sx-no-print>
        <Link to={`/incidents/${item.id}`} data-testid="inc-print-back">
          {t('incidents.print.back', { id: item.display_id })}
        </Link>
        <Typography.Text type="secondary">{t('incidents.print.help')}</Typography.Text>
        <Button
          type="primary"
          icon={<PrinterOutlined />}
          disabled={historyLoading}
          onClick={() => {
            window.print();
          }}
          data-testid="inc-print-now"
        >
          {t(historyLoading ? 'incidents.print.loading_history' : 'incidents.print.print')}
        </Button>
      </Flex>
      <header>
        <Typography.Title level={2} style={{ marginBottom: 4 }}>
          <bdi dir="ltr">{item.display_id}</bdi> <bdi dir="auto">{item.subject}</bdi>
        </Typography.Title>
        <Typography.Text type="secondary">
          {t('incidents.print.printed', { at: format(new Date().toISOString()) })}
        </Typography.Text>
      </header>
      {wanted.has('details') && (
        <Section name="details">
          {item.description === null ? null : <RichTextView html={item.description} />}
        </Section>
      )}
      {wanted.has('requester') && (
        <Section name="requester">
          <bdi>{personName(item.people, item.requester_id)}</bdi>
        </Section>
      )}
      {wanted.has('conversation') && (
        <Section name="conversation">
          <PrintedConversation id={item.id} publicOnly={publicOnly} />
        </Section>
      )}
      {wanted.has('tasks') && (
        <Section name="tasks">
          <IncidentTasks item={item} canEdit={false} />
        </Section>
      )}
      {wanted.has('checklists') && (
        <Section name="checklists">
          <RecordChecklists recordId={item.id} canEdit={false} />
        </Section>
      )}
      {wanted.has('worklogs') && (
        <Section name="worklogs">
          <IncidentWorklogs item={item} canEdit={false} />
        </Section>
      )}
      {wanted.has('resolution') && (
        <Section name="resolution">
          {item.resolution === null ? (
            <Typography.Text type="secondary">{t('incidents.print.no_resolution')}</Typography.Text>
          ) : (
            <RichTextView html={item.resolution} />
          )}
        </Section>
      )}
      {wanted.has('approvals') && (
        <Section name="approvals">
          <IncidentApprovals item={item} readOnly />
        </Section>
      )}
      {wanted.has('time') && (
        <Section name="time">
          <IncidentTime item={item} />
        </Section>
      )}
      {wanted.has('history') && (
        <Section name="history">
          <IncidentHistory id={item.id} printing onLoadingChange={setHistoryLoading} />
        </Section>
      )}
    </Flex>
  );
}
