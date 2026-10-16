import { Box, CloseButton, Dialog, HStack, Image, Portal, Stack, Text } from "@chakra-ui/react";
import { useMemo, useState } from "react";

import type { Span } from "../api";
import logoMark from "../logo-mark.png";
import { Segmented } from "./Sidebar";
import { MessageBlock, pairSteps, type StepMarks, ToolBlock } from "./StepView";
import { Chip } from "./Surface";

type Props = {
  open: boolean;
  onClose: () => void;
  title: string;
  spans: Span[];
  toolDocs: Record<string, string>;
  broke: Set<string>;
  cited: Set<string>;
  quotes: string[];
  readBy: Map<string, 0 | 1>;
};
type Filter = "all" | "messages" | "tools";

/** The complete agent run as one vertical flow: every message in full, every tool call paired with its full answer
 *  and what the tool does; broken, cited and read-by markers from the audit. */
export function TranscriptDialog({ open, onClose, title, spans, toolDocs, broke, cited, quotes, readBy }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const steps = useMemo(() => pairSteps(spans), [spans]);
  const shown = steps.filter((s) => filter === "all" || (filter === "tools" ? s.kind === "tool" : s.kind === "msg"));
  const marks = (s?: Span): StepMarks => (s ? { broke: broke.has(s.id), cited: cited.has(s.id), readBy: readBy.get(s.id) } : {});
  const tools = steps.filter((s) => s.kind === "tool").length;

  return (
    <Dialog.Root open={open} onOpenChange={(e) => !e.open && onClose()} size="cover" motionPreset="slide-in-bottom" scrollBehavior="inside">
      <Portal>
        <Dialog.Backdrop bg="blackAlpha.700" backdropFilter="blur(6px)" />
        <Dialog.Positioner>
          <Dialog.Content bg="canvas" borderWidth="1px" borderColor="hairline" borderRadius="2xl" maxW="980px" h="90vh" overflow="hidden">
            <Dialog.Header borderBottomWidth="1px" borderColor="hairline" py="3">
              <HStack gap="3" w="100%" pr="10">
                <Box w="28px" h="28px" borderRadius="md" bg="logo.solid" display="grid" placeItems="center">
                  <Image src={logoMark} alt="" w="19px" h="19px" />
                </Box>
                <Dialog.Title fontSize="15px" fontWeight="semibold">
                  Agent run · {title}
                </Dialog.Title>
                <Chip tone="muted">
                  {spans.length} steps · {tools} tool calls
                </Chip>
                <Box ml="auto" />
                <Segmented<Filter>
                  value={filter}
                  onChange={setFilter}
                  options={[
                    ["all", "everything"],
                    ["messages", "messages"],
                    ["tools", "tool calls"],
                  ]}
                />
              </HStack>
            </Dialog.Header>
            <Dialog.CloseTrigger asChild top="3" insetEnd="3">
              <CloseButton size="sm" />
            </Dialog.CloseTrigger>
            <Dialog.Body px="6" py="5">
              <Stack gap="0">
                {shown.map((s, i) => {
                  const key = s.kind === "tool" ? s.call.id : s.span.id;
                  const who = s.kind === "msg" && s.span.kind === "user_message" ? "customer" : s.kind === "tool" ? "tool" : "agent";
                  return (
                    <HStack key={key} align="stretch" gap="4" animation={`pop .35s ease-out ${Math.min(i, 12) * 0.04}s both`}>
                      {/* flow rail: a node per step, a line to the next */}
                      <Stack align="center" gap="0" w="20px" flexShrink={0}>
                        <Box w="2px" h="14px" bg={i === 0 ? "transparent" : "hairlineStrong"} />
                        <Box w="12px" h="12px" borderRadius="full" borderWidth="2px" borderColor={who === "customer" ? "logo.solid" : who === "tool" ? "fg.muted" : "brand.solid"} bg="canvas" flexShrink={0} />
                        <Box w="2px" flex="1" bg={i === shown.length - 1 ? "transparent" : "hairlineStrong"} />
                      </Stack>
                      <Box flex="1" minW="0" pb="3">
                        {s.kind === "tool" ? (
                          <ToolBlock call={s.call} result={s.result} doc={s.call.tool ? toolDocs[s.call.tool] : undefined} quotes={quotes} marksCall={marks(s.call)} marksResult={marks(s.result)} />
                        ) : (
                          <MessageBlock span={s.span} quotes={quotes} marks={marks(s.span)} />
                        )}
                      </Box>
                    </HStack>
                  );
                })}
              </Stack>
              <HStack justify="center" gap="4" pt="2" fontFamily="mono" fontSize="10px" color="fg.subtle">
                <HStack gap="1.5">
                  <Box w="9px" h="9px" borderRadius="full" borderWidth="2px" borderColor="logo.solid" />
                  <Text>customer</Text>
                </HStack>
                <HStack gap="1.5">
                  <Box w="9px" h="9px" borderRadius="full" borderWidth="2px" borderColor="brand.solid" />
                  <Text>agent</Text>
                </HStack>
                <HStack gap="1.5">
                  <Box w="9px" h="9px" borderRadius="full" borderWidth="2px" borderColor="fg.muted" />
                  <Text>tool call and answer</Text>
                </HStack>
              </HStack>
            </Dialog.Body>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
