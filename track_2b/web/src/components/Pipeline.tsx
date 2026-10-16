import { Box, Grid, HStack, Stack, Text } from "@chakra-ui/react";
import { Bookmark, BookOpen, FileCheck2, FileText, ListTree, type LucideIcon, Search, Wrench } from "lucide-react";
import type { ReactNode } from "react";

import { Chip, type Tone } from "./Surface";
import { Thinking, thinkingVerb } from "./Thinking";

export type StageStatus = "idle" | "running" | "flagged" | "cleared" | "skipped" | "failed";
export type ToolCall = { name: string; args: string; bad?: boolean };
export type Stat = { label: string; value: string };
export type Node = {
  kind: string;
  title: string;
  status: StageStatus;
  statusText?: string;
  icon?: LucideIcon;
  stats?: Stat[]; // three equal cells under the title
  note?: string; // one short line under the stats
  meta?: string; // free text (used when there are no stats)
  tools?: ToolCall[];
  big?: boolean;
  outcome?: "success" | "error"; // verdict card: animated check or cross
  toolsFromStart?: boolean; // show the first three tool rows (a chain), not the latest three
};

const TONE: Record<StageStatus, Tone> = { idle: "muted", running: "brand", flagged: "red", cleared: "brand", skipped: "muted", failed: "amber" };
const LABEL: Record<StageStatus, string> = { idle: "idle", running: "running", flagged: "flagged", cleared: "cleared", skipped: "skipped", failed: "no report" };
const BORDER: Record<StageStatus, string> = { idle: "hairline", running: "brand.solid", flagged: "red.emphasized", cleared: "brand.emphasized", skipped: "hairline", failed: "orange.emphasized" };
export const TOOL_ICON: Record<string, LucideIcon> = {
  read_spans: FileText,
  read_span: FileText,
  list_spans: ListTree,
  search: Search,
  read_policy: BookOpen,
  report: FileCheck2,
  bookmark: Bookmark,
};

const BRAND_SWEEP =
  "conic-gradient(from 0deg, transparent 0deg, var(--chakra-colors-brand-solid) 70deg, var(--chakra-colors-logo-solid) 140deg, transparent 200deg, transparent 360deg)";

/** Same tool called again in a row: one row with a count and the union of its arguments. */
function groupTools(tools: ToolCall[]): { name: string; n: number; args: string; bad: boolean }[] {
  const out: { name: string; n: number; args: string[]; bad: boolean }[] = [];
  for (const t of tools) {
    const last = out[out.length - 1];
    if (last && last.name === t.name && !t.bad && !last.bad) {
      last.n += 1;
      if (t.args && !last.args.includes(t.args)) last.args.push(t.args);
    } else out.push({ name: t.name, n: 1, args: t.args ? [t.args] : [], bad: !!t.bad });
  }
  return out.map((g) => ({ name: g.name, n: g.n, args: g.args.join(" · "), bad: g.bad }));
}

/** Verdict mark: a check that draws itself with a ripple, or a cross that draws and shakes. */
function OutcomeMark({ outcome }: { outcome: "success" | "error" }) {
  const ok = outcome === "success";
  const color = ok ? "var(--chakra-colors-brand-solid)" : "var(--chakra-colors-red-solid)";
  return (
    <Box position="relative" w="44px" h="44px" flexShrink={0} animation={ok ? undefined : "shake .5s ease-in-out .55s 1"}>
      <Box position="absolute" inset="0" borderRadius="full" borderWidth="2px" borderColor={ok ? "brand.solid" : "red.solid"} animation="ping 1s ease-out .45s 2" opacity={0} />
      <svg viewBox="0 0 44 44" width="44" height="44">
        <circle cx="22" cy="22" r="19" fill="none" stroke={color} strokeWidth="3" strokeDasharray="120" strokeDashoffset="120" style={{ animation: "draw .5s ease-out forwards" }} />
        {ok ? (
          <path d="M13 22.5l6 6 12-13" fill="none" stroke={color} strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" strokeDasharray="30" strokeDashoffset="30" style={{ animation: "draw .35s ease-out .45s forwards" }} />
        ) : (
          <path d="M15 15l14 14M29 15L15 29" fill="none" stroke={color} strokeWidth="3.4" strokeLinecap="round" strokeDasharray="40" strokeDashoffset="40" style={{ animation: "draw .35s ease-out .45s forwards" }} />
        )}
      </svg>
    </Box>
  );
}

/** One node card, same structure everywhere: icon + label + status, title, three stat cells, a note,
 *  and the tool calls grouped by tool. While running, a lime-to-pink light sweeps around its border. */
export function NodeCard({ node, children }: { node: Node; children?: ReactNode }) {
  const active = node.status === "running";
  const tools = node.tools ?? [];
  const groups = groupTools(tools);
  return (
    <Box position="relative" borderRadius="card" p={active ? "1px" : "0"} overflow="hidden" minW="0" h="100%" boxShadow={active ? "0 0 32px -6px rgba(255,95,166,0.35), 0 0 24px -8px rgba(201,239,60,0.4)" : undefined} transition="box-shadow .3s">
      {active && <Box position="absolute" top="50%" left="50%" w="300%" aspectRatio="1" bgImage={BRAND_SWEEP} animation="spinC 2.2s linear infinite" pointerEvents="none" />}
      <Box
        position="relative"
        h="100%"
        display="flex"
        flexDirection="column"
        bg="surface"
        borderWidth={active ? "0" : "1px"}
        borderColor={BORDER[node.status]}
        borderRadius={active ? "calc(var(--chakra-radii-card) - 1px)" : "card"}
        boxShadow={active ? undefined : "card"}
        px="4"
        py="3.5"
        opacity={node.status === "skipped" ? 0.5 : 1}
        transition="border-color .25s, opacity .25s"
        minW="0"
      >
        <HStack justify="space-between" gap="2" mb="2.5" h="22px">
          <HStack gap="2" minW="0">
            <Text fontFamily="mono" fontSize="10.5px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted" truncate>
              {node.kind}
            </Text>
          </HStack>
          <Chip tone={TONE[node.status]} dot={active}>
            {node.statusText ?? LABEL[node.status]}
          </Chip>
        </HStack>

        <HStack gap="3" align="center" h="44px">
          {node.outcome && <OutcomeMark key={node.outcome + node.title} outcome={node.outcome} />}
          <Text fontSize={node.big ? "24px" : "16px"} fontWeight="semibold" letterSpacing="-0.01em" lineHeight="1.15" color={node.big ? (node.status === "cleared" ? "brand.fg" : node.status === "flagged" ? "red.fg" : "fg") : "fg"} truncate>
            {node.title}
          </Text>
        </HStack>

        {node.stats && (
          <Grid templateColumns={`repeat(${node.stats.length}, 1fr)`} gap="1.5" mt="3">
            {node.stats.map((s) => (
              <Box key={s.label} bg="surfaceSunken" borderRadius="md" px="2" py="1.5" minW="0">
                <Text fontFamily="mono" fontSize="13px" fontWeight="medium" lineHeight="1.2" truncate fontVariantNumeric="tabular-nums">
                  {s.value}
                </Text>
                <Text fontFamily="mono" fontSize="9.5px" color="fg.subtle" textTransform="uppercase" letterSpacing="0.06em" truncate>
                  {s.label}
                </Text>
              </Box>
            ))}
          </Grid>
        )}
        {(node.note || node.meta) && (
          <Text fontFamily="mono" fontSize="11px" color="fg.muted" mt="2.5" whiteSpace="pre-wrap" lineClamp={2} minH="32px">
            {node.note ?? node.meta}
          </Text>
        )}

        {node.tools !== undefined && (
          <Stack gap="1" mt="2.5" h="98px" overflow="hidden">
            {(node.toolsFromStart ? groups.slice(0, 3) : groups.slice(-3)).map((g, i, arr) => {
              // key by position in the whole list, so only a new row mounts and pops in
              const at = node.toolsFromStart ? i : Math.max(0, groups.length - 3) + i;
              const ToolIcon = TOOL_ICON[g.name] ?? Wrench;
              const live = active && i === arr.length - 1;
              const rowBg = g.bad ? "red.subtle" : live ? "brand.muted" : "surfaceSunken";
              const rowFg = g.bad ? "red.fg" : live ? "brand.fg" : "fg";
              return (
                <HStack key={`${at}-${g.name}`} gap="1.5" fontFamily="mono" fontSize="10.5px" px="1.5" py="1" borderRadius="sm" bg={rowBg} color={rowFg} transition="background-color .3s, color .3s" animation="pop .35s ease-out" minW="0" title={g.args}>
                  <ToolIcon size={12} strokeWidth={2} style={{ flexShrink: 0 }} />
                  <Text as="span" fontWeight="medium" flexShrink={0}>
                    {g.name}
                  </Text>
                  {g.n > 1 && (
                    <Text as="span" color="fg.muted" flexShrink={0}>
                      ×{g.n}
                    </Text>
                  )}
                  <Text as="span" color="fg.muted" truncate>
                    {g.args}
                  </Text>
                </HStack>
              );
            })}
            {active && (
              <Box px="1.5" pt="0.5">
                <Thinking verb={thinkingVerb(tools[tools.length - 1]?.name)} />
              </Box>
            )}
          </Stack>
        )}
        {children}
      </Box>
    </Box>
  );
}

/** A connector between two nodes: brand-coloured once the flow has passed; while it flows, a lime-to-pink
 *  gradient streams along it and a pulse travels from one node to the next. */
export function Edge({ on, flowing, label }: { on: boolean; flowing?: boolean; label?: string }) {
  const streamH = "linear-gradient(90deg, var(--chakra-colors-brand-solid), var(--chakra-colors-logo-solid), var(--chakra-colors-brand-solid))";
  const streamV = "linear-gradient(180deg, var(--chakra-colors-brand-solid), var(--chakra-colors-logo-solid), var(--chakra-colors-brand-solid))";
  return (
    <Box flex="0 0 auto" w={{ base: "100%", lg: "72px" }} h={{ base: "28px", lg: "auto" }} position="relative" display="flex" alignItems="center" justifyContent="center">
      <Box position="absolute" inset="0" display="flex" alignItems="center" justifyContent="center">
        <Box position="relative" w={{ base: "2px", lg: "100%" }} h={{ base: "100%", lg: "2px" }}>
          <Box
            position="absolute"
            inset="0"
            bg={flowing ? undefined : on ? "brand.solid" : "hairlineStrong"}
            backgroundImage={flowing ? { base: streamV, lg: streamH } : undefined}
            backgroundSize={flowing ? { base: "100% 200%", lg: "200% 100%" } : undefined}
            animation={flowing ? { base: "flowY 1.2s linear infinite", lg: "flowX 1.2s linear infinite" } : undefined}
            boxShadow={flowing ? "0 0 10px rgba(255,95,166,0.45)" : undefined}
            transition="background .25s"
          />
          {flowing && (
            <Box
              display={{ base: "none", lg: "block" }}
              position="absolute"
              top="-3px"
              w="8px"
              h="8px"
              borderRadius="full"
              bg="logo.solid"
              boxShadow="0 0 10px 2px rgba(255,95,166,0.7)"
              animation="travelX 1.1s ease-in-out infinite"
            />
          )}
        </Box>
      </Box>
      {label && (
        <Text position="relative" fontFamily="mono" fontSize="10px" px="1.5" py="0.5" bg="surfaceSunken" color={on || flowing ? "brand.fg" : "fg.subtle"} whiteSpace="nowrap" borderRadius="sm" maxW="70px" textAlign="center" lineHeight="1.2" truncate>
          {label}
        </Text>
      )}
    </Box>
  );
}

/** The dotted-grid canvas behind the nodes. */
export function Canvas({ children }: { children: ReactNode }) {
  return (
    <Box
      borderRadius="card"
      borderWidth="1px"
      borderColor="hairline"
      bg="surfaceSunken"
      backgroundImage="linear-gradient(var(--chakra-colors-gridline) 1px, transparent 1px), linear-gradient(90deg, var(--chakra-colors-gridline) 1px, transparent 1px)"
      backgroundSize="24px 24px"
      p={{ base: "4", lg: "6" }}
      position="relative"
    >
      {children}
    </Box>
  );
}

/** Small inline SVG flags: emoji flags do not render on Windows. */
const FLAGS: Record<string, JSX.Element> = {
  de: (
    <svg viewBox="0 0 5 3" width="16" height="11">
      <rect width="5" height="1" fill="#000" />
      <rect y="1" width="5" height="1" fill="#dd0000" />
      <rect y="2" width="5" height="1" fill="#ffce00" />
    </svg>
  ),
  fr: (
    <svg viewBox="0 0 3 2" width="16" height="11">
      <rect width="1" height="2" fill="#0055a4" />
      <rect x="1" width="1" height="2" fill="#fff" />
      <rect x="2" width="1" height="2" fill="#ef4135" />
    </svg>
  ),
  it: (
    <svg viewBox="0 0 3 2" width="16" height="11">
      <rect width="1" height="2" fill="#009246" />
      <rect x="1" width="1" height="2" fill="#fff" />
      <rect x="2" width="1" height="2" fill="#ce2b37" />
    </svg>
  ),
  en: (
    <svg viewBox="0 0 60 30" width="16" height="11" preserveAspectRatio="none">
      <rect width="60" height="30" fill="#012169" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#fff" strokeWidth="6" />
      <path d="M0,0 L60,30 M60,0 L0,30" stroke="#c8102e" strokeWidth="2.5" />
      <path d="M30,0 V30 M0,15 H60" stroke="#fff" strokeWidth="10" />
      <path d="M30,0 V30 M0,15 H60" stroke="#c8102e" strokeWidth="6" />
    </svg>
  ),
};
const LANG_NAME: Record<string, string> = { de: "German", fr: "French", it: "Italian", en: "English" };

/** Flag + two-letter code for the language the customer wrote in. */
export function Lang({ code }: { code: string }) {
  return (
    <HStack as="span" gap="1" title={`customer writes in ${LANG_NAME[code] ?? code}`} flexShrink={0}>
      <Box as="span" display="inline-flex" borderRadius="2px" overflow="hidden" boxShadow="0 0 0 1px var(--chakra-colors-hairline)">
        {FLAGS[code]}
      </Box>
      <Text as="span" fontFamily="mono" fontSize="10px" fontWeight="semibold" color="fg.muted" textTransform="uppercase" w="16px">
        {code}
      </Text>
    </HStack>
  );
}
