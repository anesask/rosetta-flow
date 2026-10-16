import { Box, createToaster, HStack, Portal, Stack, Toast, Toaster as ChakraToaster } from "@chakra-ui/react";
import { CircleAlert, CircleCheck, Info } from "lucide-react";

export const toaster = createToaster({ placement: "bottom-end", pauseOnPageIdle: true, max: 3 });

// Lime (brand) for results and info; errors stay red so the brand colour is never read as a failure.
const STYLE: Record<string, { bg: string; fg: string; Icon: typeof Info }> = {
  success: { bg: "brand.solid", fg: "#0c0e11", Icon: CircleCheck },
  info: { bg: "brand.solid", fg: "#0c0e11", Icon: Info },
  error: { bg: "red.solid", fg: "white", Icon: CircleAlert },
  warning: { bg: "orange.solid", fg: "white", Icon: CircleAlert },
};

export function Toaster() {
  return (
    <Portal>
      <ChakraToaster toaster={toaster} insetInline={{ mdDown: "4" }}>
        {(t) => {
          const st = STYLE[t.type ?? "info"] ?? STYLE.info;
          return (
            <Toast.Root w={{ md: "380px" }} bg={st.bg} color={st.fg} borderRadius="lg" boxShadow="0 18px 40px -16px rgba(0,0,0,0.6)" px="4" py="3">
              <HStack align="start" gap="3" w="100%">
                <Box pt="0.5" flexShrink={0}>
                  <st.Icon size={18} strokeWidth={2.2} />
                </Box>
                <Stack gap="0.5" flex="1" minW="0">
                  {t.title && (
                    <Toast.Title fontWeight="semibold" fontSize="14px">
                      {t.title}
                    </Toast.Title>
                  )}
                  {t.description && (
                    <Toast.Description fontFamily="mono" fontSize="11.5px" opacity={0.8}>
                      {t.description}
                    </Toast.Description>
                  )}
                </Stack>
                <Toast.CloseTrigger color={st.fg} opacity={0.7} _hover={{ opacity: 1, bg: "blackAlpha.200" }} />
              </HStack>
            </Toast.Root>
          );
        }}
      </ChakraToaster>
    </Portal>
  );
}
