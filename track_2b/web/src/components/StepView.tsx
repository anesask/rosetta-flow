import { Box, Grid, HStack, Stack, Text } from "@chakra-ui/react";
import type { ReactNode } from "react";

import type { Span } from "../api";

/** Wraps every occurrence of a quote in <mark>; text stays text (never HTML). */
export function marked(text: string, quotes: string[]): ReactNode[] {
  const qs = quotes.filter((q) => q && q.length > 3 && text.includes(q));
  const out: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < text.length) {
    let best: [number, string] | null = null;
    for (const q of qs) {
      const j = text.indexOf(q, i);
      if (j >= 0 && (!best || j < best[0])) best = [j, q];
    }
    if (!best) {
      out.push(text.slice(i));
      break;
    }
    out.push(text.slice(i, best[0]));
    out.push(<mark key={k++}>{best[1]}</mark>);
    i = best[0] + best[1].length;
  }
  return out;
}

const scalar = (v: unknown) => (v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** A tool's arguments or answer as a field / value table; nested values stay compact JSON. Full content, no cut-off. */
export function KeyValues({ value, quotes = [], dense = false }: { value: unknown; quotes?: string[]; dense?: boolean }) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return (
      <Text fontFamily="mono" fontSize="12px" whiteSpace="pre-wrap" overflowWrap="anywhere">
        {marked(scalar(value), quotes)}
      </Text>
    );
  }
  const entries = Object.entries(value as Record<string, unknown>);
  return (
    <Grid templateColumns="minmax(90px, max-content) minmax(0, 1fr)" columnGap="4" rowGap={dense ? "0.5" : "1"} fontFamily="mono" fontSize="12px">
      {entries.map(([k, v]) => (
        <Box key={k} display="contents">
          <Text color="fg.muted">{k}</Text>
          <Text whiteSpace="pre-wrap" overflowWrap="anywhere" color={v === null ? "fg.subtle" : "fg"}>
            {marked(Array.isArray(v) && v.every((x) => typeof x !== "object") ? v.join(", ") : scalar(v), quotes)}
          </Text>
        </Box>
      ))}
    </Grid>
  );
}

export const STEP_LABEL: Record<string, string> = {
  user_message: "Customer",
  agent_message: "Agent",
  llm_reasoning: "Agent, thinking",
  tool_call: "Agent calls a tool",
  tool_result: "Tool answers",
};

export type StepMarks = { broke?: boolean; cited?: boolean; readBy?: 0 | 1; current?: boolean };

/** Small markers shown next to a step: broken, cited, which tier read it. */
export function StepBadges({ marks }: { marks: StepMarks }) {
  return (
    <HStack gap="1.5" flexWrap="wrap">
      {marks.broke && (
        <Text as="span" fontFamily="mono" fontSize="10px" px="1.5" borderRadius="sm" bg="orange.subtle" color="orange.fg">
          you broke this
        </Text>
      )}
      {marks.cited && (
        <Text as="span" fontFamily="mono" fontSize="10px" px="1.5" borderRadius="sm" bg="red.subtle" color="red.fg">
          cited by the auditor
        </Text>
      )}
      {marks.readBy !== undefined && (
        <Text as="span" fontFamily="mono" fontSize="10px" px="1.5" borderRadius="sm" bg={marks.readBy === 0 ? "brand.muted" : "pink.900"} color={marks.readBy === 0 ? "brand.fg" : "logo.fg"}>
          read by {marks.readBy === 0 ? "8B" : "70B"}
        </Text>
      )}
    </HStack>
  );
}

/** A tool call and its answer as one block: tool name, what the tool does, arguments, the full answer. */
export function ToolBlock({ call, result, doc, quotes, marksCall, marksResult }: { call: Span; result?: Span; doc?: string; quotes: string[]; marksCall: StepMarks; marksResult: StepMarks }) {
  const bad = marksCall.broke || marksResult.broke;
  return (
    <Box borderWidth="1px" borderColor={marksCall.cited || marksResult.cited ? "red.solid" : bad ? "orange.emphasized" : "hairline"} bg={bad ? "orange.subtle" : "surface"} borderRadius="lg" overflow="hidden">
      <Stack gap="1" px="3.5" py="2.5" borderBottomWidth={result ? "1px" : "0"} borderColor="hairline">
        <HStack gap="2" flexWrap="wrap">
          <Text fontFamily="mono" fontSize="11px" color="fg.subtle">
            {call.id}
          </Text>
          <Text fontSize="12px" fontWeight="semibold" color="fg.muted">
            calls
          </Text>
          <Text fontFamily="mono" fontSize="13px" fontWeight="semibold">
            {call.tool}
          </Text>
          <StepBadges marks={marksCall} />
        </HStack>
        {doc && (
          <Text fontSize="12px" color="fg.muted">
            {doc}
          </Text>
        )}
        <KeyValues value={call.args ?? {}} quotes={quotes} dense />
      </Stack>
      {result && (
        <Stack gap="1" px="3.5" py="2.5" bg={bad ? undefined : "surfaceSunken"}>
          <HStack gap="2" flexWrap="wrap">
            <Text fontFamily="mono" fontSize="11px" color="fg.subtle">
              {result.id}
            </Text>
            <Text fontSize="12px" fontWeight="semibold" color={result.status === "error" ? "red.fg" : "fg.muted"}>
              {result.status === "error" ? "answer: error" : "answer"}
            </Text>
            <StepBadges marks={marksResult} />
          </HStack>
          <KeyValues value={result.result ?? result.status ?? ""} quotes={quotes} />
        </Stack>
      )}
    </Box>
  );
}

/** A message (customer, agent, agent note) in full. */
export function MessageBlock({ span, quotes, marks }: { span: Span; quotes: string[]; marks: StepMarks }) {
  const customer = span.kind === "user_message";
  const note = span.kind === "llm_reasoning";
  return (
    <Box
      borderWidth="1px"
      borderColor={marks.cited ? "red.solid" : marks.broke ? "orange.emphasized" : "hairline"}
      bg={marks.broke ? "orange.subtle" : customer ? "surface" : note ? "surfaceSunken" : "brand.subtle"}
      borderRadius="lg"
      px="3.5"
      py="2.5"
    >
      <HStack gap="2" mb="1" flexWrap="wrap">
        <Text fontFamily="mono" fontSize="11px" color="fg.subtle">
          {span.id}
        </Text>
        <Text fontSize="12px" fontWeight="semibold" color="fg.muted">
          {STEP_LABEL[span.kind] ?? span.kind}
        </Text>
        <StepBadges marks={marks} />
      </HStack>
      <Text fontSize="14px" lineHeight="1.55" whiteSpace="pre-wrap" overflowWrap="anywhere" fontStyle={note ? "italic" : "normal"}>
        {marked(span.text ?? "", quotes)}
      </Text>
    </Box>
  );
}

/** Pairs each tool call with its answer (by call id), keeping run order. */
export function pairSteps(spans: Span[]): ({ kind: "msg"; span: Span } | { kind: "tool"; call: Span; result?: Span })[] {
  const results = new Map(spans.filter((s) => s.kind === "tool_result" && s.call_id).map((s) => [s.call_id as string, s]));
  const used = new Set<string>();
  const out: ({ kind: "msg"; span: Span } | { kind: "tool"; call: Span; result?: Span })[] = [];
  for (const s of spans) {
    if (s.kind === "tool_call") {
      const r = s.call_id ? results.get(s.call_id) : undefined;
      if (r) used.add(r.id);
      out.push({ kind: "tool", call: s, result: r });
    } else if (s.kind === "tool_result") {
      if (!used.has(s.id)) out.push({ kind: "msg", span: s });
    } else out.push({ kind: "msg", span: s });
  }
  return out;
}
