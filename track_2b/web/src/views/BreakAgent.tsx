import { Box, Button, Grid, HStack, IconButton, NativeSelect, Stack, Text } from "@chakra-ui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { costOf, type FleetRow, getJSON, type LiveEvent, type LiveInfo, type LiveRun, PRICE, shortModel, streamNDJSON, type TierResult, type Truth, typeName } from "../api";
import { FindingCard } from "../components/FindingCard";
import { Bot, Gavel, ScanSearch, ScrollText, ShieldCheck, Workflow } from "lucide-react";

import { Canvas, Edge, Lang, type Node, NodeCard, type Stat, type StageStatus, type ToolCall } from "../components/Pipeline";
import { Chip, Eyebrow, primaryButton, Surface } from "../components/Surface";
import { Thinking } from "../components/Thinking";
import { FlowDialog, type FleetStats } from "../components/FlowDialog";
import { toaster } from "../components/Toaster";
import { TranscriptDialog } from "../components/TranscriptDialog";
import { Transcript } from "../components/Transcript";

type Done = { verdict: string; caught: boolean; seconds: number };
type TierView = { status: StageStatus; meta: string; tools: ToolCall[]; res?: TierResult };
const IDLE: TierView = { status: "idle", meta: "", tools: [] };

const meta = (r: TierResult) => `${r.seconds}s · ${r.tool_calls} tool calls · ${(r.tokens / 1000).toFixed(1)}k tok · CHF ${costOf(r).toFixed(4)}`;
const statusOf = (r: TierResult): StageStatus => (r.failure ? "failed" : r.verdict === "ok" ? "cleared" : "flagged");
const DOMAIN: Record<string, string> = { refunds: "Refunds · customer support", manufacturing: "Shop floor · quality" };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function verdictNode(done: Done | null, truth: Truth, busy: boolean): Node {
  const base = { kind: "verdict", icon: Gavel, big: true };
  if (!done) return { ...base, title: busy ? "Working…" : "Waiting", status: "idle", statusText: busy ? "pending" : "idle", stats: [{ label: "truth", value: truth.sabotage ? "error" : "clean" }, { label: "verdict", value: "–" }, { label: "time", value: "–" }], note: busy ? "the tiers are working" : "pick a run, break it, audit" };
  const clean = !truth.sabotage;
  const good = clean ? done.verdict === "ok" : done.caught;
  const steps = (truth.span_ids ?? []).join(", ");
  const title = clean ? (good ? "Cleared" : "False alarm") : good ? "Caught" : done.verdict === "issues_found" ? "Wrong step" : "Missed";
  const note = clean
    ? good
      ? "clean run, the auditor agrees"
      : "clean run, but the auditor flagged it"
    : good
      ? `${typeName(truth.error_type)} at step ${steps}, quote verified`
      : done.verdict === "issues_found"
        ? `you broke step ${steps}, it cited other steps`
        : `you broke step ${steps}, the auditor said ok`;
  return {
    ...base,
    title,
    note,
    status: good ? "cleared" : "flagged",
    statusText: good ? "right" : "wrong",
    outcome: good ? "success" : "error",
    stats: [
      { label: "truth", value: clean ? "clean" : "error" },
      { label: "verdict", value: done.verdict === "ok" ? "ok" : done.verdict === "issues_found" ? "issues" : "failed" },
      { label: "time", value: `${done.seconds}s` },
    ],
  };
}

function tierStats(res?: TierResult): Stat[] {
  return [
    { label: "time", value: res ? `${res.seconds}s` : "–" },
    { label: "calls", value: res ? String(res.tool_calls) : "–" },
    { label: "tokens", value: res ? `${(res.tokens / 1000).toFixed(1)}k` : "–" },
  ];
}

function CostCell({ label, value, sub, good }: { label: string; value: string; sub: string; good?: boolean }) {
  return (
    <Box bg={good ? "brand.subtle" : "surface"} borderWidth="1px" borderColor={good ? "brand.emphasized" : "hairline"} borderRadius="lg" px="3.5" py="2.5" transition="background .3s, border-color .3s">
      <Text fontFamily="mono" fontSize="10px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted">
        {label}
      </Text>
      <Text fontFamily="mono" fontSize="16px" fontWeight="medium" mt="0.5" color={good ? "brand.fg" : "fg"} fontVariantNumeric="tabular-nums">
        {value}
      </Text>
      <Text fontFamily="mono" fontSize="11px" color="fg.muted" lineClamp={2}>
        {sub}
      </Text>
    </Box>
  );
}

/** This run's cost for the two tiers vs the 70B on every run; the avoided 70B audit is estimated from the fleet.
 *  Always rendered (placeholders before an audit) so the page does not jump when results arrive. */
function Savings({ screen, confirm, avg70, escalated }: { screen: TierResult | null; confirm: TierResult | null; avg70: number; escalated: boolean }) {
  const chf = (x: number) => `CHF ${x.toFixed(4)}`;
  if (!screen) {
    return (
      <Stack gap="2">
        <CostCell label="this run · two tiers" value="CHF –" sub="8B on every run, 70B only if flagged" />
        <CostCell label="this run · 70B on every run" value="CHF –" sub="the single-model alternative" />
        <CostCell label="saved by screening" value="CHF –" sub="appears after the audit" />
      </Stack>
    );
  }
  const two = costOf(screen) + (confirm ? costOf(confirm) : 0);
  const aloneTok = confirm ? confirm.tokens : avg70;
  const alone = (aloneTok / 1e6) * PRICE["70B"];
  return (
    <Stack gap="2">
      <CostCell label="this run · two tiers" value={chf(two)} sub={`8B ${(screen.tokens / 1000).toFixed(1)}k tok${confirm ? ` + 70B ${(confirm.tokens / 1000).toFixed(1)}k tok` : " · 70B skipped"}`} />
      <CostCell label="this run · 70B on every run" value={chf(alone)} sub={`70B ${(aloneTok / 1000).toFixed(1)}k tok${confirm ? "" : " (fleet average)"}`} />
      {escalated ? (
        <CostCell label="cost of screening first" value={`+${chf(costOf(screen))}`} sub={`${Math.round((100 * costOf(screen)) / alone)}% of one 70B audit, spent on screening`} />
      ) : (
        <CostCell label="saved by screening" value={chf(alone - two)} sub="one 70B audit avoided · fleet: ~44% of runs stop here" good />
      )}
    </Stack>
  );
}

export function BreakAgent() {
  const [info, setInfo] = useState<LiveInfo | null>(null);
  const [avg70, setAvg70] = useState(16000);
  const [fleetStats, setFleetStats] = useState<FleetStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<LiveRun | null>(null);
  const [sabotage, setSabotage] = useState("");
  const [busy, setBusy] = useState(false);
  const [spans, setSpans] = useState<LiveRun["spans"]>([]);
  const [truth, setTruth] = useState<Truth>({ sabotage: null });
  const [screener, setScreener] = useState<TierView>(IDLE);
  const [confirmer, setConfirmer] = useState<TierView>(IDLE);
  const [escalated, setEscalated] = useState<boolean | null>(null);
  const [screenResult, setScreenResult] = useState<TierResult | null>(null);
  const [result, setResult] = useState<TierResult | null>(null);
  const [done, setDone] = useState<Done | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [lastTool, setLastTool] = useState("");
  const [flowOpen, setFlowOpen] = useState(false);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const tick = useRef<number | null>(null);

  useEffect(() => {
    getJSON<LiveInfo>("/api/live")
      .then((d) => {
        setInfo(d);
        if (d.runs.length) select(d.runs[0]);
      })
      .catch((e: Error) => setError(e.message));
    getJSON<{ runs: FleetRow[] }>("/api/fleet")
      .then((d) => {
        const rs = d.runs;
        if (!rs.length) return;
        setAvg70(Math.round(rs.reduce((a, r) => a + r.tok70_alone, 0) / rs.length));
        const clean = rs.filter((r) => !r.error);
        setFleetStats({
          runs: rs.length,
          per1000Two: (rs.reduce((a, r) => a + r.tok8 * PRICE["8B"] + r.tok70 * PRICE["70B"], 0) / 1e6 / rs.length) * 1000,
          per1000Alone: (rs.reduce((a, r) => a + r.tok70_alone * PRICE["70B"], 0) / 1e6 / rs.length) * 1000,
          stopAt8B: rs.filter((r) => !r.escalated).length / rs.length,
          faTwo: clean.filter((r) => r.final === "issues_found").length,
          faAlone: clean.filter((r) => r.alone === "issues_found").length,
          clean: clean.length,
        });
      })
      .catch(() => undefined);
    return () => {
      if (tick.current) window.clearInterval(tick.current);
    };
  }, []);

  function select(r: LiveRun) {
    setRun(r);
    setSabotage("");
    setSpans(r.spans);
    reset();
  }

  function reset() {
    setTruth({ sabotage: null });
    setScreener(IDLE);
    setConfirmer(IDLE);
    setEscalated(null);
    setScreenResult(null);
    setResult(null);
    setDone(null);
    setError(null);
  }

  async function audit() {
    if (!run || busy) return;
    setBusy(true);
    reset();
    const t0 = Date.now();
    setElapsed(0);
    setLastTool("");
    tick.current = window.setInterval(() => setElapsed((Date.now() - t0) / 1000), 200);
    let last: TierResult | null = null;
    try {
      const url = `/api/live/${encodeURIComponent(run.trace_id)}?sabotage=${encodeURIComponent(sabotage)}`;
      for await (const ev of streamNDJSON<LiveEvent>(url)) {
        if (ev.event === "error") throw new Error(ev.message);
        if (ev.event === "run") {
          setSpans(ev.spans);
          setTruth(ev.truth);
        }
        if (ev.event === "tier") (ev.tier === "screener" ? setScreener : setConfirmer)({ status: "running", meta: "investigating the run with tools", tools: [] });
        if (ev.event === "tool") {
          const call = { name: ev.name, args: ev.args };
          setLastTool(`${ev.tier === "screener" ? "8B" : "70B"} · ${ev.name}${ev.args ? " " + ev.args : ""}`);
          (ev.tier === "screener" ? setScreener : setConfirmer)((t) => ({ ...t, tools: [...t.tools, call] }));
        }
        if (ev.event === "screened") {
          last = ev.result;
          setScreenResult(ev.result);
          setScreener((t) => ({ status: statusOf(ev.result), meta: meta(ev.result), res: ev.result, tools: t.tools.length ? t.tools : (ev.result.tools ?? []).map((name) => ({ name, args: "" })) }));
          setEscalated(ev.escalated);
          if (!ev.escalated) setConfirmer({ status: "skipped", meta: "not needed · the screener cleared the run", tools: [] });
        }
        if (ev.event === "confirmed") {
          last = ev.result;
          setConfirmer((t) => ({ status: statusOf(ev.result), meta: meta(ev.result), res: ev.result, tools: t.tools.length ? t.tools : (ev.result.tools ?? []).map((name) => ({ name, args: "" })) }));
        }
        if (ev.event === "done") {
          setResult(last);
          setDone({ verdict: ev.verdict, caught: ev.caught, seconds: ev.seconds });
          const sab = Boolean(sabotage);
          const good = sab ? ev.caught : ev.verdict === "ok";
          toaster.create({
            type: good ? "success" : "error",
            title: sab ? (good ? "Caught the injected error" : ev.verdict === "issues_found" ? "Flagged, but at the wrong step" : "Missed the injected error") : good ? "Clean run cleared" : "False alarm on a clean run",
            description: `${ev.seconds}s · ${ev.verdict === "ok" ? "verdict ok" : ev.verdict === "issues_found" ? "issues found" : "no report"}`,
          });
        }
      }
    } catch (e) {
      const msg = (e as Error).message;
      const busyServer = /another live audit/i.test(msg);
      setError(busyServer ? "Another audit is running" : `The audit did not finish: ${msg}`);
      toaster.create({
        type: "error",
        title: busyServer ? "Another audit is running" : "The audit did not finish",
        description: busyServer ? "One live audit at a time keeps API use fair. Try again in a few seconds." : msg,
      });
    } finally {
      if (tick.current) window.clearInterval(tick.current);
      setBusy(false);
    }
  }

  const cited = useMemo(() => new Set(result?.findings.flatMap((f) => f.span_ids) ?? []), [result]);
  const quotes = useMemo(() => result?.findings.flatMap((f) => f.evidence) ?? [], [result]);
  const broke = useMemo(() => new Set(truth.span_ids ?? []), [truth]);
  const sab = run?.sabotage.find((s) => s.name === sabotage);
  const groups = useMemo(() => {
    const g = new Map<string, LiveRun[]>();
    for (const r of info?.runs ?? []) g.set(r.domain, [...(g.get(r.domain) ?? []), r]);
    const order = ["de", "fr", "it", "en"];
    return [...g].map(([d, rs]) => [d, [...rs].sort((a, b) => order.indexOf(a.language) - order.indexOf(b.language) || a.intent.localeCompare(b.intent))] as const);
  }, [info]);

  // What the agent itself did: its tool calls in order, the one you broke marked (known once the audit starts)
  // Which tier read each step first (from the auditors' read_spans calls), for the transcript dialog
  const readBy = new Map<string, 0 | 1>();
  [screener.tools, confirmer.tools].forEach((ts, tier) =>
    ts.filter((t) => t.name.startsWith("read_span")).forEach((t) => t.args.split(",").map((x) => x.trim()).forEach((id) => id && !readBy.has(id) && readBy.set(id, tier as 0 | 1))),
  );
  const agentTools: ToolCall[] = spans
    .filter((sp) => sp.kind === "tool_call")
    .map((sp) => {
      const args = sp.args && typeof sp.args === "object" ? Object.values(sp.args as Record<string, unknown>).map(String).join(", ") : "";
      const result = spans.find((r) => r.kind === "tool_result" && (r as { call_id?: string }).call_id === (sp as { call_id?: string }).call_id);
      return { name: sp.tool ?? "tool", args, bad: broke.has(sp.id) || (result ? broke.has(result.id) : false) };
    });
  const firstCustomer = spans.find((sp) => sp.kind === "user_message")?.text ?? "";
  const customerQuote = firstCustomer ? `“${firstCustomer.length > 90 ? firstCustomer.slice(0, 90) + "…" : firstCustomer}”` : "the agent did its job correctly";
  const runNode: Node = {
    kind: "agent run",
    icon: Bot,
    title: run ? cap(run.intent) : "No run",
    stats: run
      ? [
          { label: "domain", value: run.domain === "manufacturing" ? "quality" : "refunds" },
          { label: "lang", value: run.language.toUpperCase() },
          { label: "steps", value: String(run.spans.length) },
        ]
      : undefined,
    note: sab ? `broken: ${sab.text.toLowerCase()}` : customerQuote,
    status: sabotage ? "flagged" : "idle",
    statusText: sabotage ? "stress test" : "clean run",
    tools: agentTools,
    toolsFromStart: true,
  };
  const screenerNode: Node = {
    kind: "screener",
    icon: ScanSearch,
    title: shortModel(info?.screener) || "Apertus 8B",
    stats: tierStats(screener.res),
    note: screener.res ? `tier 1 · CHF ${costOf(screener.res).toFixed(4)}` : "tier 1 · screens every run",
    status: screener.status,
    tools: screener.tools,
  };
  const confirmerNode: Node = {
    kind: "confirmer",
    icon: ShieldCheck,
    title: shortModel(info?.confirmer) || "Apertus 70B",
    stats: tierStats(confirmer.res),
    note: confirmer.status === "skipped" ? "tier 2 · skipped, run cleared" : confirmer.res ? `tier 2 · CHF ${costOf(confirmer.res).toFixed(4)}` : "tier 2 · only flagged runs",
    status: confirmer.status,
    tools: confirmer.tools,
  };
  const stage = confirmer.status === "running" ? "70B confirming" : screener.status === "running" ? "8B screening" : "starting";
  const confirmResult = result && result !== screenResult ? result : null;

  return (
    <Grid templateColumns={{ base: "1fr", lg: "260px minmax(0, 1fr)" }} gap="4" alignItems="start">
      <Box>
      <Surface p="2" position={{ lg: "fixed" }} top={{ lg: "80px" }} w={{ lg: "260px" }} zIndex="1">
        <HStack px="2" pt="2" mb="1" justify="space-between">
          <Eyebrow mb="0">Agent runs</Eyebrow>
          <Text fontFamily="mono" fontSize="10px" color="fg.subtle" pr="1">
            steps · language
          </Text>
        </HStack>
        {groups.map(([domain, runs]) => (
          <Box key={domain} mb="2">
            <HStack px="3" py="1.5" mt="1" mb="1" gap="2" bg="brand.solid" color="brand.contrast" borderRadius="md">
              <Text fontSize="12px" fontWeight="semibold">
                {DOMAIN[domain] ?? cap(domain)}
              </Text>
              <Text fontFamily="mono" fontSize="10px" opacity={0.7} ml="auto">
                {runs.length} runs
              </Text>
            </HStack>
            <Stack gap="0">
              {runs.map((r) => {
                const on = run?.trace_id === r.trace_id;
                return (
                  <HStack key={r.trace_id} as="button" onClick={() => !busy && select(r)} justify="space-between" px="3" py="1" borderRadius="md" bg={on ? "surfaceSunken" : "transparent"} _hover={{ bg: "surfaceSunken" }} cursor={busy ? "default" : "pointer"} textAlign="left">
                    <Text fontSize="13px" fontWeight={on ? "semibold" : "normal"} color={on ? "fg" : "fg.muted"} truncate>
                      {cap(r.intent)}
                    </Text>
                    <HStack gap="1.5" flexShrink={0}>
                      <Text fontFamily="mono" fontSize="10px" color="fg.subtle" title={`${r.spans.length} steps in this agent run`}>
                        {r.spans.length}
                      </Text>
                      <Lang code={r.language} />
                    </HStack>
                  </HStack>
                );
              })}
            </Stack>
          </Box>
        ))}
      </Surface>
      </Box>

      <Stack gap="4" minW="0">
        <HStack justify="space-between" flexWrap="wrap" gap="3">
          <HStack gap="2" fontSize="13px" color="fg.muted" flexWrap="wrap">
            <span>{run ? (DOMAIN[run.domain] ?? cap(run.domain)).split(" · ")[0] : ""}</span>
            <span>›</span>
            <Text color="fg" fontWeight="medium">
              {run ? cap(run.intent) : ""}
            </Text>
            {run && (
              <Chip tone={busy ? "brand" : "muted"} dot={busy}>
                {run.trace_id} · {busy ? "live" : "recorded"}
              </Chip>
            )}
          </HStack>
          <HStack gap="2" flexWrap="wrap">
            <NativeSelect.Root size="sm" w="340px" maxW="100%" disabled={busy}>
              <NativeSelect.Field value={sabotage} onChange={(e) => setSabotage(e.target.value)} h="36px" borderRadius="lg" bg="surface" borderColor="hairlineStrong" fontSize="13px">
                <option value="">Leave the run clean (control)</option>
                {run?.sabotage.map((s) => (
                  <option key={s.name} value={s.name}>
                    Break it: {s.text.toLowerCase()}
                  </option>
                ))}
              </NativeSelect.Field>
              <NativeSelect.Indicator />
            </NativeSelect.Root>
            <Button {...primaryButton} w="124px" onClick={audit} loading={busy} loadingText="Auditing" disabled={!info?.available || !run}>
              ▶ Audit
            </Button>
          </HStack>
        </HStack>

        <Canvas>
          <Grid templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr)" }} alignItems="stretch">
            <NodeCard node={runNode} />
            <Edge on={busy || !!done} flowing={screener.status === "running"} label="all runs" />
            <NodeCard node={screenerNode} />
            <Edge on={escalated === true} flowing={confirmer.status === "running"} label={escalated === null ? "if flagged" : escalated ? "flagged" : "cleared"} />
            <NodeCard node={confirmerNode} />
            <Edge on={!!done} />
            <NodeCard node={verdictNode(done, truth, busy)} />
          </Grid>
          {info && !info.available && (
            <Text fontSize="12px" color="orange.fg" mt="4" fontFamily="mono">
              no model configured: set LLM_NAME, LLM_BASE_URL, LLM_API_KEY · Fleet and Review work without
            </Text>
          )}
          <HStack mt="5" justify="center" gap="2">
          <HStack w="fit-content" minW="420px" h="38px" justify="center" bg="shell" borderWidth="1px" borderColor={error ? "orange.emphasized" : busy ? "brand.solid" : "hairline"} borderRadius="lg" px="4" gap="4" fontSize="13px" boxShadow="card" transition="border-color .3s">
            {error ? (
              <Text fontWeight="medium" color="orange.fg" lineClamp={1}>
                {error}
              </Text>
            ) : busy ? (
              <>
                <Thinking verb={stage} size="12px" />
                <Text fontFamily="mono" fontSize="11px" color="fg.muted" lineClamp={1}>
                  {elapsed.toFixed(1)}s{lastTool ? ` · ${lastTool}` : ""}
                </Text>
              </>
            ) : done ? (
              <Text fontFamily="mono" fontSize="11px" color="fg.muted">
                audit finished in {done.seconds}s · {sabotage ? "stress test" : "clean run"} · press ▶ Audit to run again
              </Text>
            ) : (
              <Text fontFamily="mono" fontSize="11px" color="fg.muted">
                ready · pick a run, choose to break it or not, press ▶ Audit
              </Text>
            )}
          </HStack>
          </HStack>
        </Canvas>

        <Grid templateColumns={{ base: "1fr", xl: "minmax(0, 1fr) minmax(360px, 440px)" }} gap="4" alignItems="start">
          <Surface>
            <HStack justify="space-between" mb="3" flexWrap="wrap" gap="2">
              <HStack gap="2">
                <Eyebrow mb="0">Transcript · {spans.filter((s) => s.kind === "tool_call").length} tool calls by the agent</Eyebrow>
                <IconButton
                  size="xs"
                  variant="outline"
                  borderColor={busy ? "brand.solid" : "hairlineStrong"}
                  color={busy ? "brand.fg" : "fg.muted"}
                  borderRadius="md"
                  onClick={() => setFlowOpen(true)}
                  disabled={!busy && !screener.tools.length}
                  aria-label="Watch the investigation"
                  title="Watch the investigation: the auditor's tool calls as an animated flow"
                  animation={busy ? "glow 1.6s ease-in-out infinite" : undefined}
                >
                  <Workflow size={14} />
                </IconButton>
                <IconButton
                  size="xs"
                  variant="outline"
                  borderColor="hairlineStrong"
                  color="fg.muted"
                  borderRadius="md"
                  onClick={() => setTranscriptOpen(true)}
                  aria-label="Open the full transcript"
                  title="Open the full transcript: every message and tool answer in full"
                >
                  <ScrollText size={14} />
                </IconButton>
              </HStack>
              <HStack gap="3" fontFamily="mono" fontSize="10px" color="fg.subtle">
                <HStack gap="1">
                  <Box w="8px" h="8px" borderRadius="sm" bg="orange.solid" /> <span>step you broke</span>
                </HStack>
                <HStack gap="1">
                  <Box w="8px" h="8px" borderRadius="sm" bg="red.solid" /> <span>cited by the auditor</span>
                </HStack>
                <HStack gap="1">
                  <mark>quote</mark> <span>evidence</span>
                </HStack>
              </HStack>
            </HStack>
            <Transcript spans={spans} broke={broke} cited={cited} quotes={quotes} />
          </Surface>
          <Stack gap="4" position={{ xl: "sticky" }} top="80px" maxH={{ xl: "calc(100vh - 100px)" }} overflow="auto">
          <Surface>
            <Eyebrow>Findings{result ? ` · ${shortModel(result.model)}` : ""}</Eyebrow>
            {result && result.findings.length > 0 ? (
              <Stack gap="3">
                {result.findings.map((f, i) => (
                  <FindingCard key={i} finding={f} unverified={new Set(result.evidence.find((e) => e.finding === i)?.unverified_quotes ?? [])} />
                ))}
              </Stack>
            ) : (
              <Text fontSize="13px" color="fg.muted" lineHeight="1.6">
                {done ? "No findings: the auditor cleared the run." : "Findings appear here. Each one names the error, the steps, and quotes evidence that code has checked word for word against those steps."}
              </Text>
            )}
          </Surface>
          <Surface>
            <Eyebrow>Cost of this run</Eyebrow>
            <Savings screen={done ? screenResult : null} confirm={done ? confirmResult : null} avg70={avg70} escalated={escalated === true} />
          </Surface>
          </Stack>
        </Grid>
      </Stack>
      <TranscriptDialog
        open={transcriptOpen}
        onClose={() => setTranscriptOpen(false)}
        title={run ? cap(run.intent) : ""}
        spans={spans}
        toolDocs={run?.tool_docs ?? {}}
        broke={broke}
        cited={cited}
        quotes={quotes}
        readBy={readBy}
      />
      <FlowDialog
        open={flowOpen}
        onClose={() => setFlowOpen(false)}
        live={busy}
        escalated={escalated}
        lanes={[
          { name: "screener · tier 1", model: shortModel(info?.screener) || "Apertus 8B", status: screener.status, tools: screener.tools, res: screener.res },
          { name: "confirmer · tier 2", model: shortModel(info?.confirmer) || "Apertus 70B", status: confirmer.status, tools: confirmer.tools, res: confirmer.res },
        ]}
        spans={spans}
        toolDocs={run?.tool_docs ?? {}}
        fleet={fleetStats}
        broke={broke}
        cited={cited}
        findings={result?.findings ?? []}
        findingsBy={result ? shortModel(result.model) : ""}
        avg70={avg70}
        verdict={done ? { title: verdictNode(done, truth, false).title, good: verdictNode(done, truth, false).status === "cleared" } : { title: "", good: null }}
      />
    </Grid>
  );
}
