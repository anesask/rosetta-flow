import { Box, Button, CloseButton, Dialog, Grid, HStack, IconButton, Image, Portal, Stack, Text } from "@chakra-ui/react";
import { ChevronLeft, ChevronRight, Pause, Play, Radio, SkipBack, SkipForward, Wrench } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { costOf, type Finding, PRICE, type Span, type TierResult, typeName } from "../api";
import logoMark from "../logo-mark.png";
import { type StageStatus, TOOL_ICON, type ToolCall } from "./Pipeline";
import { Chip, type Tone } from "./Surface";
import { PipelineGraph } from "./PipelineGraph";
import { MessageBlock, pairSteps, ToolBlock } from "./StepView";
import { Thinking } from "./Thinking";

export type Lane = { name: string; model: string; status: StageStatus; tools: ToolCall[]; res?: TierResult };
/** Measured on the held-out test set (fleet.json), used to show what the two tiers save at scale. */
export type FleetStats = { runs: number; per1000Two: number; per1000Alone: number; stopAt8B: number; faTwo: number; faAlone: number; clean: number };
type Props = {
  open: boolean;
  onClose: () => void;
  lanes: Lane[]; // screener first, confirmer second
  escalated: boolean | null;
  live: boolean;
  spans: Span[];
  toolDocs: Record<string, string>; // what each of the agent's own tools does
  broke: Set<string>;
  cited: Set<string>;
  findings: Finding[];
  findingsBy: string;
  avg70: number;
  fleet: FleetStats | null;
  verdict: { title: string; good: boolean | null };
};

const TONE: Record<StageStatus, Tone> = { idle: "muted", running: "brand", flagged: "red", cleared: "brand", skipped: "muted", failed: "amber" };
const STEP_MS = 1600;
const INTRO_MS = 900;
const KIND: Record<string, string> = { user_message: "Customer", agent_message: "Agent", llm_reasoning: "Agent note", tool_call: "Agent calls a tool", tool_result: "Tool answers" };

// What the auditor's own tools do, in plain words
const AUDIT_TOOL_DOC: Record<string, string> = {
  read_spans: "Opens steps of the agent run and reads them in full.",
  read_span: "Opens one step of the agent run and reads it in full.",
  list_spans: "Lists the steps of the run with a one-line preview each.",
  search: "Searches every step of the run for a word or pattern.",
  read_policy: "Reads the company policy the agent has to follow.",
  report: "Submits the verdict: findings with the steps and quoted evidence.",
  bookmark: "Marks a suspicious step for the next tier to look at.",
};

const openedIds = (t: ToolCall) => (t.name === "read_spans" || t.name === "read_span" ? t.args.split(",").map((x) => x.trim()).filter(Boolean) : []);

function didWhat(t: ToolCall): string {
  if (t.name.startsWith("read_span")) return `Opened step${openedIds(t).length > 1 ? "s" : ""} ${openedIds(t).join(", ")}`;
  if (t.name === "search") return `Searched for “${t.args}”`;
  if (t.name === "report") {
    const [verdict, types] = t.args.split(" · ");
    return verdict === "ok" ? "Verdict: no issues" : `Verdict: issues found${types ? ` · ${types.replaceAll("_", " ")}` : ""}`;
  }
  if (t.name === "list_spans") return "Listed the steps of the run";
  return t.args ? `${t.name}: ${t.args}` : t.name;
}


function LogoLoader({ label }: { label: string }) {
  return (
    <Stack align="center" justify="center" gap="5" py="24">
      <Box position="relative" w="104px" h="104px">
        <Box position="absolute" inset="0" borderRadius="full" bgImage="conic-gradient(from 0deg, transparent 0deg, var(--chakra-colors-brand-solid) 110deg, var(--chakra-colors-logo-solid) 220deg, transparent 300deg)" animation="spin 1.1s linear infinite" />
        <Box position="absolute" inset="4px" borderRadius="full" bg="canvas" />
        <Box position="absolute" inset="15px" borderRadius="24px" bg="logo.solid" display="grid" placeItems="center" animation="pop .5s ease-out">
          <Image src={logoMark} alt="rosetta-flow" w="46px" h="46px" />
        </Box>
      </Box>
      <Thinking verb={label} size="13px" />
    </Stack>
  );
}

type Call = { t: ToolCall; li: number; i: number };

/** The current tool call, large: what tool, what it does, what it did, and the steps it opened (with the agent's tool explained). */
function Focus({ call, lanes, spans, toolDocs, broke, step, total }: { call: Call | undefined; lanes: Lane[]; spans: Span[]; toolDocs: Record<string, string>; broke: Set<string>; step: number; total: number }) {
  if (!call) {
    return (
      <Stack align="center" justify="center" h="100%" gap="2" color="fg.muted" py="10">
        <Text fontSize="15px">Press play or step forward to follow the audit.</Text>
        <Text fontFamily="mono" fontSize="11px">{total} tool calls · ←/→ to step · space to play</Text>
      </Stack>
    );
  }
  const Icon = TOOL_ICON[call.t.name] ?? Wrench;
  const ids = openedIds(call.t);
  const opened = spans.filter((s) => ids.includes(s.id));
  return (
    <Stack key={step} gap="4" animation="pop .35s ease-out">
      <HStack gap="2" fontFamily="mono" fontSize="11px" color="fg.muted">
        <Text>
          step {step} of {total}
        </Text>
        <Text>·</Text>
        <Text color={call.li === 0 ? "brand.fg" : "logo.fg"}>{lanes[call.li]?.model}</Text>
      </HStack>
      <HStack gap="4" align="center">
        <Box w="56px" h="56px" borderRadius="xl" bg="brand.solid" color="#0c0e11" display="grid" placeItems="center" flexShrink={0} boxShadow="0 10px 30px -12px rgba(201,239,60,.6)">
          <Icon size={26} strokeWidth={2} />
        </Box>
        <Stack gap="0.5" minW="0">
          <Text fontFamily="mono" fontSize="22px" fontWeight="semibold" lineHeight="1.15">
            {call.t.name}
          </Text>
          <Text fontSize="14px" color="fg.muted">
            {AUDIT_TOOL_DOC[call.t.name] ?? "A tool of the auditor."}
          </Text>
        </Stack>
      </HStack>
      <Box bg="surfaceSunken" borderRadius="lg" px="4" py="3">
        <Text fontFamily="mono" fontSize="10px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted" mb="1">
          What it did
        </Text>
        <Text fontSize="16px" fontWeight="medium">
          {didWhat(call.t)}
        </Text>
      </Box>
      {opened.length > 0 && (
        <Stack gap="2">
          <Text fontFamily="mono" fontSize="10px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted">
            What it read
          </Text>
          {pairSteps(spans)
            .filter((p) => (p.kind === "tool" ? ids.includes(p.call.id) || (p.result ? ids.includes(p.result.id) : false) : ids.includes(p.span.id)))
            .map((p, k) => (
              <Box key={p.kind === "tool" ? p.call.id : p.span.id} animation={`pop .35s ease-out ${k * 0.08}s both`}>
                {p.kind === "tool" ? (
                  <ToolBlock call={p.call} result={p.result} doc={p.call.tool ? toolDocs[p.call.tool] : undefined} quotes={[]} marksCall={{ broke: broke.has(p.call.id) }} marksResult={p.result ? { broke: broke.has(p.result.id) } : {}} />
                ) : (
                  <MessageBlock span={p.span} quotes={[]} marks={{ broke: broke.has(p.span.id) }} />
                )}
              </Box>
            ))}
        </Stack>
      )}
    </Stack>
  );
}

/** "The investigation" player: a timeline of every tool call by tier, the current call explained, the transcript
 *  with the agent's tools explained, controls to play, pause and step, and the decision with what it saves. */
export function FlowDialog({ open, onClose, lanes, escalated, live, spans, toolDocs, broke, cited, findings, findingsBy, avg70, fleet, verdict }: Props) {
  const [intro, setIntro] = useState(true);
  const [cursor, setCursor] = useState(0); // number of calls shown; the focus is call cursor-1
  const [playing, setPlaying] = useState(false);
  const [follow, setFollow] = useState(true); // during a live audit, jump to each new call
  const listRef = useRef<HTMLDivElement | null>(null);

  const calls: Call[] = useMemo(() => lanes.flatMap((l, li) => l.tools.map((t, i) => ({ t, li, i }))), [lanes]);
  const total = calls.length;

  useEffect(() => {
    if (!open) return;
    setIntro(true);
    setCursor(0);
    setPlaying(false);
    const t = window.setTimeout(() => {
      setIntro(false);
      setCursor(live ? total : 0);
      setPlaying(!live);
    }, INTRO_MS);
    return () => window.clearTimeout(t);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) return;
    if (cursor >= total) {
      setPlaying(false);
      return;
    }
    const t = window.setTimeout(() => setCursor((k) => Math.min(total, k + 1)), cursor === 0 ? 300 : STEP_MS);
    return () => window.clearTimeout(t);
  }, [playing, cursor, total]);

  useEffect(() => {
    if (live && follow && !intro) setCursor(total);
  }, [total, live, follow, intro]);

  const step = useCallback(
    (d: number) => {
      setPlaying(false);
      setFollow(false);
      setCursor((k) => Math.max(0, Math.min(total, k + d)));
    },
    [total],
  );

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === " ") {
        e.preventDefault();
        setFollow(false);
        setPlaying((p) => (cursor >= total ? (setCursor(0), true) : !p));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, step, cursor, total]);

  const current = cursor > 0 ? calls[cursor - 1] : undefined;
  const openedBy = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of calls.slice(0, cursor)) for (const id of openedIds(c.t)) if (!m.has(id)) m.set(id, c.li);
    return m;
  }, [calls, cursor]);
  const nowIds = current ? openedIds(current.t) : [];
  const finished = verdict.good !== null && cursor >= total;

  useEffect(() => {
    if (!nowIds.length || !listRef.current) return;
    listRef.current.querySelector(`[data-steps~="${nowIds[0]}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [cursor]); // eslint-disable-line react-hooks/exhaustive-deps

  const waiting = intro || (live && total === 0);
  const screen = lanes[0]?.res;
  const confirm = lanes[1]?.res;
  const two = (screen ? costOf(screen) : 0) + (confirm ? costOf(confirm) : 0);
  const alone = ((confirm ? confirm.tokens : avg70) / 1e6) * PRICE["70B"];
  const chf = (x: number, d = 4) => `CHF ${x.toFixed(d)}`;

  return (
    <Dialog.Root open={open} onOpenChange={(e) => !e.open && onClose()} size="cover" motionPreset="slide-in-bottom">
      <Portal>
        <Dialog.Backdrop bg="blackAlpha.700" backdropFilter="blur(6px)" />
        <Dialog.Positioner>
          <Dialog.Content bg="canvas" borderWidth="1px" borderColor="hairline" borderRadius="2xl" maxW="1440px" h="90vh" overflow="hidden" display="flex" flexDirection="column">
            <Dialog.Header borderBottomWidth="1px" borderColor="hairline" py="3" flexShrink={0}>
              <HStack gap="3" w="100%">
                <Box w="28px" h="28px" borderRadius="md" bg="logo.solid" display="grid" placeItems="center">
                  <Image src={logoMark} alt="" w="19px" h="19px" />
                </Box>
                <Dialog.Title fontSize="15px" fontWeight="semibold">
                  The investigation
                </Dialog.Title>
                <Chip tone={live ? "brand" : "muted"} dot={live}>
                  {live ? "live" : "recorded"}
                </Chip>
              </HStack>
            </Dialog.Header>
            <Dialog.CloseTrigger asChild top="3" insetEnd="3">
              <CloseButton size="sm" />
            </Dialog.CloseTrigger>

            {waiting ? (
              <Box flex="1">
                <LogoLoader label={live ? "waiting for the first tool call" : "loading the investigation"} />
              </Box>
            ) : (
              <Grid flex="1" minH="0" templateColumns="minmax(0, 1fr)" templateRows="auto minmax(0, 1fr) auto auto">
                {/* pipeline graph */}
                <Box px="4" py="3" borderBottomWidth="1px" borderColor="hairline" bg="surfaceSunken" backgroundImage="linear-gradient(var(--chakra-colors-gridline) 1px, transparent 1px), linear-gradient(90deg, var(--chakra-colors-gridline) 1px, transparent 1px)" backgroundSize="24px 24px">
                  <PipelineGraph
                    lanes={lanes}
                    calls={calls}
                    cursor={cursor}
                    escalated={escalated}
                    verdict={verdict}
                    finished={finished}
                    steps={spans.length}
                    onJump={(k) => {
                      setPlaying(false);
                      setFollow(false);
                      setCursor(k);
                    }}
                  />
                </Box>

                {/* focus + transcript */}
                <Grid minH="0" templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) minmax(380px, 1fr)" }}>
                  <Box overflow="auto" px="6" py="5" borderRightWidth={{ lg: "1px" }} borderColor="hairline">
                    <Focus call={current} lanes={lanes} spans={spans} toolDocs={toolDocs} broke={broke} step={cursor} total={total} />
                  </Box>
                  <Box ref={listRef} overflow="auto" px="4" py="4">
                    <HStack justify="space-between" mb="2">
                      <Text fontFamily="mono" fontSize="11px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted">
                        Agent run · {openedBy.size}/{spans.length} steps read
                      </Text>
                      <HStack gap="2" fontFamily="mono" fontSize="9.5px" color="fg.subtle">
                        <HStack gap="1">
                          <Box w="7px" h="7px" borderRadius="sm" bg="brand.solid" />
                          <span>read by 8B</span>
                        </HStack>
                        <HStack gap="1">
                          <Box w="7px" h="7px" borderRadius="sm" bg="logo.solid" />
                          <span>read by 70B</span>
                        </HStack>
                      </HStack>
                    </HStack>
                    <Stack gap="2">
                      {pairSteps(spans).map((p) => {
                        const ids = p.kind === "tool" ? [p.call.id, ...(p.result ? [p.result.id] : [])] : [p.span.id];
                        const by = ids.map((id) => openedBy.get(id)).find((x) => x !== undefined) as 0 | 1 | undefined;
                        const now = ids.some((id) => nowIds.includes(id));
                        const mk = (id?: string) => (id ? { broke: broke.has(id), cited: finished && cited.has(id), readBy: openedBy.get(id) as 0 | 1 | undefined } : {});
                        return (
                          <Box
                            key={ids[0]}
                            data-steps={ids.join(" ")}
                            borderRadius="lg"
                            boxShadow={now ? "0 0 0 2px var(--chakra-colors-brand-solid)" : undefined}
                            opacity={by !== undefined || now ? 1 : 0.55}
                            transition="opacity .35s, box-shadow .35s"
                          >
                            {p.kind === "tool" ? (
                              <ToolBlock call={p.call} result={p.result} doc={p.call.tool ? toolDocs[p.call.tool] : undefined} quotes={[]} marksCall={mk(p.call.id)} marksResult={mk(p.result?.id)} />
                            ) : (
                              <MessageBlock span={p.span} quotes={[]} marks={mk(p.span.id)} />
                            )}
                          </Box>
                        );
                      })}
                    </Stack>
                  </Box>
                </Grid>

                {/* player controls */}
                <HStack justify="center" gap="2" py="2.5" borderTopWidth="1px" borderColor="hairline" bg="surfaceSunken">
                  <IconButton aria-label="first step" size="sm" variant="ghost" onClick={() => step(-total)} disabled={cursor === 0}>
                    <SkipBack size={16} />
                  </IconButton>
                  <IconButton aria-label="previous step" size="sm" variant="outline" borderColor="hairlineStrong" onClick={() => step(-1)} disabled={cursor === 0}>
                    <ChevronLeft size={18} />
                  </IconButton>
                  <IconButton
                    aria-label={playing ? "pause" : "play"}
                    w="44px"
                    h="44px"
                    borderRadius="full"
                    bg="brand.solid"
                    color="#0c0e11"
                    _hover={{ bg: "lime.400" }}
                    onClick={() => {
                      setFollow(false);
                      if (cursor >= total) setCursor(0);
                      setPlaying((p) => !p);
                    }}
                  >
                    {playing ? <Pause size={18} /> : <Play size={18} />}
                  </IconButton>
                  <IconButton aria-label="next step" size="sm" variant="outline" borderColor="hairlineStrong" onClick={() => step(1)} disabled={cursor >= total}>
                    <ChevronRight size={18} />
                  </IconButton>
                  <IconButton aria-label="last step" size="sm" variant="ghost" onClick={() => step(total)} disabled={cursor >= total}>
                    <SkipForward size={16} />
                  </IconButton>
                  <Text fontFamily="mono" fontSize="12px" color="fg.muted" w="96px" textAlign="center">
                    {cursor} / {total}
                  </Text>
                  {live && (
                    <Button size="xs" variant={follow ? "solid" : "outline"} colorPalette="gray" onClick={() => setFollow((f) => !f)} fontFamily="mono">
                      <Radio size={12} /> follow live
                    </Button>
                  )}
                </HStack>

                {/* decision + benefit */}
                <Grid templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) auto" }} gap="5" alignItems="center" px="6" py="3" borderTopWidth="1px" borderColor="hairline" bg="surface">
                  <HStack gap="4" minW="0">
                    <Box px="4" py="2" borderRadius="lg" bg={!finished ? "surfaceSunken" : verdict.good ? "brand.solid" : "red.solid"} color={!finished ? "fg.muted" : verdict.good ? "#0c0e11" : "white"} fontWeight="semibold" fontSize="16px" minW="140px" textAlign="center" animation={finished ? "pop .4s ease-out" : undefined}>
                      {finished ? verdict.title : "…"}
                    </Box>
                    <Stack gap="0.5" minW="0">
                      <Text fontFamily="mono" fontSize="10px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted">
                        Decision{findingsBy ? ` · ${findingsBy}` : ""}
                      </Text>
                      {finished && findings.length > 0 ? (
                        <Text fontSize="12.5px" lineClamp={2}>
                          <Text as="span" fontWeight="semibold" textTransform="capitalize">
                            {typeName(findings[0].error_type)}
                          </Text>{" "}
                          <Text as="span" fontFamily="mono" color="fg.muted">
                            at {findings[0].span_ids.join(", ")}
                          </Text>{" "}
                          · {findings[0].explanation}
                        </Text>
                      ) : (
                        <Text fontSize="12.5px" color="fg.muted">
                          {finished ? "No findings: the run was cleared." : "Shown after the last tool call."}
                        </Text>
                      )}
                    </Stack>
                  </HStack>
                  <HStack gap="2" align="stretch">
                    <Benefit label="this run" value={screen ? chf(two) : "–"} sub={screen ? `vs ${chf(alone)} with the 70B alone` : "two tiers"} />
                    <Benefit
                      label="per 1,000 runs"
                      value={fleet ? chf(fleet.per1000Two, 2) : "–"}
                      sub={fleet ? `saves ${chf(fleet.per1000Alone - fleet.per1000Two, 2)} (${Math.round((100 * (fleet.per1000Alone - fleet.per1000Two)) / fleet.per1000Alone)}%) vs 70B alone` : "measured on the test set"}
                      good
                    />
                    <Benefit label="never reach the 70B" value={fleet ? `${Math.round(fleet.stopAt8B * 100)}%` : "–"} sub="of runs stop at the small GPU" good />
                    <Benefit label="false alarms" value={fleet ? `${fleet.faTwo} vs ${fleet.faAlone}` : "–"} sub={fleet ? `${Math.round((100 * (fleet.faAlone - fleet.faTwo)) / Math.max(1, fleet.faAlone))}% fewer runs for a person to review` : "two tiers vs 70B alone"} good />
                  </HStack>
                </Grid>
              </Grid>
            )}
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}

function Benefit({ label, value, sub, good }: { label: string; value: string; sub: string; good?: boolean }) {
  return (
    <Box bg={good ? "brand.subtle" : "canvas"} borderWidth="1px" borderColor={good ? "brand.emphasized" : "hairline"} borderRadius="md" px="3" py="2" w="176px">
      <Text fontFamily="mono" fontSize="9px" color="fg.subtle" textTransform="uppercase" letterSpacing="0.06em">
        {label}
      </Text>
      <Text fontFamily="mono" fontSize="15px" fontWeight="semibold" color={good ? "brand.fg" : "fg"} lineHeight="1.3">
        {value}
      </Text>
      <Text fontSize="10.5px" color="fg.muted" lineHeight="1.3">
        {sub}
      </Text>
    </Box>
  );
}
