import { Box, type BoxProps } from "@chakra-ui/react";
import { BarChart, LineChart, SankeyChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useTheme } from "next-themes";
import { useEffect, useRef } from "react";

// Only the parts we use, bundled locally: no CDN, works offline
echarts.use([SankeyChart, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

export type EOption = echarts.EChartsCoreOption;

/** Colours that follow the app theme, for chart options. */
export function chartColors(dark: boolean) {
  return {
    lime: "#c9ef3c",
    limeDim: dark ? "#5c740a" : "#98bf0f",
    pink: "#ff5fa6",
    red: "#ef4444",
    gray: dark ? "#3b4150" : "#c4c8cf",
    text: dark ? "#e4e6ea" : "#1b1f27",
    muted: dark ? "#8b92a0" : "#6a7179",
    grid: dark ? "rgba(255,255,255,0.06)" : "rgba(20,16,28,0.08)",
    panel: dark ? "#15161d" : "#ffffff",
  };
}

/** A small ECharts host: created once, option updates animate, resizes with its box. */
export function EChart({ option, ...box }: { option: (dark: boolean) => EOption } & BoxProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme !== "light";

  useEffect(() => {
    if (!ref.current) return;
    chart.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    const ro = new ResizeObserver(() => chart.current?.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    chart.current?.setOption(option(dark), { notMerge: false, lazyUpdate: true });
  }, [option, dark]);

  return <Box ref={ref} w="100%" h="260px" {...box} />;
}
