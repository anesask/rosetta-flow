import { Grid, HStack, Text } from "@chakra-ui/react";
import { useCallback } from "react";

import { type FleetRow, PRICE } from "../api";
import { chartColors, EChart } from "./EChart";
import { Eyebrow, Surface } from "./Surface";

const mono = "JetBrains Mono Variable, monospace";

/** What happened to the runs (Sankey), the cost as the day goes on (line), and outcomes compared (bars).
 *  `rows` is the part of the fleet replayed so far; before a replay the whole measured set is shown. */
export function FleetCharts({ rows, replaying }: { rows: FleetRow[]; replaying: boolean }) {
  const sankey = useCallback(
    (dark: boolean) => {
      const c = chartColors(dark);
      const count = (f: (r: FleetRow) => boolean) => rows.filter(f).length;
      const links = [
        { source: "Incoming runs", target: "8B cleared", value: count((r) => r.screen === "ok") },
        { source: "Incoming runs", target: "8B flagged", value: count((r) => r.screen === "issues_found") },
        { source: "Incoming runs", target: "8B no report", value: count((r) => r.screen === "failed") },
        { source: "8B flagged", target: "70B confirms", value: count((r) => r.screen === "issues_found" && r.final === "issues_found") },
        { source: "8B flagged", target: "70B clears", value: count((r) => r.screen === "issues_found" && r.final === "ok") },
        { source: "8B no report", target: "70B confirms", value: count((r) => r.screen === "failed" && r.final === "issues_found") },
        { source: "8B no report", target: "70B clears", value: count((r) => r.screen === "failed" && r.final === "ok") },
        { source: "8B cleared", target: "Right: clean", value: count((r) => r.screen === "ok" && !r.error) },
        { source: "8B cleared", target: "Missed error", value: count((r) => r.screen === "ok" && !!r.error) },
        { source: "70B confirms", target: "Right: caught", value: count((r) => r.escalated && r.final === "issues_found" && !!r.error) },
        { source: "70B confirms", target: "False alarm", value: count((r) => r.escalated && r.final === "issues_found" && !r.error) },
        { source: "70B clears", target: "Right: clean", value: count((r) => r.escalated && r.final === "ok" && !r.error) },
        { source: "70B clears", target: "Missed error", value: count((r) => r.escalated && r.final === "ok" && !!r.error) },
      ].filter((l) => l.value > 0);
      const color: Record<string, string> = {
        "Incoming runs": c.muted,
        "8B cleared": c.limeDim,
        "8B flagged": c.lime,
        "8B no report": c.gray,
        "70B confirms": c.pink,
        "70B clears": c.pink,
        "Right: clean": c.lime,
        "Right: caught": c.lime,
        "Missed error": c.red,
        "False alarm": c.red,
      };
      const names = [...new Set(links.flatMap((l) => [l.source, l.target]))];
      // Node totals computed here: inflow for every node, outflow for the source
      const total = new Map<string, number>();
      for (const l of links) total.set(l.target, (total.get(l.target) ?? 0) + l.value);
      total.set("Incoming runs", rows.length);
      return {
        animationDurationUpdate: 300,
        tooltip: { trigger: "item", backgroundColor: c.panel, borderColor: c.grid, textStyle: { color: c.text, fontFamily: mono, fontSize: 11 } },
        series: [
          {
            type: "sankey",
            left: 8,
            right: 150,
            top: 10,
            bottom: 10,
            nodeWidth: 12,
            nodeGap: 12,
            draggable: false,
            layoutIterations: 0,
            data: names.map((n) => ({ name: n, value: total.get(n) ?? 0, itemStyle: { color: color[n] ?? c.muted, borderWidth: 0 } })),
            links,
            lineStyle: { color: "gradient", opacity: dark ? 0.35 : 0.45, curveness: 0.5 },
            label: { color: c.text, fontFamily: mono, fontSize: 11, formatter: (p: { name: string }) => `${p.name}  ${total.get(p.name) ?? 0}` },
            emphasis: { focus: "adjacency" },
          },
        ],
      };
    },
    [rows],
  );

  const cost = useCallback(
    (dark: boolean) => {
      const c = chartColors(dark);
      let two = 0;
      let alone = 0;
      const xs: number[] = [];
      const a: number[] = [];
      const b: number[] = [];
      rows.forEach((r, i) => {
        two += (r.tok8 * PRICE["8B"] + r.tok70 * PRICE["70B"]) / 1e6;
        alone += (r.tok70_alone * PRICE["70B"]) / 1e6;
        xs.push(i + 1);
        a.push(+two.toFixed(4));
        b.push(+alone.toFixed(4));
      });
      const axis = { axisLine: { lineStyle: { color: c.grid } }, axisLabel: { color: c.muted, fontFamily: mono, fontSize: 10 }, splitLine: { lineStyle: { color: c.grid } } };
      return {
        animation: !replaying,
        grid: { left: 52, right: 16, top: 30, bottom: 28 },
        legend: { top: 0, right: 0, textStyle: { color: c.muted, fontFamily: mono, fontSize: 10 }, itemWidth: 14, itemHeight: 3 },
        tooltip: { trigger: "axis", backgroundColor: c.panel, borderColor: c.grid, textStyle: { color: c.text, fontFamily: mono, fontSize: 11 }, valueFormatter: (v: number) => `CHF ${v.toFixed(3)}` },
        xAxis: { type: "category", data: xs, name: "runs", nameTextStyle: { color: c.muted, fontSize: 10 }, ...axis, splitLine: { show: false }, axisLabel: { ...axis.axisLabel, interval: Math.max(0, Math.floor(xs.length / 6) - 1) } },
        yAxis: { type: "value", ...axis, axisLabel: { ...axis.axisLabel, formatter: (v: number) => v.toFixed(2) } },
        series: [
          { name: "70B on every run", type: "line", data: b, showSymbol: false, smooth: true, lineStyle: { color: c.red, width: 2 }, itemStyle: { color: c.red } },
          { name: "two tiers", type: "line", data: a, showSymbol: false, smooth: true, lineStyle: { color: c.lime, width: 2.5 }, itemStyle: { color: c.lime }, areaStyle: { color: c.lime, opacity: 0.08 } },
        ],
      };
    },
    [rows, replaying],
  );

  const outcomes = useCallback(
    (dark: boolean) => {
      const c = chartColors(dark);
      const broken = rows.filter((r) => r.error);
      const clean = rows.filter((r) => !r.error);
      const two = [broken.filter((r) => r.final === "issues_found").length, clean.filter((r) => r.final === "issues_found").length, rows.filter((r) => r.escalated).length];
      const alone = [broken.filter((r) => r.alone === "issues_found").length, clean.filter((r) => r.alone === "issues_found").length, rows.length];
      const axis = { axisLine: { lineStyle: { color: c.grid } }, axisLabel: { color: c.muted, fontFamily: mono, fontSize: 10 }, splitLine: { lineStyle: { color: c.grid } } };
      return {
        animationDurationUpdate: 250,
        grid: { left: 40, right: 16, top: 30, bottom: 28 },
        legend: { top: 0, right: 0, textStyle: { color: c.muted, fontFamily: mono, fontSize: 10 }, itemWidth: 10, itemHeight: 10 },
        tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: c.panel, borderColor: c.grid, textStyle: { color: c.text, fontFamily: mono, fontSize: 11 } },
        xAxis: { type: "category", data: ["errors flagged", "false alarms", "runs the 70B reads"], ...axis, splitLine: { show: false } },
        yAxis: { type: "value", ...axis },
        series: [
          { name: "two tiers", type: "bar", data: two, barGap: "20%", barWidth: "28%", itemStyle: { color: c.lime, borderRadius: [4, 4, 0, 0] }, label: { show: true, position: "top", color: c.text, fontFamily: mono, fontSize: 10 } },
          { name: "70B alone", type: "bar", data: alone, barWidth: "28%", itemStyle: { color: c.gray, borderRadius: [4, 4, 0, 0] }, label: { show: true, position: "top", color: c.muted, fontFamily: mono, fontSize: 10 } },
        ],
      };
    },
    [rows],
  );

  return (
    <>
      <Surface>
        <HStack justify="space-between" mb="1">
          <Eyebrow mb="0">What happened to every run</Eyebrow>
          <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
            {rows.length} runs · hover a band for counts
          </Text>
        </HStack>
        <EChart option={sankey} h="300px" />
      </Surface>
      <Grid templateColumns={{ base: "1fr", md: "1fr 1fr" }} gap="4">
        <Surface>
          <Eyebrow mb="1">Cost as the day goes on · CHF</Eyebrow>
          <EChart option={cost} h="240px" />
        </Surface>
        <Surface>
          <Eyebrow mb="1">Two tiers vs the 70B alone</Eyebrow>
          <EChart option={outcomes} h="240px" />
        </Surface>
      </Grid>
    </>
  );
}
