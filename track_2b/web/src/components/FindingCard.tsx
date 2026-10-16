import { Box, HStack, Stack, Text } from "@chakra-ui/react";
import type { ReactNode } from "react";

import { type Finding, typeName } from "../api";

export type FindingCardProps = { finding: Finding; unverified: Set<string>; children?: ReactNode };

function jump(id: string) {
  document.getElementById(`step-${id}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

/** One finding: what went wrong, at which steps (click to jump), and each quote with its evidence check. */
export function FindingCard({ finding: f, unverified, children }: FindingCardProps) {
  return (
    <Box bg="surfaceSunken" borderRadius="xl" p="4">
      <Stack gap="2.5">
        <HStack gap="2" flexWrap="wrap" align="baseline">
          <Text fontWeight="semibold" fontSize="15px" textTransform="capitalize">
            {typeName(f.error_type)}
          </Text>
          <Text fontSize="12px" color="fg.muted">
            at step{f.span_ids.length > 1 ? "s" : ""}
          </Text>
          {f.span_ids.map((s) => (
            <Box key={s} as="button" onClick={() => jump(s)} fontFamily="mono" fontSize="12px" px="2" py="0.5" borderRadius="chip" bg="red.subtle" color="red.fg" fontWeight="semibold" cursor="pointer" _hover={{ bg: "red.muted" }}>
              {s}
            </Box>
          ))}
          {f.severity && (
            <Text fontSize="11px" color="fg.subtle" ml="auto">
              severity {f.severity}
            </Text>
          )}
        </HStack>
        <Text fontSize="14px" lineHeight="1.55">
          {f.explanation}
        </Text>
        {f.expected_behavior && (
          <Text fontSize="13px" color="fg.muted" lineHeight="1.5">
            Should have: {f.expected_behavior}
          </Text>
        )}
        <Stack gap="1">
          {f.evidence.map((q, i) => {
            const bad = unverified.has(q);
            return (
              <HStack key={i} align="start" gap="2" fontSize="12px" bg="surface" borderWidth="1px" borderColor="hairline" px="2.5" py="1.5" borderRadius="md">
                <Text as="span" color={bad ? "red.fg" : "brand.fg"} fontWeight="semibold" flexShrink={0} whiteSpace="nowrap" title={bad ? "quote not found in the cited step" : "quote found word for word in the cited step"}>
                  {bad ? "✗ not in the step" : "✓ word for word"}
                </Text>
                <Text as="span" fontFamily="mono" overflowWrap="anywhere" color="fg.muted">
                  {q}
                </Text>
              </HStack>
            );
          })}
        </Stack>
        {children}
      </Stack>
    </Box>
  );
}
