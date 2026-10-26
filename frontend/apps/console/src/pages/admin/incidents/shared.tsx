import { Alert, Checkbox, ColorPicker, Flex, Form, Input, Modal, Typography } from 'antd';
import { useEffect, useRef, useState } from 'react';

import type { Labels } from '@supportx/api-client';
import { useLabelsIn } from '@supportx/labels';
import { useLabel } from '@supportx/ui';

import { cleanLabels } from './helpers';

export function Problems({ problems, testId }: { problems: string[]; testId?: string }) {
  if (problems.length === 0) return null;
  return (
    <Alert
      type="error"
      showIcon
      role="alert"
      message={problems.join(' ')}
      style={{ marginBottom: 12 }}
      data-testid={testId ?? 'settings-problems'}
    />
  );
}

const LANGUAGES = ['en', 'ar', 'ur'] as const;

/** English (required), Arabic and Urdu names, each typed in its own direction. */
export function LabelsFields({
  value,
  onChange,
  testId,
  autoFocus = true,
}: {
  value: Labels;
  onChange: (next: Labels) => void;
  testId: string;
  autoFocus?: boolean;
}) {
  const t = useLabel();
  const first = useRef<HTMLInputElement | null>(null);
  // Dialogs open with the caret in the first name (QA BUG-09). After the dialog's own focus
  // handling, which would otherwise take it back to the dialog frame.
  useEffect(() => {
    if (!autoFocus) return undefined;
    const timer = setTimeout(() => {
      first.current?.focus();
    }, 60);
    return () => {
      clearTimeout(timer);
    };
  }, [autoFocus]);
  return (
    <>
      {LANGUAGES.map((language) => (
        <Form.Item
          key={language}
          label={t(`settings.name_in.${language}`)}
          required={language === 'en'}
          htmlFor={`${testId}-${language}`}
        >
          <Input
            ref={(element) => {
              if (language === 'en') first.current = element?.input ?? null;
            }}
            id={`${testId}-${language}`}
            dir={language === 'en' ? 'ltr' : 'rtl'}
            lang={language}
            maxLength={120}
            value={value[language] ?? ''}
            onChange={(event) => {
              onChange({ ...value, [language]: event.target.value });
            }}
            data-testid={`${testId}-${language}`}
          />
        </Form.Item>
      ))}
    </>
  );
}

export function ColourField({
  value,
  onChange,
  label,
  testId,
}: {
  value: string | null;
  onChange: (next: string | null) => void;
  label: string;
  testId: string;
}) {
  const t = useLabel();
  return (
    <Form.Item label={label}>
      <ColorPicker
        value={value ?? undefined}
        allowClear
        disabledAlpha
        format="hex"
        // Our words for "none", not the picker's "Transparent" (QA C2).
        showText={() => value ?? t('settings.no_colour')}
        onChange={(colour) => {
          onChange(colour.toHexString());
        }}
        onClear={() => {
          onChange(null);
        }}
        aria-label={label}
        data-testid={testId}
      />
    </Form.Item>
  );
}

/**
 * Rename / translate (and colour) one value. Seeded values have a shipped name in every
 * language: the dialog shows it and an admin may go back to it.
 */
export function ValueDialog({
  open,
  title,
  shippedKey,
  labels,
  colour,
  withColour,
  colourRequired,
  pending,
  problems,
  onCancel,
  onSave,
  testId,
}: {
  open: boolean;
  title: string;
  /** Label key of the built-in name (seeded values); null for admin values. */
  shippedKey: string | null;
  labels: Labels | null;
  colour?: string | null;
  withColour?: boolean;
  colourRequired?: boolean;
  pending: boolean;
  problems: string[];
  onCancel: () => void;
  onSave: (labels: Labels | null, colour: string | null) => void;
  testId: string;
}) {
  const t = useLabel();
  const tIn = useLabelsIn();
  const shipped = shippedKey === null ? null : t(shippedKey);
  const [names, setNames] = useState<Labels>(labels ?? {});
  const [shippedName, setShippedName] = useState(shipped !== null && labels === null);
  const [hex, setHex] = useState<string | null>(colour ?? null);
  return (
    <Modal
      open={open}
      title={title}
      okText={t('actions.save')}
      cancelText={t('actions.cancel')}
      confirmLoading={pending}
      onCancel={onCancel}
      onOk={() => {
        onSave(shippedName ? null : (cleanLabels(names) ?? {}), hex);
      }}
      destroyOnHidden
      data-testid={testId}
    >
      <Problems problems={problems} testId={`${testId}-problems`} />
      <Form layout="vertical" component="div">
        {shipped !== null && (
          <Flex vertical gap={4} style={{ marginBottom: 12 }}>
            <Typography.Text type="secondary">
              {t('settings.shipped_name', { name: shipped })}
            </Typography.Text>
            <Checkbox
              checked={shippedName}
              onChange={(event) => {
                setShippedName(event.target.checked);
                // Start from the built-in names in every language, to edit (QA C2).
                if (!event.target.checked && shippedKey !== null && cleanLabels(names) === null) {
                  setNames(
                    Object.fromEntries(
                      (['en', 'ar', 'ur'] as const).map((lang) => [lang, tIn(lang, shippedKey)]),
                    ),
                  );
                }
              }}
              data-testid={`${testId}-shipped`}
            >
              {t('settings.use_shipped_name')}
            </Checkbox>
          </Flex>
        )}
        {!shippedName && (
          <LabelsFields value={names} onChange={setNames} testId={`${testId}-name`} />
        )}
        {withColour === true && (
          <ColourField
            value={hex}
            onChange={(next) => {
              setHex(next === null && colourRequired === true ? hex : next);
            }}
            label={t('settings.colour')}
            testId={`${testId}-colour`}
          />
        )}
      </Form>
    </Modal>
  );
}
