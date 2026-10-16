import { Text } from "@chakra-ui/react";
import { useEffect, useState } from "react";

// Our own "thinking" mark: a glyph that grows from a dot to a full ring and back (two tiers, small to large),
// painted in the brand gradient (lime to pink). The verb comes from the auditor's last real tool call.
const GLYPHS = ["·", "∘", "○", "◎", "◉", "◎", "○", "∘"];
const VERB: Record<string, string> = {
  read_spans: "reading steps",
  read_span: "reading a step",
  list_spans: "mapping the run",
  search: "searching",
  read_policy: "checking the policy",
  report: "writing the report",
  bookmark: "marking a step",
};

export function thinkingVerb(lastTool?: string): string {
  return lastTool ? (VERB[lastTool] ?? lastTool.replaceAll("_", " ")) : "reading the run";
}

// Darker brand tones (brand.fg / logo.fg) so the text stays readable on light and dark surfaces
const gradient = { bgImage: "linear-gradient(90deg, var(--chakra-colors-brand-fg), var(--chakra-colors-logo-fg))", bgClip: "text", color: "transparent" } as const;

export function Thinking({ verb, size = "10px" }: { verb: string; size?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = window.setInterval(() => setI((k) => (k + 1) % GLYPHS.length), 110);
    return () => window.clearInterval(t);
  }, []);
  return (
    <Text as="span" fontFamily="mono" fontSize={size} display="inline-flex" alignItems="center" gap="1.5">
      <Text as="span" w="1.1em" textAlign="center" fontSize="1.3em" lineHeight="1" {...gradient}>
        {GLYPHS[i]}
      </Text>
      <Text as="span" {...gradient} fontWeight="semibold">
        {verb}…
      </Text>
    </Text>
  );
}
