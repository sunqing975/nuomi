/** shared/BusyBridge：在 AssistantRuntimeProvider 内读取运行状态（busy/empty），供 InputBar 等使用。 */
import type { ReactNode } from "react";
import { useAuiState } from "@assistant-ui/react";

export function BusyBridge({ children }: { children: (ctx: { busy: boolean; empty: boolean }) => ReactNode }) {
  const busy = useAuiState((s) => s.thread.isRunning);
  const empty = useAuiState((s) => s.thread.messages.length === 0);
  return <>{children({ busy, empty })}</>;
}
