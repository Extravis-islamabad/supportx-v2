import type { EChartsCoreOption } from 'echarts/core';

type Axis = Record<string, unknown>;

/** Mirror category axes for right-to-left: first category on the right, value axis on the right. */
export function mirrorForRtl(option: EChartsCoreOption, rtl: boolean): EChartsCoreOption {
  if (!rtl) return option;
  const flip = (axis: unknown, key: 'inverse' | 'position', value: unknown) =>
    Array.isArray(axis)
      ? axis.map((one: Axis) => ({ ...one, [key]: value }))
      : { ...(axis as Axis | undefined), [key]: value };
  return {
    ...option,
    xAxis: flip(option.xAxis, 'inverse', true),
    yAxis: flip(option.yAxis, 'position', 'right'),
    legend: { ...(option.legend as Axis | undefined), right: 'auto', left: 0 },
  };
}
