import { Box, Button, Grid, HStack, Stack, Table, Text } from "@chakra-ui/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { type FleetRow, getJSON, PRICE, typeName } from "../api";
import { Gavel, Inbox, ScanSearch, ShieldCheck } from "lucide-react";

import { Canvas, Edge, type Node, NodeCard } from "../components/Pipeline";
import { FleetCharts } from "../components/FleetCharts";
import { Segmented } from "../components/Sidebar";
import { Chip, Eyebrow, primaryButton, Surface } from "../components/Surface";

type Domain = "all" | "refunds" | "manufacturing";
const chf = (x: number) => `CHF ${x.toFixed(2)}`;

function CostCard({ label, value, sub, good }: { label: string; value: string; sub: string; good?: boolean }) {
  return (
    <Box bg={good ? "brand.subtle" : "surface"} borderWidth="1px" borderColor={good ? "brand.emphasized" : "hairline"} borderRadius="xl" px="4" py="3">
      <Text fontFamily="mono" fontSize="10px" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted">
        {label}
      </Text>
      <Text fontFamily="mono" fontSize="20px" fontWeight="medium" mt="1" color={good ? "brand.fg" : "fg"} fontVariantNumeric="tabular-nums">
        {value}
      </Text>
      <Text fontFamily="mono" fontSize="11px" color="fg.muted">
        {sub}
      </Text>
    </Box>
  );
}

export function Fleet() {
  const [all, setAll] = useState<FleetRow[] | null>(null);
  const [domain, setDomain] = useState<Domain>("all");
  const [n, setN] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    getJSON<{ runs: FleetRow[] }>("/api/fleet")
      .then((d) => setAll(d.runs))
      .catch(() => setAll([]));
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  const fleet = useMemo(() => (all ?? []).filter((r) => domain === "all" || r.domain === domain), [all, domain]);

  function stop() {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
  }

  function replay() {
    stop();
    setN(0);
    let k = 0;
    timer.current = window.setInterval(() => {
      k = Math.min(fleet.length, k + 3);
      setN(k);
      if (k >= fleet.length) stop();
    }, 90);
  }

  function pick(d: Domain) {
    stop();
    setDomain(d);
    setN(0);
  }

  if (!all) return null;
  const rows = fleet.slice(0, n);
  const running = n > 0 && n < fleet.length;
  const finished = fleet.length > 0 && n >= fleet.length;
  const cleared = rows.filter((r) => r.screen === "ok").length;
  const flagged = rows.filter((r) => r.screen === "issues_found").length;
  const failed = rows.filter((r) => r.screen === "failed").length;
  const esc = rows.filter((r) => r.escalated);
  const confirms = esc.filter((r) => r.final === "issues_found").length;
  const clears = esc.length - confirms;
  const broken = rows.filter((r) => r.error);
  const clean = rows.filter((r) => !r.error);
  const caught = broken.filter((r) => r.final === "issues_found").length;
  const faTwo = clean.filter((r) => r.final === "issues_found").length;
  const faAlone = clean.filter((r) => r.alone === "issues_found").length;
  const right = rows.filter((r) => (r.error ? r.final === "issues_found" : r.final === "ok")).length;
  const cost = (f: (r: FleetRow) => number) => rows.reduce((a, r) => a + f(r), 0) / 1e6;
  const costTwo = cost((r) => r.tok8 * PRICE["8B"] + r.tok70 * PRICE["70B"]);
  const costAlone = cost((r) => r.tok70_alone * PRICE["70B"]);
  const pct = (a: number, b: number) => (b ? `${Math.round((100 * a) / b)}%` : "–");

  const nodes: Node[] = [
    { kind: "incoming", title: `${n} / ${fleet.length} runs`, meta: `held-out test runs\n${broken.length} with an injected error · ${clean.length} clean`, status: running ? "running" : finished ? "cleared" : "idle", statusText: running ? "streaming" : finished ? "done" : "idle" },
    { kind: "screener", title: "Apertus 8B", meta: `${cleared} cleared · ${flagged} flagged · ${failed} no report\nevery run, one small GPU`, status: running ? "running" : finished ? "cleared" : "idle", statusText: running ? "screening" : finished ? `${pct(cleared, rows.length)} stop here` : "idle" },
    { kind: "confirmer", title: "Apertus 70B", meta: `${confirms} confirmed · ${clears} cleared\nsees ${pct(esc.length, rows.length)} of the runs`, status: running && esc.length ? "running" : finished ? "cleared" : "idle", statusText: running && esc.length ? "confirming" : finished ? `${esc.length} runs` : "idle" },
    { kind: "outcome", title: rows.length ? pct(right, rows.length) + " right" : "Waiting", meta: rows.length ? `${caught}/${broken.length} errors flagged\n${faTwo} false alarms (70B alone: ${faAlone})` : "press replay", status: finished ? "cleared" : "idle", statusText: finished ? "measured" : "idle", big: true },
  ];

  return (
    <Stack gap="4">
      <HStack justify="space-between" flexWrap="wrap" gap="3">
        <HStack gap="2" fontSize="13px" color="fg.muted" flexWrap="wrap">
          <span>Fleet</span>
          <span>›</span>
          <Text color="fg" fontWeight="medium">
            A day of agent traffic
          </Text>
          <Chip tone={running ? "brand" : "muted"} dot={running}>
            measured on the test set · replayed, no model calls
          </Chip>
        </HStack>
        <HStack gap="2">
          <Segmented<Domain>
            value={domain}
            onChange={pick}
            options={[
              ["all", `All ${all.length}`],
              ["refunds", "Refunds"],
              ["manufacturing", "Shop floor"],
            ]}
          />
          <Button {...primaryButton} onClick={replay}>
            ▶ Replay
          </Button>
        </HStack>
      </HStack>

      <Canvas>
        <Grid templateColumns={{ base: "1fr", lg: "minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr) 72px minmax(0, 1fr)" }} alignItems="stretch">
          <NodeCard node={{ ...nodes[0], icon: Inbox }} />
          <Edge on={rows.length > 0} flowing={running} label="all runs" />
          <NodeCard node={{ ...nodes[1], icon: ScanSearch }} />
          <Edge on={esc.length > 0} flowing={running && esc.length > 0} label={`${esc.length} flagged`} />
          <NodeCard node={{ ...nodes[2], icon: ShieldCheck }} />
          <Edge on={finished} flowing={running} />
          <NodeCard node={{ ...nodes[3], icon: Gavel }} />
        </Grid>
        <Grid templateColumns={{ base: "1fr", md: "repeat(4, 1fr)" }} gap="3" mt="4">
          <CostCard label="two tiers" value={chf(costTwo)} sub="8B on every run + 70B on flagged" />
          <CostCard label="70B on every run" value={chf(costAlone)} sub="the single-model alternative" />
          <CostCard label="saved" value={costAlone ? chf(costAlone - costTwo) : "–"} sub={costAlone ? `${pct(costAlone - costTwo, costAlone)} of the 70B cost` : "CSCS per-token prices"} good={costAlone > costTwo} />
          <CostCard label="on your own GPU" value="~40,000 / day" sub="8B screening on one A100, measured" />
        </Grid>
      </Canvas>

      <FleetCharts rows={n === 0 ? fleet : rows} replaying={running} />

      <Surface p="0" overflow="hidden">
        <HStack justify="space-between" px="4" pt="3" pb="2">
          <Eyebrow mb="0">Live feed · newest first</Eyebrow>
          <Text fontFamily="mono" fontSize="10px" color="fg.subtle">
            truth = the error we injected, or clean
          </Text>
        </HStack>
        <Box maxH="44vh" overflow="auto">
          <Table.Root size="sm" variant="line" fontSize="12px" fontFamily="mono">
            <Table.Header position="sticky" top="0" bg="surface" zIndex="1">
              <Table.Row>
                {["run", "8B screener", "70B confirmer", "verdict", "truth"].map((h) => (
                  <Table.ColumnHeader key={h} fontFamily="mono" fontSize="10px" textTransform="uppercase" letterSpacing="0.08em" color="fg.subtle">
                    {h}
                  </Table.ColumnHeader>
                ))}
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {rows
                .slice()
                .reverse()
                .map((r) => {
                  const ok = r.error ? r.final === "issues_found" : r.final === "ok";
                  return (
                    <Table.Row key={r.id} borderColor="hairline">
                      <Table.Cell color="fg.muted">{r.id}</Table.Cell>
                      <Table.Cell>
                        <Chip tone={r.screen === "ok" ? "brand" : r.screen === "failed" ? "amber" : "red"}>{r.screen === "ok" ? "cleared" : r.screen === "failed" ? "no report" : "flagged"}</Chip>
                      </Table.Cell>
                      <Table.Cell>{r.escalated ? <Chip tone={r.final === "ok" ? "brand" : "red"}>{r.final === "ok" ? "clears" : "confirms"}</Chip> : <Chip tone="muted">skipped</Chip>}</Table.Cell>
                      <Table.Cell>
                        <Chip tone={ok ? "brand" : "amber"}>{ok ? "right" : "wrong"}</Chip>
                      </Table.Cell>
                      <Table.Cell color="fg.muted">{r.error ? typeName(r.error) : "clean"}</Table.Cell>
                    </Table.Row>
                  );
                })}
              {rows.length === 0 && (
                <Table.Row>
                  <Table.Cell colSpan={5} color="fg.subtle" py="6" textAlign="center">
                    press ▶ Replay to stream {fleet.length} runs through the two tiers
                  </Table.Cell>
                </Table.Row>
              )}
            </Table.Body>
          </Table.Root>
        </Box>
      </Surface>
    </Stack>
  );
}
