import { Box, HStack, Text } from "@chakra-ui/react";
import type { ReactNode } from "react";

/** Full-colour group band (domain), also used as a filter toggle. */
export function GroupBand({ label, count, on = true, onClick }: { label: string; count: ReactNode; on?: boolean; onClick?: () => void }) {
  return (
    <HStack
      as={onClick ? "button" : "div"}
      onClick={onClick}
      w="100%"
      px="3"
      py="1.5"
      gap="2"
      borderRadius="md"
      bg={on ? "brand.solid" : "surfaceSunken"}
      color={on ? "brand.contrast" : "fg.muted"}
      cursor={onClick ? "pointer" : "default"}
      transition="background .15s"
      textAlign="left"
    >
      <Text fontSize="12px" fontWeight="semibold">
        {label}
      </Text>
      <Text fontFamily="mono" fontSize="10px" opacity={0.7} ml="auto">
        {count}
      </Text>
    </HStack>
  );
}

/** One row in a run list: title left, small meta right. Selected = darker row, no border. */
export function RunRow({ on, onClick, disabled, children, right }: { on: boolean; onClick: () => void; disabled?: boolean; children: ReactNode; right?: ReactNode }) {
  return (
    <HStack
      as="button"
      onClick={() => !disabled && onClick()}
      justify="space-between"
      px="3"
      py="1"
      borderRadius="md"
      bg={on ? "surfaceSunken" : "transparent"}
      _hover={{ bg: "surfaceSunken" }}
      cursor={disabled ? "default" : "pointer"}
      textAlign="left"
      w="100%"
      minW="0"
    >
      <Box minW="0" flex="1">
        {children}
      </Box>
      {right && (
        <HStack gap="1.5" flexShrink={0}>
          {right}
        </HStack>
      )}
    </HStack>
  );
}

/** Segmented control in the header style. */
export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <HStack bg="surface" borderWidth="1px" borderColor="hairlineStrong" borderRadius="lg" p="1" gap="1" h="36px">
      {options.map(([v, label]) => (
        <Box
          key={v}
          as="button"
          onClick={() => onChange(v)}
          px="3"
          h="26px"
          borderRadius="md"
          fontSize="12px"
          bg={value === v ? "brand.solid" : "transparent"}
          color={value === v ? "brand.contrast" : "fg.muted"}
          fontWeight={value === v ? "semibold" : "medium"}
        >
          {label}
        </Box>
      ))}
    </HStack>
  );
}
