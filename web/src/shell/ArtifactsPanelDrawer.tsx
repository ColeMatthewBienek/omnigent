// Right-side push panel hosting the session's published artifacts.
//
// Layout contract matches `FilesPanelDrawer`:
//
//   - **Mobile (`< md`)**: fixed full-screen overlay, sliding in from the
//     right via `translate-x`. Opened from the session-menu FAB.
//   - **Desktop (`md+`)**: static flex sibling with a resize handle on its
//     left edge; width set inline by `useResizablePanel`.

import { useEffect, useRef } from "react";

import { useResizablePanel } from "@/hooks/useResizablePanel";
import { cn } from "@/lib/utils";
import { ArtifactsPanel } from "./ArtifactsPanel";

interface ArtifactsPanelDrawerProps {
  open: boolean;
  onClose: () => void;
  conversationId: string;
}

export function ArtifactsPanelDrawer({ open, onClose, conversationId }: ArtifactsPanelDrawerProps) {
  const { panelWidth, handleProps, isDesktop } = useResizablePanel(open);
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (ref.current) {
      if (open) {
        ref.current.removeAttribute("inert");
      } else {
        ref.current.setAttribute("inert", "");
      }
    }
  }, [open]);

  return (
    <aside
      ref={ref}
      data-testid="artifacts-panel-drawer"
      data-state={open ? "open" : "closed"}
      style={{ width: panelWidth }}
      className={cn(
        "flex flex-col overflow-hidden bg-card transition-[translate,border-color,border-width] duration-150 ease-out",
        "fixed inset-0 z-50 shadow-lg",
        open ? "translate-x-0" : "translate-x-full",
        "md:relative md:inset-auto md:z-auto md:shadow-none md:translate-x-0 md:shrink-0",
        open ? "md:border-border md:border-l" : "md:w-0 md:border-l-0",
      )}
      aria-hidden={!open}
      data-collapsed={!open || undefined}
    >
      {isDesktop && (
        <div
          {...handleProps}
          className="absolute inset-y-0 left-0 z-10 w-1 cursor-col-resize hover:bg-primary/30 active:bg-primary/50 transition-colors"
        />
      )}
      {/* Mounted only while open so the list seeds from a fresh read each
          time the panel is opened. */}
      {open && <ArtifactsPanel conversationId={conversationId} onClose={onClose} />}
    </aside>
  );
}
