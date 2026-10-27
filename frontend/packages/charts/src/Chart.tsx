import { ConfigProvider, theme } from 'antd';
import { BarChart, GaugeChart, LineChart, PieChart } from 'echarts/charts';
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import {
  init,
  use as registerEcharts,
  type EChartsCoreOption,
  type EChartsType,
} from 'echarts/core';
import { CanvasRenderer } from 'echarts/renderers';
import { useContext, useEffect, useMemo, useRef } from 'react';

import { mirrorForRtl } from './rtl';

// Only what the charts use is registered: keeps the ECharts chunk small (tree-shaken core).
registerEcharts([
  BarChart,
  LineChart,
  PieChart,
  GaugeChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  AriaComponent,
  CanvasRenderer,
]);

export interface ChartProps {
  option: EChartsCoreOption;
  /** Accessible description read by screen readers (already translated). */
  ariaLabel: string;
  height?: number;
  /**
   * Called with the category index of a clicked bar, point or slice (drill-down, REQ-RPT-037).
   * The same records stay reachable by keyboard through the caller's table view.
   */
  onSelect?: (index: number) => void;
}

/**
 * An ECharts chart that takes its colours from the Ant Design theme (brand primary first, text
 * and grid lines from the theme tokens), so it follows light, dark and high contrast, and
 * mirrors for right-to-left.
 */
export function Chart({ option, ariaLabel, height = 320, onSelect }: ChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<EChartsType | null>(null);
  const select = useRef(onSelect);
  useEffect(() => {
    select.current = onSelect;
  }, [onSelect]);
  const { token } = theme.useToken();
  const { direction } = useContext(ConfigProvider.ConfigContext);

  const themed = useMemo<EChartsCoreOption>(
    () =>
      mirrorForRtl(
        {
          color: [
            token.colorPrimary,
            token.colorInfo,
            token.colorSuccess,
            token.colorWarning,
            token.colorError,
          ],
          textStyle: { color: token.colorText, fontFamily: token.fontFamily },
          aria: { enabled: true, label: { description: ariaLabel } },
          tooltip: { trigger: 'axis' },
          ...option,
        },
        direction === 'rtl',
      ),
    [option, ariaLabel, direction, token],
  );

  useEffect(() => {
    if (ref.current === null) return;
    const instance = init(ref.current, undefined, { renderer: 'canvas' });
    chart.current = instance;
    instance.on('click', (event) => {
      if (typeof event.dataIndex === 'number') select.current?.(event.dataIndex);
    });
    const resize = () => {
      instance.resize();
    };
    window.addEventListener('resize', resize);
    return () => {
      window.removeEventListener('resize', resize);
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(themed, { notMerge: true });
  }, [themed]);

  return (
    <div
      ref={ref}
      role="img"
      aria-label={ariaLabel}
      style={{ width: '100%', height, cursor: onSelect ? 'pointer' : undefined }}
    />
  );
}
