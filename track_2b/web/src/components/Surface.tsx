import { Box, type BoxProps, Text } from "@chakra-ui/react";
import type { ReactNode } from "react";

/** A panel: hairline border, soft shadow, slightly lighter than the canvas. */
export function Surface({ children, ...rest }: BoxProps & { children: ReactNode }) {
  return (
    <Box bg="surface" borderWidth="1px" borderColor="hairline" borderRadius="card" boxShadow="card" p="4" minW="0" {...rest}>
      {children}
    </Box>
  );
}

/** Small uppercase mono label, as on the node cards. */
export function Eyebrow({ children, ...rest }: BoxProps & { children: ReactNode }) {
  return (
    <Text fontFamily="mono" fontSize="11px" fontWeight="medium" letterSpacing="0.1em" textTransform="uppercase" color="fg.muted" mb="3" {...rest}>
      {children}
    </Text>
  );
}

export type Tone = "brand" | "red" | "amber" | "muted";

export const TONE_STYLE: Record<Tone, { bg: string; color: string }> = {
  brand: { bg: "brand.muted", color: "brand.fg" },
  red: { bg: "red.subtle", color: "red.fg" },
  amber: { bg: "orange.subtle", color: "orange.fg" },
  muted: { bg: "surfaceSunken", color: "fg.muted" },
};

/** Status chip: mono, tinted. */
export function Chip({ tone, children, dot }: { tone: Tone; children: ReactNode; dot?: boolean }) {
  const c = TONE_STYLE[tone];
  return (
    <Text as="span" fontFamily="mono" fontSize="11px" px="2" py="0.5" borderRadius="sm" bg={c.bg} color={c.color} whiteSpace="nowrap" display="inline-flex" alignItems="center" gap="1.5">
      {dot && <Box as="span" w="6px" h="6px" borderRadius="full" bg="currentColor" />}
      {children}
    </Text>
  );
}

/** Primary (brand) button styling, shared by Audit and Replay. */
export const primaryButton = { bg: "brand.solid", color: "brand.contrast", _hover: { bg: "lime.400" }, size: "sm" as const, h: "36px", borderRadius: "lg", px: "5", fontSize: "13px", fontWeight: "semibold" };
