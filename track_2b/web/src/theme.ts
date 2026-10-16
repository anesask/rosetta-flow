import { createSystem, defaultConfig, defineConfig } from "@chakra-ui/react";

// Dark-first "ops console" look: near-black canvas with a faint grid, one brand accent (lime) for anything
// active, cleared or primary; red = flagged, amber = the step you broke; pink only for the logo.
// Light mode keeps the same roles on paper tones. Fonts are bundled (Inter, JetBrains Mono): nothing loads
// from the network.
const config = defineConfig({
  globalCss: {
    html: { fontSize: "14px" },
    body: { bg: "canvas", color: "fg" },
    mark: { bg: "amber.mark", color: "inherit", borderRadius: "2px", padding: "0 2px" },
    "::selection": { bg: "brand.muted" },
    "*::-webkit-scrollbar": { width: "10px", height: "10px" },
    "*::-webkit-scrollbar-thumb": { bg: "hairlineStrong", borderRadius: "999px", border: "3px solid transparent", backgroundClip: "padding-box" },
  },
  theme: {
    keyframes: {
      viewIn: { from: { opacity: 0 }, to: { opacity: 1 } },
      pop: { from: { opacity: 0, transform: "translateY(4px) scale(0.92)" }, to: { opacity: 1, transform: "none" } },
      dash: { from: { backgroundPosition: "0 0" }, to: { backgroundPosition: "24px 0" } },
      dashV: { from: { backgroundPosition: "0 0" }, to: { backgroundPosition: "0 24px" } },
      glow: { "0%, 100%": { boxShadow: "0 0 0 1px #c9ef3c, 0 0 18px rgba(201,239,60,0.18)" }, "50%": { boxShadow: "0 0 0 1px #c9ef3c, 0 0 34px rgba(201,239,60,0.38)" } },
      blink: { "0%, 100%": { opacity: 1 }, "50%": { opacity: 0.25 } },
      shimmer: { from: { backgroundPosition: "-200% 0" }, to: { backgroundPosition: "200% 0" } },
      spin: { from: { transform: "rotate(0deg)" }, to: { transform: "rotate(360deg)" } },
      spinC: { from: { transform: "translate(-50%, -50%) rotate(0deg)" }, to: { transform: "translate(-50%, -50%) rotate(360deg)" } },
      draw: { to: { strokeDashoffset: 0 } },
      dashMove: { to: { strokeDashoffset: -28 } },
      ping: { "0%": { transform: "scale(0.9)", opacity: 0.7 }, "100%": { transform: "scale(1.9)", opacity: 0 } },
      shake: { "0%, 100%": { transform: "translateX(0)" }, "20%, 60%": { transform: "translateX(-4px)" }, "40%, 80%": { transform: "translateX(4px)" } },
      flowX: { from: { backgroundPosition: "0% 0" }, to: { backgroundPosition: "-200% 0" } },
      flowY: { from: { backgroundPosition: "0 0%" }, to: { backgroundPosition: "0 -200%" } },
      travelX: { "0%": { left: "-4px", opacity: 0 }, "15%": { opacity: 1 }, "85%": { opacity: 1 }, "100%": { left: "calc(100% - 4px)", opacity: 0 } },
    },
    tokens: {
      fonts: {
        body: { value: `"Inter Variable", system-ui, -apple-system, "Segoe UI", sans-serif` },
        heading: { value: `"Inter Variable", system-ui, -apple-system, "Segoe UI", sans-serif` },
        mono: { value: `"JetBrains Mono Variable", ui-monospace, Menlo, Consolas, monospace` },
      },
      radii: { card: { value: "14px" }, chip: { value: "999px" } },
      colors: {
        lime: {
          50: { value: "#f7fde0" },
          100: { value: "#ecfab5" },
          200: { value: "#dcf57a" },
          300: { value: "#c9ef3c" },
          400: { value: "#b5de1f" },
          500: { value: "#98bf0f" },
          600: { value: "#7a9a0a" },
          700: { value: "#5c740a" },
          800: { value: "#44560c" },
          900: { value: "#2f3b0b" },
          950: { value: "#1a2106" },
        },
        pink: {
          300: { value: "#ff8fc0" },
          400: { value: "#ff5fa6" },
          500: { value: "#f0408f" },
          600: { value: "#d12374" },
        },
      },
    },
    semanticTokens: {
      colors: {
        canvas: { value: { base: "#eef0ea", _dark: "#0c0e11" } },
        shell: { value: { base: "#ffffff", _dark: "#121318" } },
        surface: { value: { base: "#ffffff", _dark: "#15161d" } },
        surfaceSunken: { value: { base: "#f3f4f0", _dark: "#0f1115" } },
        hairline: { value: { base: "rgba(20,16,28,0.10)", _dark: "rgba(255,255,255,0.08)" } },
        hairlineStrong: { value: { base: "rgba(20,16,28,0.22)", _dark: "rgba(255,255,255,0.18)" } },
        gridline: { value: { base: "rgba(20,16,28,0.05)", _dark: "rgba(255,255,255,0.035)" } },
        brand: {
          solid: { value: "{colors.lime.300}" },
          contrast: { value: "#0c0e11" },
          fg: { value: { base: "{colors.lime.700}", _dark: "{colors.lime.300}" } },
          muted: { value: { base: "{colors.lime.100}", _dark: "{colors.lime.900}" } },
          subtle: { value: { base: "{colors.lime.50}", _dark: "{colors.lime.950}" } },
          emphasized: { value: { base: "{colors.lime.200}", _dark: "{colors.lime.800}" } },
          focusRing: { value: "{colors.lime.400}" },
          glow: { value: "0 0 0 1px #c9ef3c, 0 0 28px rgba(201,239,60,0.22)" },
        },
        logo: {
          solid: { value: { base: "{colors.pink.500}", _dark: "{colors.pink.400}" } },
          fg: { value: { base: "{colors.pink.600}", _dark: "{colors.pink.300}" } },
        },
        amber: { mark: { value: { base: "#ffe9a8", _dark: "#5a4612" } } },
      },
      shadows: {
        card: { value: { base: "0 1px 2px rgba(20,16,28,0.05), 0 10px 30px -18px rgba(20,16,28,0.25)", _dark: "0 1px 0 rgba(255,255,255,0.03) inset, 0 16px 40px -24px rgba(0,0,0,0.8)" } },
      },
    },
  },
});

export const system = createSystem(defaultConfig, config);
