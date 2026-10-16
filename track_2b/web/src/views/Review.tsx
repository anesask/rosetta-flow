import { Box, Button, Grid, HStack, Input, Stack, Text } from "@chakra-ui/react";
import { useEffect, useMemo, useState } from "react";

import { getJSON, postJSON, type RunDetail, type RunSummary, shortModel, type Trail, typeName } from "../api";
import { FindingCard } from "../components/FindingCard";
import { Bot, Link2, ShieldCheck, UserCheck } from "lucide-react";

import { Canvas, Edge, Lang, type Node, NodeCard } from "../components/Pipeline";
import { GroupBand, RunRow, Segmented } from "../components/Sidebar";
import { Chip, Eyebrow, Surface } from "../components/Surface";
import { Transcript } from "../components/Transcript";

const DECISIONS: [string, string, string][] = [
  ["confirmed", "Confirm", "red"],
  ["false_alarm", "False alarm", "brand"],
  ["follow_up", "Follow up", "orange"],
];
const DOMAIN: Record<string, string> = { refunds: "Refunds · customer support", manufacturing: "Shop floor · quality" };
const PAGE = 14;
type Filter = "flagged" | "all";
const shortId = (id: string) => id.replace(/^(refunds|manufacturing)-/, "");

export function Review() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [trail, setTrail] = useState<Trail>({ entries: [], count: 0, intact: true, broken_at: null, latest: {} });
  const [reviewer, setReviewer] = useState("demo-reviewer");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [domain, setDomain] = useState("refunds");
  const [filter, setFilter] = useState<Filter>("flagged");
  const [page, setPage] = useState(0);

  useEffect(() => {
    getJSON<RunSummary[]>("/api/runs")
      .then((rs) => {
        setRuns(rs);
        const first = rs.find((r) => r.verdict === "issues_found") ?? rs[0];
        if (first) open(first.trace_id);
      })
      .catch(() => setRuns([]));
    getJSON<Trail>("/api/review").then(setTrail).catch(() => undefined);
    try {
      const saved = localStorage.getItem("rf-reviewer");
      if (saved) setReviewer(saved);
    } catch {
      /* storage blocked */
    }
  }, []);

  function saveReviewer(v: string) {
    setReviewer(v);
    try {
      localStorage.setItem("rf-reviewer", v.trim());
    } catch {
      /* storage blocked */
    }
  }

  async function open(id: string) {
    setError(null);
    setDetail(await getJSON<RunDetail>(`/api/runs/${encodeURIComponent(id)}`));
  }

  async function decide(finding: number, decision: string) {
    if (!detail || !reviewer.trim()) return;
    setError(null);
    try {
      setTrail(await postJSON<Trail>("/api/review", { trace_id: detail.summary.trace_id, finding, decision, reviewer: reviewer.trim() }));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of runs) if (filter === "all" || r.verdict === "issues_found") c[r.domain] = (c[r.domain] ?? 0) + 1;
    return c;
  }, [runs, filter]);
  const list = useMemo(() => runs.filter((r) => r.domain === domain && (filter === "all" || r.verdict === "issues_found")), [runs, domain, filter]);
  const pages = Math.max(1, Math.ceil(list.length / PAGE));
  const shown = list.slice(page * PAGE, page * PAGE + PAGE);
  const reviewed = (id: string) => Object.keys(trail.latest).some((k) => k.startsWith(`${id}#`));

  const findings = detail?.audit?.report?.findings ?? [];
  const cited = useMemo(() => new Set(findings.flatMap((f) => f.span_ids)), [findings]);
  const quotes = useMemo(() => findings.flatMap((f) => f.evidence), [findings]);
  const broke = useMemo(() => new Set(detail?.truth?.flatMap((t) => t.span_ids) ?? []), [detail]);
  const id = detail?.summary.trace_id ?? "";
  const decided = findings.filter((_, i) => trail.latest[`${id}#${i}`]).length;
  const quotesAll = findings.reduce((a, f) => a + f.evidence.length, 0);
  const quotesBad = (detail?.audit?.evidence ?? []).reduce((a, e) => a + e.unverified_quotes.length, 0);
  const flaggedRun = detail?.audit?.report?.verdict === "issues_found";

  const nodes: Node[] = detail
    ? [
        {
          kind: "agent run",
          title: shortId(id),
          meta: `${detail.summary.domain} · ${detail.summary.language} · ${detail.summary.steps} steps\n${detail.truth?.length ? "injected: " + detail.truth.map((t) => typeName(t.type)).join(", ") : "clean"}`,
          status: detail.truth?.length ? "flagged" : "idle",
          statusText: detail.truth?.length ? "has an error" : "clean",
        },
        {
          kind: "70B audit",
          title: shortModel(detail.audit?.model) || "Apertus 70B",
          meta: `${findings.length} finding${findings.length === 1 ? "" : "s"} · ${quotesAll - quotesBad}/${quotesAll} quotes verified\n${detail.audit?.tool_calls ?? 0} tool calls · ${detail.audit?.duration_s?.toFixed(1) ?? "–"}s`,
          status: flaggedRun ? "flagged" : detail.audit?.report ? "cleared" : "failed",
        },
        {
          kind: "your decision",
          title: findings.length ? `${decided} / ${findings.length} decided` : "Nothing to decide",
          meta: findings.length ? "confirm, false alarm or follow up\nper finding, on the right" : "the 70B cleared this run",
          status: findings.length && decided === findings.length ? "cleared" : findings.length ? "running" : "idle",
          statusText: findings.length && decided === findings.length ? "done" : findings.length ? "open" : "idle",
        },
        {
          kind: "review trail",
          title: trail.intact ? "Chain intact" : "Chain broken",
          meta: `${trail.count} decision${trail.count === 1 ? "" : "s"} recorded\nlast hash ${trail.entries[0]?.hash.slice(0, 10) ?? "–"}`,
          status: trail.intact ? "cleared" : "flagged",
          statusText: trail.intact ? "verified" : `entry ${trail.broken_at}`,
          big: true,
        },
      ]
    : [];

  return (
    <Grid templateColumns={{ base: "1fr", lg: "260px minmax(0, 1fr)" }} gap="4" alignItems="start">
      <Box>
        <Surface p="2" position={{ lg: "fixed" }} top={{ lg: "80px" }} w={{ lg: "260px" }} zIndex="1">
          <HStack px="2" pt="2" mb="2" justify="space-between">
            <Eyebrow mb="0">Audited runs</Eyebrow>
            <Segmented<Filter>
              value={filter}
              onChange={(f) => {
                setFilter(f);
                setPage(0);
              }}
              options={[
                ["flagged", "flagged"],
                ["all", "all"],
              ]}
            />
          </HStack>
          <Stack gap="1" mb="2">
            {Object.keys(DOMAIN).map((d) => (
              <GroupBand
                key={d}
                label={DOMAIN[d]}
                count={`${counts[d] ?? 0} runs`}
                on={domain === d}
                onClick={() => {
                  setDomain(d);
                  setPage(0);
                }}
              />
            ))}
          </Stack>
          <HStack px="3" pb="1" justify="space-between">
            <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
              error · run
            </Text>
            <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
              findings · lang
            </Text>
          </HStack>
          <Stack gap="0">
            {shown.map((r) => (
              <RunRow
                key={r.trace_id}
                on={id === r.trace_id}
                onClick={() => open(r.trace_id)}
                right={
                  <>
                    <Text fontFamily="mono" fontSize="10px" fontWeight="semibold" color={r.verdict === "issues_found" ? "red.fg" : r.verdict === "ok" ? "brand.fg" : "orange.fg"} title="findings by the 70B">
                      {r.verdict === "issues_found" ? r.findings : r.verdict === "ok" ? "ok" : "–"}
                    </Text>
                    <Lang code={r.language} />
                  </>
                }
              >
                <HStack gap="1.5" minW="0">
                  {reviewed(r.trace_id) && <Box w="6px" h="6px" borderRadius="full" bg="brand.solid" flexShrink={0} title="reviewed" />}
                  <Text fontSize="13px" fontWeight={id === r.trace_id ? "semibold" : "normal"} color={id === r.trace_id ? "fg" : "fg.muted"} truncate>
                    {r.truth && r.truth.length ? typeName(r.truth[0]) : "clean run"}
                  </Text>
                </HStack>
                <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
                  {shortId(r.trace_id)}
                </Text>
              </RunRow>
            ))}
          </Stack>
          <HStack justify="space-between" px="2" pt="2">
            <Button size="2xs" variant="ghost" disabled={page === 0} onClick={() => setPage(page - 1)} fontFamily="mono">
              ‹ prev
            </Button>
            <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
              {list.length ? `${page * PAGE + 1}–${Math.min(list.length, (page + 1) * PAGE)} of ${list.length}` : "none"}
            </Text>
            <Button size="2xs" variant="ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)} fontFamily="mono">
              next ›
            </Button>
          </HStack>
        </Surface>
      </Box>

      <Stack gap="4" minW="0">
        <HStack justify="space-between" flexWrap="wrap" gap="3">
          <HStack gap="2" fontSize="13px" color="fg.muted" flexWrap="wrap">
            <span>Review</span>
            <span>›</span>
            <Text color="fg" fontWeight="medium">
              {id || "pick a run"}
            </Text>
            <Chip tone={trail.intact ? "brand" : "red"} dot>
              {trail.intact ? `chain intact · ${trail.count} decision${trail.count === 1 ? "" : "s"}` : `chain broken at ${trail.broken_at}`}
            </Chip>
          </HStack>
          <HStack gap="2">
            <Text fontFamily="mono" fontSize="11px" color="fg.muted">
              reviewer
            </Text>
            <Input size="sm" h="36px" w="180px" borderRadius="lg" bg="surface" borderColor="hairlineStrong" value={reviewer} maxLength={60} onChange={(e) => saveReviewer(e.target.value)} />
          </HStack>
        </HStack>

        {detail && (
          <Canvas>
            <Grid templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr)" }} alignItems="stretch">
              <NodeCard node={{ ...nodes[0], icon: Bot }} />
              <Edge on label="audited" />
              <NodeCard node={{ ...nodes[1], icon: ShieldCheck }} />
              <Edge on={findings.length > 0} label={findings.length ? "findings" : "cleared"} />
              <NodeCard node={{ ...nodes[2], icon: UserCheck }} />
              <Edge on={decided > 0} label="appended" />
              <NodeCard node={{ ...nodes[3], icon: Link2 }} />
            </Grid>
          </Canvas>
        )}

        {detail && (
          <Grid templateColumns={{ base: "1fr", xl: "minmax(0, 1fr) minmax(360px, 440px)" }} gap="4" alignItems="start">
            <Surface>
              <HStack justify="space-between" mb="3" flexWrap="wrap" gap="2">
                <Eyebrow mb="0">Transcript</Eyebrow>
                <HStack gap="3" fontFamily="mono" fontSize="10px" color="fg.subtle">
                  <HStack gap="1">
                    <Box w="8px" h="8px" borderRadius="sm" bg="orange.solid" /> <span>injected error</span>
                  </HStack>
                  <HStack gap="1">
                    <Box w="8px" h="8px" borderRadius="sm" bg="red.solid" /> <span>cited by the auditor</span>
                  </HStack>
                  <HStack gap="1">
                    <mark>quote</mark> <span>evidence</span>
                  </HStack>
                </HStack>
              </HStack>
              <Transcript spans={detail.spans} broke={broke} cited={cited} quotes={quotes} />
            </Surface>
            <Stack gap="4" position={{ xl: "sticky" }} top="80px">
              <Surface>
                <Eyebrow>Findings · decide each</Eyebrow>
                {error && (
                  <Text fontSize="13px" color="red.fg" mb="2">
                    {error}
                  </Text>
                )}
                {!findings.length && (
                  <Text fontSize="13px" color="fg.muted">
                    The 70B found no issues in this run.
                  </Text>
                )}
                <Stack gap="3">
                  {findings.map((f, i) => {
                    const current = trail.latest[`${id}#${i}`];
                    return (
                      <FindingCard key={i} finding={f} unverified={new Set(detail.audit?.evidence.find((e) => e.finding === i)?.unverified_quotes ?? [])}>
                        <HStack gap="2" pt="1" flexWrap="wrap">
                          {DECISIONS.map(([d, label, palette]) => (
                            <Button key={d} size="xs" borderRadius="md" variant={current === d ? "solid" : "outline"} colorPalette={palette} onClick={() => decide(i, d)}>
                              {label}
                            </Button>
                          ))}
                        </HStack>
                      </FindingCard>
                    );
                  })}
                </Stack>
              </Surface>
              <Surface>
                <Eyebrow>Review trail · latest</Eyebrow>
                <Stack gap="1" fontFamily="mono" fontSize="11px">
                  {trail.entries.slice(0, 6).map((e) => (
                    <HStack key={e.hash} bg="surfaceSunken" px="2.5" py="1.5" borderRadius="md" gap="2" color="fg.muted">
                      <Chip tone={e.decision === "confirmed" ? "red" : e.decision === "false_alarm" ? "brand" : "amber"}>{e.decision.replace("_", " ")}</Chip>
                      <Text truncate>
                        {shortId(e.trace_id)} #{e.finding} · {e.reviewer}
                      </Text>
                      <Text ml="auto" flexShrink={0}>
                        {e.hash.slice(0, 8)}
                      </Text>
                    </HStack>
                  ))}
                  {!trail.entries.length && <Text color="fg.subtle">No decisions yet. Each one is appended with the hash of the one before.</Text>}
                </Stack>
              </Surface>
            </Stack>
          </Grid>
        )}
      </Stack>
    </Grid>
  );
}
