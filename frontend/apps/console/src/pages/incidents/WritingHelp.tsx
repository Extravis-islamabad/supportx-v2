import { EditOutlined } from '@ant-design/icons';
import { Alert, Button, Drawer, Flex, Input, Segmented, Select, Space, Typography } from 'antd';
import { useState } from 'react';

import {
  useAiOutcome,
  useAiSettings,
  useWritingHelp,
  type WritingAnswer,
  type WritingRequest,
} from '@supportx/api-client';
import { describeError, lengthLimit, useLabel } from '@supportx/ui';

import { asParagraphs, plainText } from './writingText';

// Writing help in the reply and note editors (WP-038, REQ-INC-136): a draft from an
// instruction, or the text already typed improved. The answer opens in a review panel with
// Insert, Replace and Discard; nothing is ever sent from here. Shown while either feature is on.

const STYLES = ['correct', 'shorter', 'longer', 'formal', 'friendly', 'translate'] as const;
const LANGUAGES = ['en', 'ar', 'ur'] as const;
type Mode = WritingRequest['mode'];
type Style = (typeof STYLES)[number];
type Language = (typeof LANGUAGES)[number];

export function WritingHelp({
  recordId,
  kind,
  html,
  insert,
  replace,
}: {
  recordId: string;
  kind: WritingRequest['kind'];
  /** The editor's current content (improve mode works on it). */
  html: string;
  insert: (html: string) => void;
  replace: (html: string) => void;
}) {
  const t = useLabel();
  const settings = useAiSettings(true, true);
  const on = (code: string) =>
    settings.data?.features.find((f) => f.code === code)?.enabled === true;
  const draftOn = on('reply_draft');
  const improveOn = on('text_improve');
  const [open, setOpen] = useState(false);
  // The person's pick, else drafting when it is on (the settings may still be loading at first).
  const [picked, setPicked] = useState<Mode | null>(null);
  const mode: Mode = picked ?? (draftOn ? 'draft' : 'improve');
  const [instruction, setInstruction] = useState('');
  const [style, setStyle] = useState<Style>('correct');
  const [language, setLanguage] = useState<Language | undefined>(undefined);
  const [answer, setAnswer] = useState<WritingAnswer | null>(null);
  const help = useWritingHelp('incident', recordId);
  const outcome = useAiOutcome();
  if (!draftOn && !improveOn) return null;
  const current = plainText(html);
  const finish = (result: 'accepted' | 'discarded') => {
    if (answer !== null) outcome.mutate({ callId: answer.call_id, outcome: result });
    setAnswer(null);
    if (result === 'accepted') setOpen(false);
  };
  const ask = () => {
    setAnswer(null);
    help.mutate(
      mode === 'draft'
        ? { mode, kind, instruction, language }
        : {
            mode,
            kind,
            text: current,
            style,
            language: style === 'translate' ? language : undefined,
          },
      { onSuccess: setAnswer },
    );
  };
  const ready =
    mode === 'draft'
      ? instruction.trim() !== ''
      : current !== '' && (style !== 'translate' || language !== undefined);
  return (
    <>
      <Button
        size="small"
        type="text"
        icon={<EditOutlined />}
        onMouseDown={(event) => {
          event.preventDefault(); // keep the editor's caret for Insert
        }}
        onClick={() => {
          setOpen(true);
        }}
        data-testid="writing-help-open"
      >
        {t('ai.writing.button')}
      </Button>
      <Drawer
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        title={t('ai.writing.title')}
        width={480}
        destroyOnHidden
        data-testid="writing-help"
      >
        <Flex vertical gap={12}>
          {draftOn && improveOn && (
            <Segmented
              block
              value={mode}
              onChange={(value) => {
                setPicked(value);
                setAnswer(null);
              }}
              options={(['draft', 'improve'] as const).map((value) => ({
                value,
                label: t(`ai_writing_mode.${value}`),
              }))}
              data-testid="writing-help-mode"
            />
          )}
          {mode === 'draft' ? (
            <Input.TextArea
              value={instruction}
              onChange={(event) => {
                setInstruction(event.target.value);
              }}
              autoSize={{ minRows: 3, maxRows: 8 }}
              count={lengthLimit(1000)}
              placeholder={t('ai.writing.instruction_placeholder')}
              aria-label={t('ai.writing.instruction')}
              dir="auto"
              data-testid="writing-help-instruction"
            />
          ) : (
            <>
              {current === '' && (
                <Alert type="info" showIcon message={t('ai.writing.type_first')} />
              )}
              <Select
                value={style}
                onChange={setStyle}
                options={STYLES.map((value) => ({ value, label: t(`ai_writing_style.${value}`) }))}
                aria-label={t('ai.writing.style')}
                data-testid="writing-help-style"
              />
            </>
          )}
          {(mode === 'draft' || style === 'translate') && (
            <Select
              allowClear={mode === 'draft'}
              value={language}
              onChange={setLanguage}
              placeholder={t('ai.writing.language')}
              options={LANGUAGES.map((value) => ({ value, label: t(`locale.${value}`) }))}
              aria-label={t('ai.writing.language')}
              data-testid="writing-help-language"
            />
          )}
          <Button
            type="primary"
            disabled={!ready}
            loading={help.isPending}
            onClick={ask}
            data-testid="writing-help-ask"
          >
            {t('ai.writing.ask')}
          </Button>
          {help.error !== null && (
            <Alert type="error" showIcon message={describeError(help.error, t).title} />
          )}
          {answer !== null && (
            <Flex vertical gap={8} data-testid="writing-help-answer">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t('ai.writing.review', { model: answer.model })}
              </Typography.Text>
              <Typography.Paragraph
                dir="auto"
                style={{ whiteSpace: 'pre-line', marginBottom: 0 }}
                data-testid="writing-help-text"
              >
                {answer.text}
              </Typography.Paragraph>
              <Space wrap>
                <Button
                  type="primary"
                  onClick={() => {
                    insert(asParagraphs(answer.text));
                    finish('accepted');
                  }}
                  data-testid="writing-help-insert"
                >
                  {t('ai.writing.insert')}
                </Button>
                <Button
                  onClick={() => {
                    replace(asParagraphs(answer.text));
                    finish('accepted');
                  }}
                  data-testid="writing-help-replace"
                >
                  {t('ai.writing.replace')}
                </Button>
                <Button
                  onClick={() => {
                    finish('discarded');
                  }}
                  data-testid="writing-help-discard"
                >
                  {t('ai.writing.discard')}
                </Button>
              </Space>
            </Flex>
          )}
        </Flex>
      </Drawer>
    </>
  );
}
