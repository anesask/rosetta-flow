import { Box, HStack, Text } from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";
import { Bot, Gavel, Wrench } from "lucide-react";

import type { Lane } from "./FlowDialog";
import { TOOL_ICON, type ToolCall } from "./Pipeline";

type Call = { t: ToolCall; li: number; i: number };
type Props = {
  lanes: Lane[];
  calls: Call[];
  cursor: number; // calls shown; the current call is cursor-1
  escalated: boolean | null;
  verdict: { title: string; good: boolean | null };
  finished: boolean;
  steps: number;
  onJump: (k: number) => void;
};

const W = 150;
const H = 64;
const COL = 190; // node width + gap
const ROW_A = 18;
const ROW_B = ROW_A + H + 64;
const PAD = 16;

type NodeBox = { key: string; x: number; y: number; order: number; kind: "start" | "call" | "end"; call?: Call };

/** Tool calls as a pipeline graph: Agent run → 8B tool calls → (flagged) → 70B tool calls → Verdict.
 *  Edges are curves; passed edges are lime, the edge into the current node flows, future edges are grey. */
export function PipelineGraph({ lanes, calls, cursor, escalated, verdict, finished, steps, onJump }: Props) {
  const s8 = calls.filter((c) => c.li === 0);
  const s70 = calls.filter((c) => c.li === 1);
  const nodes: NodeBox[] = [];
  const start: NodeBox = { key: "start", x: PAD, y: s70.length ? (ROW_A + ROW_B) / 2 : ROW_A, order: 0, kind: "start" };
  nodes.push(start);
  let order = 1;
  s8.forEach((c, i) => nodes.push({ key: `a${i}`, x: PAD + COL * (i + 1), y: ROW_A, order: order++, kind: "call", call: c }));
  const col70 = Math.max(1, s8.length); // the 70B row starts under the 8B's last call
  s70.forEach((c, i) => nodes.push({ key: `b${i}`, x: PAD + COL * (col70 + i), y: ROW_B, order: order++, kind: "call", call: c }));
  const lastCol = s70.length ? col70 + s70.length : s8.length + 1;
  const end: NodeBox = { key: "end", x: PAD + COL * lastCol, y: s70.length ? (ROW_A + ROW_B) / 2 : ROW_A, order: order, kind: "end" };
  nodes.push(end);

  const a = nodes.filter((n) => n.key.startsWith("a"));
  const b = nodes.filter((n) => n.key.startsWith("b"));
  type Edge = { from: NodeBox; to: NodeBox; label?: string; vertical?: boolean };
  const edges: Edge[] = [];
  const firstWork = a[0] ?? b[0];
  if (firstWork) edges.push({ from: start, to: firstWork });
  for (let i = 1; i < a.length; i++) edges.push({ from: a[i - 1], to: a[i] });
  if (a.length && b.length) edges.push({ from: a[a.length - 1], to: b[0], label: "flagged → 70B", vertical: true });
  for (let i = 1; i < b.length; i++) edges.push({ from: b[i - 1], to: b[i] });
  const lastWork = b[b.length - 1] ?? a[a.length - 1];
  if (lastWork) edges.push({ from: lastWork, to: end, label: escalated === false ? "cleared" : undefined });

  const width = end.x + W + PAD;
  const height = (s70.length ? ROW_B + H : ROW_A + H) + 26;
  // Long investigations are scaled down to fit the dialog instead of scrolling sideways
  const host = useRef<HTMLDivElement | null>(null);
  const [avail, setAvail] = useState(width);
  useEffect(() => {
    if (!host.current) return;
    const ro = new ResizeObserver(([e]) => setAvail(e.contentRect.width));
    ro.observe(host.current);
    return () => ro.disconnect();
  }, []);
  const scale = Math.min(1, avail / width);
  const reached = (n: NodeBox) => (n.kind === "start" ? true : n.kind === "end" ? finished : n.order <= cursor);
  const isCurrent = (n: NodeBox) => n.kind === "call" && n.order === cursor;

  const path = (e: Edge) => {
    if (e.vertical) {
      const x1 = e.from.x + W / 2;
      const y1 = e.from.y + H;
      const x2 = e.to.x + W / 2;
      const y2 = e.to.y;
      return `M ${x1} ${y1} C ${x1} ${y1 + 36}, ${x2} ${y2 - 36}, ${x2} ${y2}`;
    }
    const x1 = e.from.x + W;
    const y1 = e.from.y + H / 2;
    const x2 = e.to.x;
    const y2 = e.to.y + H / 2;
    const dx = Math.max(24, (x2 - x1) / 2);
    return `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
  };

  return (
    <Box ref={host} overflow="hidden" h={`${height * scale}px`}>
      <Box position="relative" w={`${width}px`} h={`${height}px`} mx={scale < 1 ? 0 : "auto"} transform={`scale(${scale})`} transformOrigin="top left" transition="transform .4s ease">
        <svg width={width} height={height} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
          <defs>
            <linearGradient id="rfFlow" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0" stopColor="var(--chakra-colors-brand-solid)" />
              <stop offset="1" stopColor="var(--chakra-colors-logo-solid)" />
            </linearGradient>
          </defs>
          {edges.map((e, i) => {
            const done = reached(e.to);
            const flowing = e.to.kind === "end" ? finished && cursor > 0 && !reached(e.to) : isCurrent(e.to);
            const d = path(e);
            return (
              <g key={i}>
                <path d={d} fill="none" stroke="var(--chakra-colors-hairline-strong)" strokeWidth="2" />
                {done && <path d={d} fill="none" stroke="var(--chakra-colors-brand-solid)" strokeWidth="2.5" strokeDasharray="600" strokeDashoffset="600" style={{ animation: "draw .5s ease-out forwards" }} />}
                {flowing && <path d={d} fill="none" stroke="url(#rfFlow)" strokeWidth="3" strokeDasharray="7 7" style={{ animation: "dashMove .6s linear infinite" }} />}
                {e.label && (
                  <text
                    x={e.vertical ? e.from.x + W / 2 + 10 : (e.from.x + W + e.to.x) / 2}
                    y={e.vertical ? (e.from.y + H + e.to.y) / 2 + 4 : e.from.y + H / 2 - 8}
                    fill={done ? "var(--chakra-colors-brand-fg)" : "var(--chakra-colors-fg-subtle)"}
                    fontFamily="JetBrains Mono Variable, monospace"
                    fontSize="10.5"
                    textAnchor={e.vertical ? "start" : "middle"}
                  >
                    {e.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {nodes.map((n) => {
          const on = reached(n);
          const cur = isCurrent(n);
          const tier = n.call ? (n.call.li === 0 ? "8B" : "70B") : "";
          const Icon = n.kind === "start" ? Bot : n.kind === "end" ? Gavel : (TOOL_ICON[n.call!.t.name] ?? Wrench);
          const endColor = n.kind === "end" && finished ? (verdict.good ? "brand.solid" : "red.solid") : undefined;
          return (
            <Box
              key={n.key}
              as={n.kind === "call" ? "button" : "div"}
              onClick={n.kind === "call" ? () => onJump(n.order) : undefined}
              position="absolute"
              left={`${n.x}px`}
              top={`${n.y}px`}
              w={`${W}px`}
              h={`${H}px`}
              textAlign="left"
              bg={endColor ?? (cur ? "brand.solid" : "surface")}
              color={endColor ? (verdict.good ? "#0c0e11" : "white") : cur ? "#0c0e11" : "fg"}
              borderWidth="1px"
              borderColor={cur ? "brand.solid" : on ? "brand.emphasized" : "hairline"}
              borderRadius="xl"
              px="3"
              py="2"
              opacity={on || cur ? 1 : 0.45}
              boxShadow={cur ? "0 0 0 5px var(--chakra-colors-brand-muted), 0 14px 30px -14px rgba(201,239,60,.6)" : "card"}
              transform={cur ? "translateY(-2px) scale(1.04)" : "none"}
              transition="all .35s cubic-bezier(.34,1.4,.64,1)"
              cursor={n.kind === "call" ? "pointer" : "default"}
            >
              <HStack justify="space-between" mb="1">
                <HStack gap="1.5" minW="0">
                  <Icon size={14} strokeWidth={2.2} style={{ flexShrink: 0 }} />
                  <Text fontFamily="mono" fontSize="11.5px" fontWeight="semibold" truncate>
                    {n.kind === "start" ? "agent run" : n.kind === "end" ? "verdict" : n.call!.t.name}
                  </Text>
                </HStack>
                {tier && (
                  <Text fontFamily="mono" fontSize="9.5px" px="1.5" borderRadius="sm" bg={cur ? "blackAlpha.200" : n.call!.li === 0 ? "brand.muted" : "pink.900"} color={cur ? "#0c0e11" : n.call!.li === 0 ? "brand.fg" : "logo.fg"}>
                    {tier}
                  </Text>
                )}
              </HStack>
              <Text fontFamily="mono" fontSize="10px" opacity={0.75} truncate>
                {n.kind === "start" ? `${steps} steps` : n.kind === "end" ? (finished ? verdict.title : "…") : n.call!.t.args || "–"}
              </Text>
            </Box>
          );
        })}
        {lanes[1]?.status === "skipped" && (
          <Text position="absolute" left={`${PAD + COL}px`} top={`${ROW_A + H + 14}px`} fontFamily="mono" fontSize="10.5px" color="fg.subtle">
            70B not needed: the screener cleared the run
          </Text>
        )}
      </Box>
    </Box>
  );
}
