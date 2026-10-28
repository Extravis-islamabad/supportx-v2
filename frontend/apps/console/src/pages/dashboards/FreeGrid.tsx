import 'react-grid-layout/css/styles.css';

import { type ReactNode, type RefObject } from 'react';
import { GridLayout, useContainerWidth, verticalCompactor, type Layout } from 'react-grid-layout';

import type { DashboardWidget } from '@supportx/api-client';

import { layoutOf, placesOf } from './gridMirror';
import { COLUMNS, ROW_PX, type Place } from './layout';

// Free-form dragging and resizing in edit mode (REQ-DSH-019; react-grid-layout, D-110). This
// file is loaded only when someone edits a dashboard (lazy), so viewers never download it.
//
// Right to left: the library lays out from the left edge only. The grid itself stays left to
// right, and in Arabic and Urdu each widget's column is mirrored on the way in and out
// (x' = 12 - x - w), so the first column is on the right like the read-only grid; resizing
// grabs the bottom-left corner, the end side in right to left. The widgets' content keeps the
// page's direction. Checked by e2e (dashboards-grid.spec.ts).

const MARGIN = 12;

export function FreeGrid({
  widgets,
  rtl,
  render,
  onPlaces,
}: {
  widgets: DashboardWidget[];
  rtl: boolean;
  render: (widget: DashboardWidget) => ReactNode;
  /** Called once a drag or resize ends, with every widget's place (for undo and saving). */
  onPlaces: (places: Map<string, Place>) => void;
}) {
  const { width, containerRef, mounted } = useContainerWidth();
  const finish = (layout: Layout) => {
    onPlaces(placesOf(layout, rtl));
  };
  return (
    <div
      // The library types its ref for React 19 (`RefObject<T | null>`); React 18's `ref` prop
      // wants `RefObject<T>`. Same object at run time.
      ref={containerRef as RefObject<HTMLDivElement>}
      dir="ltr"
      data-testid="dashboard-free-grid"
    >
      {mounted && (
        <GridLayout
          width={width}
          layout={layoutOf(widgets, rtl)}
          gridConfig={{
            cols: COLUMNS,
            rowHeight: ROW_PX,
            margin: [MARGIN, MARGIN],
            containerPadding: [0, 0],
          }}
          dragConfig={{ enabled: true, handle: '.dashboard-drag-handle', cancel: 'button' }}
          resizeConfig={{ enabled: true, handles: [rtl ? 'sw' : 'se'] }}
          compactor={verticalCompactor}
          onDragStop={finish}
          onResizeStop={finish}
        >
          {widgets.map((widget) => (
            <div key={widget.id} dir={rtl ? 'rtl' : 'ltr'} data-testid={`free-${widget.id}`}>
              {render(widget)}
            </div>
          ))}
        </GridLayout>
      )}
    </div>
  );
}
