import { Box, Button, HStack, Text } from "@chakra-ui/react";
import { type ReactNode, useState } from "react";

import type { Span } from "../api";

/** Wraps every occurrence of a quote in <mark>; text stays text (never HTML). */
function marked(text: string, quotes: string[]): ReactNode[] {
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

const KIND: Record<string, string> = {
  user_message: "Customer",
  agent_message: "Agent",
  llm_reasoning: "Agent, thinking",
  tool_call: "calls",
  tool_result: "returns",
  other: "Other",
};

function Tag({ children, palette }: { children: ReactNode; palette: "amber" | "red" | "gray" }) {
  const c = { amber: { bg: "orange.subtle", color: "orange.fg" }, red: { bg: "red.subtle", color: "red.fg" }, gray: { bg: "bg.muted", color: "fg.muted" } }[palette];
  return (
    <Text as="span" fontSize="11px" fontWeight="semibold" px="2" py="0.5" borderRadius="chip" bg={c.bg} color={c.color} whiteSpace="nowrap">
      {children}
    </Text>
  );
}

type RowProps = { span: Span; broke: boolean; cited: boolean; quotes: string[]; open: boolean };

function ToolRow({ span, broke, cited, quotes, open }: RowProps) {
  const [expanded, setExpanded] = useState(false);
  const show = open || expanded || broke || cited;
  const code = span.kind === "tool_call" ? `${span.tool}(${JSON.stringify(span.args ?? {})})` : JSON.stringify(span.result, null, 1);
  const summary = span.kind === "tool_call" ? `${span.tool}(${JSON.stringify(span.args ?? {})})` : JSON.stringify(span.result ?? span.status ?? "");
  return (
    <Box id={`step-${span.id}`} pl="3" borderLeftWidth="3px" borderLeftColor={cited ? "red.solid" : broke ? "orange.solid" : "transparent"} bg={broke ? "orange.subtle" : undefined} borderRadius="sm" py="1">
      <HStack gap="2" fontFamily="mono" fontSize="12px" flexWrap="wrap">
        <Text color="fg.subtle" w="7">
          {span.id}
        </Text>
        <Text color="fg.muted">{KIND[span.kind]}</Text>
        {!show && (
          <Button size="2xs" variant="ghost" onClick={() => setExpanded(true)} fontFamily="mono" fontWeight="normal" color="fg" px="1" h="auto" minH="0" lineHeight="1.6" maxW="100%" whiteSpace="normal" textAlign="start" overflowWrap="anywhere">
            {summary.length > 110 ? summary.slice(0, 110) + "…" : summary}
          </Button>
        )}
        {broke && <Tag palette="amber">you broke this</Tag>}
        {cited && <Tag palette="red">cited</Tag>}
        {span.kind === "tool_result" && span.status === "error" && <Tag palette="gray">error</Tag>}
      </HStack>
      {show && (
        <Box mt="1" ml="9" fontFamily="mono" fontSize="12px" bg="surfaceSunken" px="3" py="2" borderRadius="md" whiteSpace="pre-wrap" overflowWrap="anywhere">
          {marked(code, quotes)}
        </Box>
      )}
    </Box>
  );
}

function MessageRow({ span, broke, cited, quotes }: RowProps) {
  const customer = span.kind === "user_message";
  return (
    <HStack id={`step-${span.id}`} align="start" gap="3" justify={customer ? "flex-start" : "flex-end"}>
      {customer && (
        <Text fontFamily="mono" fontSize="12px" color="fg.subtle" pt="2.5" w="7" flexShrink={0}>
          {span.id}
        </Text>
      )}
      <Box
        maxW="78%"
        bg={customer ? "surfaceSunken" : broke ? "orange.subtle" : "brand.subtle"}
        borderWidth="1px"
        borderColor={cited ? "red.solid" : broke ? "orange.emphasized" : "transparent"}
        borderRadius="xl"
        borderTopLeftRadius={customer ? "sm" : "xl"}
        borderTopRightRadius={customer ? "xl" : "sm"}
        px="4"
        py="2.5"
      >
        <HStack gap="2" mb="1">
          <Text fontSize="11px" fontWeight="semibold" color="fg.muted">
            {KIND[span.kind] ?? span.kind}
          </Text>
          {broke && <Tag palette="amber">you broke this</Tag>}
          {cited && <Tag palette="red">cited by the auditor</Tag>}
        </HStack>
        <Text fontSize="14px" lineHeight="1.55" whiteSpace="pre-wrap" overflowWrap="anywhere">
          {marked(span.text ?? "", quotes)}
        </Text>
      </Box>
      {!customer && (
        <Text fontFamily="mono" fontSize="12px" color="fg.subtle" pt="2.5" w="7" flexShrink={0}>
          {span.id}
        </Text>
      )}
    </HStack>
  );
}

export type TranscriptProps = { spans: Span[]; broke?: Set<string>; cited?: Set<string>; quotes?: string[]; openTools?: boolean };

/** The agent run as a conversation: messages as bubbles, tool calls as one-line rows (expand on click). */
export function Transcript({ spans, broke = new Set(), cited = new Set(), quotes = [], openTools = false }: TranscriptProps) {
  return (
    <Box display="grid" gridTemplateColumns="minmax(0, 1fr)" gap="2.5">
      {spans.map((s) => {
        const p = { span: s, broke: broke.has(s.id), cited: cited.has(s.id), quotes, open: openTools };
        return s.kind === "tool_call" || s.kind === "tool_result" ? <ToolRow key={s.id} {...p} /> : <MessageRow key={s.id} {...p} />;
      })}
    </Box>
  );
}
