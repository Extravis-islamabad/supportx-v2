import { useQueryClient } from '@tanstack/react-query';
import { App, Button, Checkbox, Form, Input, List, Modal, Select, Typography } from 'antd';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  incidentAnnouncementsKey,
  useAnnounceFromIncident,
  useEndIncidentAnnouncement,
  useIncidentAnnouncements,
  useUnits,
  type Incident,
} from '@supportx/api-client';
import { useListChannel } from '@supportx/realtime';
import { EmptyText, lengthLimit, reportError, useLabel, WriteButton } from '@supportx/ui';

// WP-046b S4 (REQ-INC-129): announce from an incident through the announcements module, list the
// ones made from it, and end them. The text is the technician's: it starts from the subject and
// the display ID only, and nothing is published until they confirm (lane C).

type Audience = 'everyone' | 'sites' | 'groups';
const TITLE_MAX = 200;
const BODY_MAX = 20_000;

/** Announce from this incident: the actor writes it and picks who sees it. */
export function AnnounceDialog({
  item,
  open,
  onClose,
}: {
  item: Pick<Incident, 'id' | 'display_id' | 'subject'>;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const { message } = App.useApp();
  const announce = useAnnounceFromIncident(item.id);
  const sites = useUnits('sites');
  const groups = useUnits('groups');
  // One Idempotency-Key per opening of the dialog, never per click (lane C).
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [title, setTitle] = useState(item.subject);
  const [body, setBody] = useState(() =>
    t('incidents.announce.body_start', { id: item.display_id }),
  );
  const [audience, setAudience] = useState<Audience>('everyone');
  const [units, setUnits] = useState<string[]>([]);
  const [banner, setBanner] = useState(true);
  const close = () => {
    setKey(crypto.randomUUID());
    setTitle(item.subject);
    setBody(t('incidents.announce.body_start', { id: item.display_id }));
    setAudience('everyone');
    setUnits([]);
    onClose();
  };
  const ready =
    title.trim() !== '' && body.trim() !== '' && (audience === 'everyone' || units.length > 0);
  const choices = (audience === 'sites' ? sites.data : groups.data) ?? [];
  return (
    <Modal
      open={open}
      title={t('incidents.announce.title', { id: item.display_id })}
      okText={t('incidents.announce.confirm')}
      cancelText={t('actions.cancel')}
      okButtonProps={{
        disabled: !ready,
        loading: announce.isPending,
        'data-testid': 'inc-announce-confirm',
      }}
      onCancel={close}
      destroyOnHidden
      data-testid="inc-announce-dialog"
      onOk={() => {
        announce.mutate(
          {
            key,
            values: {
              title: title.trim(),
              body: body.trim(),
              severity: 'info',
              audience,
              site_ids: audience === 'sites' ? units : [],
              group_ids: audience === 'groups' ? units : [],
              show_as_banner: banner,
              publish: true,
            },
          },
          {
            onSuccess: (made) => {
              // Asked to publish but not allowed to: it is a draft, said in words (lane C).
              if (made.status === 'draft') {
                void message.warning(t('incidents.announce.saved_draft', { id: made.display_id }));
              } else {
                void message.success(t('incidents.announce.published', { id: made.display_id }));
              }
              close();
            },
            onError: reportError,
          },
        );
      }}
    >
      <Typography.Paragraph type="secondary">{t('incidents.announce.help')}</Typography.Paragraph>
      <Form layout="vertical" component="div">
        <Form.Item label={t('incidents.announce.heading')} htmlFor="inc-announce-title" required>
          <Input
            id="inc-announce-title"
            value={title}
            count={lengthLimit(TITLE_MAX, true)}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
            data-testid="inc-announce-title"
          />
        </Form.Item>
        <Form.Item label={t('incidents.announce.text')} htmlFor="inc-announce-body" required>
          <Input.TextArea
            id="inc-announce-body"
            value={body}
            count={lengthLimit(BODY_MAX, true)}
            autoSize={{ minRows: 3, maxRows: 8 }}
            onChange={(e) => {
              setBody(e.target.value);
            }}
            data-testid="inc-announce-body"
          />
        </Form.Item>
        <Form.Item label={t('incidents.announce.audience')} htmlFor="inc-announce-audience">
          <Select<Audience>
            id="inc-announce-audience"
            value={audience}
            onChange={(next) => {
              setAudience(next);
              setUnits([]);
            }}
            options={(['everyone', 'sites', 'groups'] as const).map((a) => ({
              value: a,
              label: t(`announcement_audience.${a}`),
            }))}
            data-testid="inc-announce-audience"
          />
        </Form.Item>
        {audience !== 'everyone' && (
          <Form.Item
            label={t(
              audience === 'sites' ? 'incidents.announce.sites' : 'incidents.announce.groups',
            )}
            htmlFor="inc-announce-units"
            required
          >
            <Select
              id="inc-announce-units"
              mode="multiple"
              value={units}
              onChange={setUnits}
              optionFilterProp="label"
              options={choices.map((u) => ({ value: u.id, label: u.name }))}
              data-testid="inc-announce-units"
            />
          </Form.Item>
        )}
        <Checkbox
          checked={banner}
          onChange={(e) => {
            setBanner(e.target.checked);
          }}
          data-testid="inc-announce-banner"
        >
          {t('incidents.announce.banner')}
        </Checkbox>
      </Form>
    </Modal>
  );
}

/** The announcements made from this incident, live, each with End while it is not archived. */
export function IncidentAnnouncements({ item }: { item: Pick<Incident, 'id'> }) {
  const t = useLabel();
  const found = useIncidentAnnouncements(item.id);
  const end = useEndIncidentAnnouncement(item.id);
  const queryClient = useQueryClient();
  // Announcements' own channel (lane C): a publish, end or edit anywhere refreshes the list.
  useListChannel('announcements', () => {
    void queryClient.invalidateQueries({ queryKey: incidentAnnouncementsKey(item.id) });
  });
  const items = found.data ?? [];
  if (items.length === 0) {
    return (
      <div data-testid="inc-announcements-empty">
        <EmptyText>{t('incidents.announce.none')}</EmptyText>
      </div>
    );
  }
  return (
    <List
      size="small"
      data-testid="inc-announcements"
      dataSource={items}
      renderItem={(a) => (
        <List.Item
          data-testid={`inc-announcement-${a.display_id}`}
          actions={
            a.status === 'archived'
              ? []
              : [
                  <WriteButton
                    key="end"
                    size="small"
                    loading={end.isPending && end.variables === a.id}
                    data-testid={`inc-announcement-end-${a.display_id}`}
                    onClick={() => {
                      end.mutate(a.id, { onError: reportError });
                    }}
                  >
                    {t('incidents.announce.end')}
                  </WriteButton>,
                ]
          }
        >
          <span>
            <Link to={`/announcements/${a.id}`}>
              <bdi dir="ltr">{a.display_id}</bdi> <bdi dir="auto">{a.title}</bdi>
            </Link>{' '}
            <Typography.Text type="secondary">
              · {t(`announcement_status.${a.status}`)}
            </Typography.Text>
          </span>
        </List.Item>
      )}
    />
  );
}

/** On resolving: the live announcements made from it, offered to end (nothing ends by itself). */
export function EndAnnouncementsPrompt({
  item,
  open,
  onClose,
}: {
  item: Pick<Incident, 'id' | 'display_id'>;
  open: boolean;
  onClose: () => void;
}) {
  const t = useLabel();
  const found = useIncidentAnnouncements(item.id, open);
  const live = (found.data ?? []).filter((a) => a.status !== 'archived');
  return (
    <Modal
      open={open && live.length > 0}
      title={t('incidents.announce.end_prompt_title', { id: item.display_id })}
      onCancel={onClose}
      footer={
        <Button onClick={onClose} data-testid="inc-announce-prompt-close">
          {t('incidents.announce.keep')}
        </Button>
      }
      data-testid="inc-announce-prompt"
    >
      <Typography.Paragraph>{t('incidents.announce.end_prompt')}</Typography.Paragraph>
      <IncidentAnnouncements item={item} />
    </Modal>
  );
}
