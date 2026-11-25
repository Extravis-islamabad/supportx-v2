import { Flex, Input } from 'antd';

import { lengthLimit, useLabel } from '@supportx/ui';

const LANGUAGES = ['en', 'ar', 'ur'] as const;

/** One text per language (English, Arabic, Urdu), each with its own limit and direction. */
export function PerLanguage({
  value,
  onChange,
  testId,
  limit,
  area,
}: {
  value: Record<string, string> | null | undefined;
  onChange: (next: Record<string, string>) => void;
  testId: string;
  limit: number;
  area?: boolean;
}) {
  const t = useLabel();
  return (
    <Flex vertical gap={8}>
      {LANGUAGES.map((lang) => {
        const props = {
          lang,
          dir: lang === 'en' ? ('ltr' as const) : ('rtl' as const),
          placeholder: t(`settings.name_in.${lang}`),
          'aria-label': t(`settings.name_in.${lang}`),
          count: lengthLimit(limit),
          value: value?.[lang] ?? '',
          'data-testid': `${testId}-${lang}`,
        };
        return area === true ? (
          <Input.TextArea
            key={lang}
            {...props}
            autoSize={{ minRows: 2, maxRows: 4 }}
            onChange={(event) => {
              onChange({ ...(value ?? {}), [lang]: event.target.value });
            }}
          />
        ) : (
          <Input
            key={lang}
            {...props}
            onChange={(event) => {
              onChange({ ...(value ?? {}), [lang]: event.target.value });
            }}
          />
        );
      })}
    </Flex>
  );
}
