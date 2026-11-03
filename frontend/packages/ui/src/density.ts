import { theme as antdTheme, type ThemeConfig } from 'antd';

/**
 * The console's density (docs/architecture/console-design.md, D-124). Staff screens are dense
 * by default; the portal keeps Ant Design's comfortable size.
 */
export type Density = 'compact' | 'comfortable';

/** The spacing scale: nothing in between (gaps, paddings, margins). */
export const SPACE = { xxs: 4, xs: 8, sm: 12, md: 16, lg: 24, xl: 32 } as const;

/** The type scale in px. */
export const TYPE = {
  meta: 12,
  data: 13,
  body: 14,
  section: 16,
  record: 18,
  page: 20,
} as const;

/** Table row height in the console (the cell padding below gives it with 13 px data text). */
export const ROW_HEIGHT = 40;
export const CONTROL_HEIGHT = 28;
/** The record page's permanent properties panel. */
export const PANEL_WIDTH = 320;

/** What compact density adds to a theme: Ant Design's compact algorithm and our scale. */
export function densityTheme(
  density: Density,
  algorithm: NonNullable<ThemeConfig['algorithm']>,
): Pick<ThemeConfig, 'algorithm' | 'token' | 'components'> {
  if (density === 'comfortable') return { algorithm };
  const base = Array.isArray(algorithm) ? algorithm : [algorithm];
  return {
    algorithm: [...base, antdTheme.compactAlgorithm],
    token: {
      fontSize: TYPE.body,
      controlHeight: CONTROL_HEIGHT,
      fontSizeHeading1: TYPE.page,
      fontSizeHeading2: TYPE.record,
      fontSizeHeading3: TYPE.section,
      fontSizeHeading4: TYPE.body,
      fontSizeHeading5: TYPE.body,
    },
    components: {
      Table: {
        cellFontSize: TYPE.data,
        cellPaddingBlock: 9,
        cellPaddingInline: SPACE.sm,
        cellPaddingBlockSM: 9,
        cellPaddingInlineSM: SPACE.xs,
        headerBorderRadius: 0,
      },
      Card: { headerFontSize: TYPE.body, headerHeightSM: 36, bodyPaddingSM: SPACE.sm },
      Tabs: {
        horizontalItemPadding: `${String(SPACE.xs)}px 0`,
        horizontalMargin: `0 0 ${String(SPACE.sm)}px 0`,
      },
      Descriptions: { itemPaddingBottom: SPACE.xs, titleMarginBottom: SPACE.xs },
      Layout: { headerHeight: 48, headerPadding: `0 ${String(SPACE.md)}px` },
      Menu: { itemHeight: 36, itemMarginBlock: 2 },
    },
  };
}
