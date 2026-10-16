import { Box, HStack, IconButton, Image, Tabs, Text } from "@chakra-ui/react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import logoMark from "./logo-mark.png";
import { Toaster } from "./components/Toaster";
import { BreakAgent } from "./views/BreakAgent";
import { Fleet } from "./views/Fleet";
import { Review } from "./views/Review";

const TAB_W = 124;

const VIEWS = [
  { id: "break", label: "Break the agent" },
  { id: "fleet", label: "Fleet" },
  { id: "review", label: "Review" },
];

const Sun = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>
);
const Moon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </svg>
);

export default function App() {
  // Deep link: #break, #fleet or #review
  const [view, setView] = useState(() => (VIEWS.some((v) => v.id === location.hash.slice(1)) ? location.hash.slice(1) : "break"));
  const { resolvedTheme, setTheme } = useTheme();
  const dark = resolvedTheme === "dark";
  const go = (v: string) => {
    setView(v);
    if (location.hash !== `#${v}`) history.pushState(null, "", `#${v}`);
  };
  // Back/forward and edited hashes switch the tab too
  useEffect(() => {
    const sync = () => {
      const h = location.hash.slice(1);
      if (VIEWS.some((v) => v.id === h)) setView(h);
    };
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);

  return (
    <Tabs.Root
      value={view}
      onValueChange={(e) => go(e.value)}
      variant="plain"
      lazyMount
    >
      <Box as="header" position="sticky" top="0" zIndex="10" bg="shell" borderBottomWidth="1px" borderColor="hairline">
        <HStack gap="6" px="5" h="60px">
          <HStack as="button" gap="2.5" onClick={() => go("break")} cursor="pointer" aria-label="rosetta-flow, open Break the agent">
            <Box w="32px" h="32px" borderRadius="lg" bg="logo.solid" display="grid" placeItems="center">
              <Image src={logoMark} alt="" w="21px" h="21px" />
            </Box>
            <Text fontWeight="semibold" fontSize="15px" letterSpacing="-0.01em">
              rosetta-flow
            </Text>
          </HStack>
          <Text fontFamily="mono" fontSize="11px" color="fg.muted" display={{ base: "none", md: "block" }}>
            An open, on-premise auditor for AI-agent runs, built with Apertus
          </Text>
          {/* One group, equal widths; a lime pill slides to the active view (slight overshoot) and sits a bit larger */}
          <Tabs.List ml="auto" position="relative" gap="0" p="0" h="34px" alignItems="stretch" bg="surface" borderWidth="1px" borderColor="hairlineStrong" borderRadius="xl" overflow="hidden">
            <Box
              position="absolute"
              top="0"
              bottom="0"
              left="0"
              w={`${TAB_W}px`}
              borderRadius="lg"
              bg="brand.solid"
              boxShadow="brand.glow"
              transform={`translateX(${VIEWS.findIndex((v) => v.id === view) * TAB_W}px)`}
              transition="transform .45s cubic-bezier(.34, 1.3, .64, 1)"
              pointerEvents="none"
            />
            {VIEWS.map((v) => (
              <Tabs.Trigger
                key={v.id}
                value={v.id}
                position="relative"
                zIndex="1"
                w={`${TAB_W}px`}
                h="auto"
                minH="0"
                display="flex"
                alignItems="center"
                lineHeight="1"
                px="2"
                whiteSpace="nowrap"
                justifyContent="center"
                borderRadius="lg"
                bg="transparent"
                color="fg.muted"
                fontSize="12.5px"
                fontWeight="medium"
                transition="color .25s, font-size .25s"
                _hover={{ color: "fg" }}
                _selected={{ color: "brand.contrast", fontWeight: "semibold", fontSize: "13px", _hover: { color: "brand.contrast" } }}
              >
                {v.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <IconButton w="34px" h="34px" minW="34px" variant="outline" borderColor="hairlineStrong" bg="surface" onClick={() => setTheme(dark ? "light" : "dark")} aria-label={dark ? "switch to light mode" : "switch to dark mode"} color="fg.muted" borderRadius="full">
            {dark ? <Sun /> : <Moon />}
          </IconButton>
        </HStack>
      </Box>
      <Box px="5" py="5" pb="24">
        <Tabs.Content value="break" pt="0">
          <Box animation="viewIn .35s ease-out">
          <BreakAgent />
          </Box>
        </Tabs.Content>
        <Tabs.Content value="fleet" pt="0">
          <Box animation="viewIn .35s ease-out">
          <Fleet />
          </Box>
        </Tabs.Content>
        <Tabs.Content value="review" pt="0">
          <Box animation="viewIn .35s ease-out">
          <Review />
          </Box>
        </Tabs.Content>
      </Box>
      <Toaster />
    </Tabs.Root>
  );
}
