import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Focusable,
  Navigation,
  Spinner,
  DialogButton,
} from "@decky/ui";
import {
  applyDepotSelection,
  getAtomGame,
  listAtomGames,
  refreshGame,
  type AtomDepotInfo,
  type AtomDetail,
  type AtomDlcInfo,
  type AtomGame,
  type AtomKeyInfo,
} from "../api";
import {
  AndroidIcon,
  AppleIcon,
  LinuxIcon,
  WindowsIcon,
} from "../components/icons";

/**
 * AdvancedPage: Full-screen Steam route ("/uran/advanced") with:
 *   - Left sidebar (300px): Searchable list of registered AT0-M games.
 *   - Right main pane: Game header, 3 sub-tabs (Depots, DLCs & Licenses, Decryption Keys).
 *   - Gamepad navigation: D-Pad Left/Right between columns, D-Pad Up/Down inside lists.
 *   - Batch staging: Select/unselect across all 3 tabs, and "Apply Selection" commits atomically.
 */

let _target = "";
type TargetListener = (appId: string) => void;
const _listeners = new Set<TargetListener>();

export function setAdvancedTarget(appId: string): void {
  _target = appId;
  _listeners.forEach((l) => l(appId));
}

export function openAdvanced(appId: string): void {
  setAdvancedTarget(appId);
  Navigation.Navigate("/uran/advanced");
}

export function subscribeAdvancedTarget(l: TargetListener): () => void {
  _listeners.add(l);
  return () => {
    _listeners.delete(l);
  };
}

type MainTab = "depots" | "dlcs" | "keys";
type DepotFilter = "all" | "windows" | "linux" | "dlc";

const OS_PRIORITY: Record<string, number> = {
  shared: 0,
  multi: 0,
  none: 0,
  windows: 1,
  linux: 2,
  other: 4,
  macos: 5,
};

const STYLES = `
.uran-adv-root {
  position: absolute;
  inset: 0;
  bottom: 48px;
  display: flex;
  flex-direction: column;
  background: #121318;
  color: #ffffff;
  font-family: inherit;
  overflow: hidden;
  box-sizing: border-box;
}
.uran-adv-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 22px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.10);
  background: rgba(255, 255, 255, 0.02);
  flex-shrink: 0;
}
.uran-adv-title {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  color: #ffffff;
}
.uran-adv-sub {
  font-size: 12px;
  color: #a0aec0;
  margin-top: 3px;
}
.uran-adv-body {
  flex: 1 1 0%;
  display: flex !important;
  flex-direction: row !important;
  min-height: 0;
  overflow: hidden;
}
.uran-adv-side {
  width: 310px;
  min-width: 260px;
  display: flex !important;
  flex-direction: column !important;
  border-right: 1px solid rgba(255, 255, 255, 0.10);
  background: rgba(255, 255, 255, 0.015);
  min-height: 0;
  flex-shrink: 0;
}
.uran-adv-search-box {
  margin: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.14);
  color: #ffffff;
  outline: none;
  box-sizing: border-box;
  width: calc(100% - 24px);
}
.uran-adv-search-box:focus {
  border-color: #1a73e8;
  box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.35);
}
.uran-adv-games {
  flex: 1 1 0%;
  overflow-y: auto;
  padding: 0 8px 12px;
  display: flex !important;
  flex-direction: column !important;
  gap: 3px;
}
.uran-adv-game {
  display: flex !important;
  align-items: center !important;
  gap: 8px !important;
  padding: 9px 12px !important;
  border-radius: 6px !important;
  font-size: 13px !important;
  cursor: pointer !important;
  color: #dbe0e6 !important;
  transition: background 0.12s ease !important;
}
.uran-adv-game:hover,
.uran-adv-game:focus,
.uran-adv-game:focus-within {
  background: rgba(255, 255, 255, 0.08) !important;
  color: #ffffff !important;
}
.uran-adv-game.sel {
  background: rgba(26, 115, 232, 0.25) !important;
  color: #ffffff !important;
  font-weight: 600 !important;
  border-left: 3px solid #1a73e8 !important;
}
.uran-adv-game .nm {
  flex: 1 1 0%;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.uran-adv-game .id {
  font-size: 11px;
  color: #a0aec0;
  font-variant-numeric: tabular-nums;
  font-family: monospace;
}

.uran-adv-main {
  flex: 1 1 0%;
  display: flex !important;
  flex-direction: column !important;
  min-width: 0;
  min-height: 0;
  background: #121318;
}
.uran-adv-mhead {
  padding: 14px 22px 10px;
  flex-shrink: 0;
}
.uran-adv-mhead h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #ffffff;
}
.uran-adv-meta {
  font-size: 12px;
  color: #a0aec0;
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.uran-adv-subtabs {
  display: flex !important;
  flex-direction: row !important;
  align-items: center !important;
  gap: 8px !important;
  padding: 0 22px 10px !important;
  flex-shrink: 0 !important;
  flex-wrap: nowrap !important;
  overflow-x: auto !important;
}
.uran-adv-subtab-btn {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: auto !important;
  min-width: 0 !important;
  flex: 0 0 auto !important;
  padding: 6px 14px !important;
  border-radius: 6px !important;
  font-size: 12px !important;
  font-weight: 600 !important;
  height: 32px !important;
  min-height: 32px !important;
  cursor: pointer !important;
}
.uran-adv-filters {
  display: flex !important;
  flex-direction: row !important;
  align-items: center !important;
  gap: 8px !important;
  padding: 4px 22px 10px !important;
  flex-wrap: nowrap !important;
  overflow-x: auto !important;
  flex-shrink: 0 !important;
}
.uran-adv-chip {
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  width: auto !important;
  min-width: 0 !important;
  max-width: fit-content !important;
  flex: 0 0 auto !important;
  margin: 0 !important;
  padding: 4px 14px !important;
  border-radius: 999px !important;
  font-size: 11px !important;
  cursor: pointer !important;
  height: 28px !important;
  min-height: 28px !important;
  background: rgba(255, 255, 255, 0.06) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  color: #dbe0e6 !important;
  white-space: nowrap !important;
}
.uran-adv-chip.on {
  background: rgba(26, 115, 232, 0.3) !important;
  border-color: #1a73e8 !important;
  color: #ffffff !important;
}
.uran-adv-table {
  flex: 1 1 0% !important;
  min-height: 0 !important;
  overflow-y: auto !important;
  margin: 0 16px 8px !important;
  border-radius: 8px !important;
  background: rgba(255, 255, 255, 0.02) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
}
.uran-adv-thead {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  padding: 9px 14px !important;
  position: sticky !important;
  top: 0 !important;
  z-index: 2 !important;
  background: #191a20 !important;
  font-size: 11px !important;
  text-transform: uppercase !important;
  letter-spacing: 0.6px !important;
  color: #a0aec0 !important;
  font-weight: 700 !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.10) !important;
}
.uran-adv-row {
  display: flex !important;
  align-items: center !important;
  gap: 10px !important;
  padding: 9px 14px !important;
  font-size: 13px !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04) !important;
  cursor: pointer !important;
  transition: background 0.12s ease !important;
}
.uran-adv-row:hover,
.uran-adv-row:focus,
.uran-adv-row:focus-within {
  background: rgba(255, 255, 255, 0.06) !important;
}
.uran-adv-row.dim {
  opacity: 0.45;
}
.uran-adv-check {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  line-height: 1;
  border: 1.5px solid rgba(255, 255, 255, 0.35);
  color: #ffffff;
  transition: all 0.15s ease;
}
.uran-adv-check.on {
  background: #1a73e8;
  border-color: #1a73e8;
}
.uran-adv-id {
  width: 82px;
  flex: none;
  font-variant-numeric: tabular-nums;
  color: #c0caf5;
  font-family: monospace;
}
.uran-adv-label {
  flex: 1 1 0%;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.uran-adv-size {
  width: 90px;
  flex: none;
  text-align: right;
  color: #a0aec0;
  font-variant-numeric: tabular-nums;
  font-family: monospace;
}
.uran-badge {
  font-size: 10px !important;
  padding: 1px 6px !important;
  border-radius: 4px !important;
  flex: none !important;
  font-weight: 700 !important;
  letter-spacing: 0.3px !important;
  line-height: 14px !important;
}
.uran-badge-id { background: rgba(122,162,247,0.18); color: #7aa2f7; }
.uran-badge-arch { background: rgba(224,175,104,0.18); color: #e0af68; }
.uran-badge-lang { background: rgba(125,207,255,0.18); color: #7dcfff; }
.uran-badge-dlc { background: rgba(187,154,247,0.18); color: #bb9af7; }
.uran-badge-shared { background: rgba(126,226,168,0.18); color: #7ee2a8; }
.uran-badge-key { background: rgba(126,226,168,0.18); color: #7ee2a8; }
.uran-badge-nokey { background: rgba(247,118,142,0.18); color: #f7768e; }
.uran-badge-license { background: rgba(156,39,176,0.22); color: #ce93d8; border: 1px solid rgba(156,39,176,0.4); }
.uran-badge-appkey { background: rgba(33,150,243,0.22); color: #90caf9; border: 1px solid rgba(33,150,243,0.4); }

.uran-adv-foot {
  display: flex !important;
  flex-direction: row !important;
  align-items: center !important;
  gap: 10px !important;
  padding: 10px 22px !important;
  border-top: 1px solid rgba(255, 255, 255, 0.10) !important;
  background: #16171e !important;
  flex-shrink: 0 !important;
}
.uran-adv-foot .spacer {
  flex: 1 1 0%;
}
.uran-adv-msg {
  font-size: 12px;
  color: #7ee2a8;
  font-weight: 500;
}
.uran-adv-empty {
  padding: 36px 20px;
  text-align: center;
  color: #a0aec0;
  font-size: 13px;
}
`;

function osKey(d: AtomDepotInfo): string {
  if (d.is_shared) return "shared";
  const list = d.os_list && d.os_list.length ? d.os_list : [d.os];
  const first = (list[0] || "").toLowerCase();
  return first || "none";
}

function OsIcons({ d }: { d: AtomDepotInfo }) {
  const list = (d.os_list && d.os_list.length ? d.os_list : [d.os]).map((o) =>
    o.toLowerCase()
  );
  const has = (o: string) => list.includes(o);
  const props = { size: 14, style: { flex: "none" as const } };
  return (
    <>
      {has("windows") && <WindowsIcon {...props} />}
      {has("linux") && <LinuxIcon {...props} />}
      {has("macos") && <AppleIcon {...props} />}
      {has("android") && <AndroidIcon {...props} />}
    </>
  );
}

export function AdvancedPage() {
  const [games, setGames] = useState<AtomGame[]>([]);
  const [gamesLoading, setGamesLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [appId, setAppId] = useState(_target);
  const [detail, setDetail] = useState<AtomDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Staging sets for atomic multi-tab apply
  const [pickedDepots, setPickedDepots] = useState<Set<string>>(new Set());
  const [pickedDlcs, setPickedDlcs] = useState<Set<string>>(new Set());
  const [pickedKeys, setPickedKeys] = useState<Set<string>>(new Set());

  const [activeTab, setActiveTab] = useState<MainTab>("depots");
  const [filter, setFilter] = useState<DepotFilter>("all");
  const [showHidden, setShowHidden] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const selectedGameRef = useRef<HTMLDivElement>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const mainPaneRef = useRef<HTMLDivElement>(null);
  const firstTabRef = useRef<HTMLDivElement>(null);

  const handleGlobalKeyDown = (e: React.KeyboardEvent) => {
    // Shoulder bumpers: L1 (PageUp) -> Games List, R1 (PageDown) -> Details/Tabs
    if (e.key === "PageUp") {
      e.preventDefault();
      selectedGameRef.current?.focus();
      return;
    }
    if (e.key === "PageDown") {
      e.preventDefault();
      firstTabRef.current?.focus();
      return;
    }
  };

  // Load all registered games
  useEffect(() => {
    let alive = true;
    listAtomGames()
      .then((res) => {
        if (!alive) return;
        setGames(res?.ok ? res.games || [] : []);
      })
      .catch(() => alive && setGames([]))
      .finally(() => alive && setGamesLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const loadDetail = (id: string) => {
    setDetailLoading(true);
    setMsg("");
    getAtomGame(id)
      .then((res) => {
        if (!res?.ok) {
          setMsg(res?.error || "Could not load this game.");
          return;
        }
        setDetail(res);
        // Initialize staging sets from current configuration
        setPickedDepots(
          new Set(
            (res.depots_detail || [])
              .filter((d) => d.in_config && !d.is_app_key)
              .map((d) => d.id)
          )
        );
        setPickedDlcs(
          new Set(
            (res.dlcs_detail || [])
              .filter((d) => d.in_config)
              .map((d) => d.id)
          )
        );
        setPickedKeys(
          new Set(
            (res.keys_detail || [])
              .filter((k) => k.in_config)
              .map((k) => k.id)
          )
        );
      })
      .catch(() => setMsg("Could not load this game."))
      .finally(() => setDetailLoading(false));
  };

  useEffect(() => {
    if (appId) loadDetail(appId);
  }, [appId]);

  // Follow external target updates
  useEffect(() => subscribeAdvancedTarget(setAppId), []);

  // Land initial focus on the selected game in the left sidebar list
  useEffect(() => {
    if (!gamesLoading && selectedGameRef.current) {
      setTimeout(() => {
        selectedGameRef.current?.focus();
      }, 50);
    }
  }, [gamesLoading, appId]);

  // Data helpers
  const rows = useMemo(
    () => (detail?.depots_detail || []).filter((d) => !d.is_app_key),
    [detail]
  );
  const dlcs = useMemo(() => detail?.dlcs_detail || [], [detail]);
  const keys = useMemo(() => detail?.keys_detail || [], [detail]);

  const selectableDepot = (d: AtomDepotInfo) => d.has_key || d.is_shared;
  const hiddenRows = rows.filter((d) => !selectableDepot(d) && !d.is_shared);
  const selectableCount = rows.filter(selectableDepot).length;

  const visibleDepots = useMemo(() => {
    const filtered = rows.filter((d) => {
      if (!d.in_config && !selectableDepot(d) && !showHidden) return false;
      if (filter === "windows")
        return (d.os_list || [d.os]).some((o) => o.toLowerCase() === "windows");
      if (filter === "linux")
        return (d.os_list || [d.os]).some((o) => o.toLowerCase() === "linux");
      if (filter === "dlc") return !!d.is_dlc || !!d.owner;
      return true;
    });
    return filtered.sort((a, b) => {
      const oa = OS_PRIORITY[osKey(a)] ?? 3;
      const ob = OS_PRIORITY[osKey(b)] ?? 3;
      if (oa !== ob) return oa - ob;
      return Number(a.id) - Number(b.id);
    });
  }, [rows, filter, showHidden]);

  const shownGames = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return games;
    return games.filter(
      (g) => g.name.toLowerCase().includes(q) || g.app_id.includes(q)
    );
  }, [games, query]);

  // -- Toggle Helpers ---------------------------------------------------------
  const toggleDepot = (id: string) =>
    setPickedDepots((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleDlc = (id: string) =>
    setPickedDlcs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleKey = (id: string) =>
    setPickedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const allShownDepotsSelected =
    visibleDepots.length > 0 &&
    visibleDepots.filter(selectableDepot).every((d) => pickedDepots.has(d.id));

  const toggleAllDepots = () =>
    setPickedDepots((prev) => {
      const next = new Set(prev);
      visibleDepots.filter(selectableDepot).forEach((d) => {
        if (allShownDepotsSelected) next.delete(d.id);
        else next.add(d.id);
      });
      return next;
    });

  // Revert all 3 tabs back to config
  const revert = () => {
    if (!detail) return;
    setPickedDepots(
      new Set(
        (detail.depots_detail || [])
          .filter((d) => d.in_config && !d.is_app_key)
          .map((d) => d.id)
      )
    );
    setPickedDlcs(
      new Set(
        (detail.dlcs_detail || [])
          .filter((d) => d.in_config)
          .map((d) => d.id)
      )
    );
    setPickedKeys(
      new Set(
        (detail.keys_detail || [])
          .filter((k) => k.in_config)
          .map((k) => k.id)
      )
    );
    setMsg("Reverted changes to current configuration.");
  };

  // Atomic batch apply across Depots, DLCs, and Keys
  const apply = async () => {
    if (!appId || busy) return;
    setBusy(true);
    setMsg("Applying changes to SLSsteam config…");
    try {
      const res = await applyDepotSelection(
        appId,
        [...pickedDepots],
        [...pickedDlcs],
        [...pickedKeys]
      );
      if (res?.ok) {
        const dCount = res.depots_added?.length ?? pickedDepots.size;
        const dlcCount = res.dlc_appids?.length ?? pickedDlcs.size;
        const kCount = res.keys_added?.length ?? pickedKeys.size;
        setMsg(
          `Applied: ${dCount} depot(s), ${dlcCount} DLC(s), ${kCount} key(s) active.`
        );
        loadDetail(appId);
      } else {
        setMsg(res?.error || "Apply failed.");
      }
    } catch {
      setMsg("Apply failed.");
    } finally {
      setBusy(false);
    }
  };

  const refresh = async () => {
    if (!appId || busy) return;
    setBusy(true);
    setMsg("Refreshing freshest data from Hubcap…");
    try {
      const res = await refreshGame(appId);
      setMsg(res?.ok ? "Refreshed from Hubcap." : res?.error || "Refresh failed.");
      loadDetail(appId);
    } catch {
      setMsg("Refresh failed.");
    } finally {
      setBusy(false);
    }
  };

  const close = () => Navigation.NavigateBack();

  return (
    <Focusable
      className="uran-adv-root"
      flow-children="down"
      onCancel={close}
      onKeyDown={handleGlobalKeyDown}
      style={{ padding: 0 }}
    >
      <style>{STYLES}</style>

      {/* Top Header Bar */}
      <div className="uran-adv-bar">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <h2 className="uran-adv-title">Advanced — Depot &amp; Key Manager</h2>
            <span style={{ fontSize: "11px", color: "#a0aec0", background: "rgba(255,255,255,0.06)", padding: "2px 8px", borderRadius: "4px" }}>
              L1: Games | R1: Details
            </span>
          </div>
          <div className="uran-adv-sub">
            Pick a game on the left, then configure depots, license DLCs, and AES keys.
          </div>
        </div>
        <Focusable onActivate={close} onCancel={close}>
          <DialogButton
            style={{ minWidth: 0, padding: "6px 14px", fontSize: "12px" }}
            onClick={close}
          >
            Close
          </DialogButton>
        </Focusable>
      </div>

      {/* Two-Pane Body: Left (Sidebar) and Right (Main) */}
      <Focusable className="uran-adv-body" flow-children="right">
        {/* Left Sidebar: Game List with Search */}
        <Focusable className="uran-adv-side" flow-children="down" ref={sidebarRef}>
          <input
            className="uran-adv-search-box"
            placeholder="Search games…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <Focusable className="uran-adv-games" flow-children="down">
            {gamesLoading && (
              <div className="uran-adv-empty">
                <Spinner />
              </div>
            )}
            {!gamesLoading && shownGames.length === 0 && (
              <div className="uran-adv-empty">No AT0-M games found.</div>
            )}
            {shownGames.map((g) => (
              <Focusable
                key={g.app_id}
                ref={g.app_id === appId ? selectedGameRef : undefined}
                className={`uran-adv-game${g.app_id === appId ? " sel" : ""}`}
                onActivate={() => setAppId(g.app_id)}
                onKeyDown={(e: React.KeyboardEvent) => {
                  if (e.key === "ArrowRight") {
                    e.preventDefault();
                    e.stopPropagation();
                    firstTabRef.current?.focus();
                  }
                }}
              >
                <span className="nm">{g.name}</span>
                <span className="id">{g.app_id}</span>
              </Focusable>
            ))}
          </Focusable>
        </Focusable>

        {/* Right Main Pane: Subtabs, Table, and Footer */}
        <Focusable className="uran-adv-main" flow-children="down" ref={mainPaneRef}>
          {!appId && (
            <div className="uran-adv-empty">Select a game on the left.</div>
          )}

          {appId && (
            <>
              {/* Game Header */}
              <div className="uran-adv-mhead">
                <h3>{detail?.name || `App ${appId}`}</h3>
                <div className="uran-adv-meta">
                  <span>AppID: <strong style={{ color: "#7ee2a8", fontFamily: "monospace" }}>{appId}</strong></span>
                  <span>•</span>
                  <span>{pickedDepots.size} Depots Selected</span>
                  <span>•</span>
                  <span>{pickedDlcs.size} DLCs Active</span>
                  <span>•</span>
                  <span>{pickedKeys.size} Keys Configured</span>
                </div>
              </div>

              {/* Sub-Tabs: Depots | DLCs & Licenses | Decryption Keys */}
              <Focusable className="uran-adv-subtabs" flow-children="right">
                <DialogButton
                  ref={firstTabRef}
                  className="uran-adv-subtab-btn"
                  style={{
                    width: "auto",
                    minWidth: 0,
                    flex: "0 0 auto",
                    background: activeTab === "depots" ? "#1a73e8" : "rgba(255,255,255,0.06)",
                    color: activeTab === "depots" ? "#ffffff" : "#c5cdd8",
                  }}
                  onClick={() => setActiveTab("depots")}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === "ArrowLeft") {
                      e.preventDefault();
                      e.stopPropagation();
                      selectedGameRef.current?.focus();
                    }
                  }}
                >
                  Depots ({rows.length})
                </DialogButton>
                <DialogButton
                  className="uran-adv-subtab-btn"
                  style={{
                    width: "auto",
                    minWidth: 0,
                    flex: "0 0 auto",
                    background: activeTab === "dlcs" ? "#1a73e8" : "rgba(255,255,255,0.06)",
                    color: activeTab === "dlcs" ? "#ffffff" : "#c5cdd8",
                  }}
                  onClick={() => setActiveTab("dlcs")}
                >
                  DLCs &amp; Licenses ({dlcs.length})
                </DialogButton>
                <DialogButton
                  className="uran-adv-subtab-btn"
                  style={{
                    width: "auto",
                    minWidth: 0,
                    flex: "0 0 auto",
                    background: activeTab === "keys" ? "#1a73e8" : "rgba(255,255,255,0.06)",
                    color: activeTab === "keys" ? "#ffffff" : "#c5cdd8",
                  }}
                  onClick={() => setActiveTab("keys")}
                >
                  Decryption Keys ({keys.length})
                </DialogButton>
              </Focusable>

              {/* Filters (Shown only on Depots tab) */}
              {activeTab === "depots" && (
                <Focusable className="uran-adv-filters" flow-children="right">
                  {(["all", "windows", "linux", "dlc"] as DepotFilter[]).map((f) => (
                    <DialogButton
                      key={f}
                      className={`uran-adv-chip${filter === f ? " on" : ""}`}
                      style={{ width: "auto", minWidth: 0, flex: "0 0 auto", margin: 0 }}
                      onClick={() => setFilter(f)}
                      onKeyDown={(e: React.KeyboardEvent) => {
                        if (e.key === "ArrowLeft" && f === "all") {
                          e.preventDefault();
                          e.stopPropagation();
                          selectedGameRef.current?.focus();
                        }
                      }}
                    >
                      {f === "all" ? "All" : f === "dlc" ? "DLC Only" : f[0].toUpperCase() + f.slice(1)}
                    </DialogButton>
                  ))}
                  <DialogButton
                    className={`uran-adv-chip${showHidden ? " on" : ""}`}
                    style={{ width: "auto", minWidth: 0, flex: "0 0 auto", margin: 0 }}
                    onClick={() => setShowHidden((v) => !v)}
                  >
                    {showHidden ? "Hide" : "Show"} Hidden ({hiddenRows.length})
                  </DialogButton>
                </Focusable>
              )}

              {/* Main Table Content */}
              <div className="uran-adv-table">
                {detailLoading && (
                  <div className="uran-adv-empty">
                    <Spinner />
                  </div>
                )}

                {!detailLoading && activeTab === "depots" && (
                  <>
                    <Focusable
                      className="uran-adv-thead"
                      flow-children="right"
                      onActivate={toggleAllDepots}
                    >
                      <span className={`uran-adv-check${allShownDepotsSelected ? " on" : ""}`}>
                        {allShownDepotsSelected ? "✓" : ""}
                      </span>
                      <span className="uran-adv-id">
                        ({pickedDepots.size}/{selectableCount})
                      </span>
                      <span className="uran-adv-label">Depot Configuration</span>
                      <span className="uran-adv-size">Size</span>
                    </Focusable>

                    {visibleDepots.map((d) => {
                      const can = selectableDepot(d);
                      const on = pickedDepots.has(d.id);
                      return (
                        <Focusable
                          key={d.id}
                          className={`uran-adv-row${can ? "" : " dim"}`}
                          onActivate={() => can && toggleDepot(d.id)}
                          onKeyDown={(e: React.KeyboardEvent) => {
                            if (e.key === "ArrowLeft") {
                              e.preventDefault();
                              e.stopPropagation();
                              selectedGameRef.current?.focus();
                            }
                          }}
                        >
                          <span className={`uran-adv-check${on ? " on" : ""}`}>
                            {on ? "✓" : ""}
                          </span>
                          <span className="uran-adv-id">{d.id}</span>
                          <span className="uran-adv-label">
                            <OsIcons d={d} />
                            {d.arch && <span className="uran-badge uran-badge-arch">{d.arch}</span>}
                            {d.lang && <span className="uran-badge uran-badge-lang">{d.lang}</span>}
                            {d.is_shared ? (
                              <span className="uran-badge uran-badge-shared">Shared</span>
                            ) : (
                              (d.owner || d.is_dlc) && (
                                <span className="uran-badge uran-badge-dlc">
                                  DLC{d.owner ? ` ${d.owner}` : ""}
                                </span>
                              )
                            )}
                            {d.has_key ? (
                              <span className="uran-badge uran-badge-key">Key</span>
                            ) : (
                              <span className="uran-badge uran-badge-nokey">No key</span>
                            )}
                            <span>{d.name}</span>
                          </span>
                          <span className="uran-adv-size">{d.size_str || "—"}</span>
                        </Focusable>
                      );
                    })}
                  </>
                )}

                {!detailLoading && activeTab === "dlcs" && (
                  <>
                    <div className="uran-adv-thead">
                      <span className="uran-adv-check on">✓</span>
                      <span className="uran-adv-id">AppID</span>
                      <span className="uran-adv-label">Downloadable Content &amp; License Status</span>
                    </div>

                    {/* Base Game Row (Always Active) */}
                    <div className="uran-adv-row" style={{ opacity: 0.85 }}>
                      <span className="uran-adv-check on" style={{ opacity: 0.6 }}>✓</span>
                      <span className="uran-adv-id">{appId}</span>
                      <span className="uran-adv-label">
                        <span className="uran-badge uran-badge-shared" style={{ background: "#2e7d32", color: "#fff" }}>
                          Base Game • Core App
                        </span>
                        <span>{detail?.name} (Always active)</span>
                      </span>
                    </div>

                    {/* DLC Rows */}
                    {dlcs.length === 0 ? (
                      <div className="uran-adv-empty">No DLC AppIDs found for this game.</div>
                    ) : (
                      dlcs.map((dlc) => {
                        const on = pickedDlcs.has(dlc.id);
                        return (
                          <Focusable
                            key={dlc.id}
                            className="uran-adv-row"
                            onActivate={() => toggleDlc(dlc.id)}
                            onKeyDown={(e: React.KeyboardEvent) => {
                              if (e.key === "ArrowLeft") {
                                e.preventDefault();
                                e.stopPropagation();
                                selectedGameRef.current?.focus();
                              }
                            }}
                          >
                            <span className={`uran-adv-check${on ? " on" : ""}`}>
                              {on ? "✓" : ""}
                            </span>
                            <span className="uran-adv-id">{dlc.id}</span>
                            <span className="uran-adv-label">
                              {dlc.is_license_only ? (
                                <span className="uran-badge uran-badge-license">
                                  License Only (0 Byte / No Depot)
                                </span>
                              ) : (
                                <span className="uran-badge uran-badge-dlc">
                                  {dlc.depot_count ? `${dlc.depot_count} Depot${dlc.depot_count === 1 ? "" : "s"}` : "DLC"}
                                </span>
                              )}
                              <span>{dlc.name}</span>
                            </span>
                          </Focusable>
                        );
                      })
                    )}
                  </>
                )}

                {!detailLoading && activeTab === "keys" && (
                  <>
                    <div className="uran-adv-thead">
                      <span className="uran-adv-check on">✓</span>
                      <span className="uran-adv-id">Target ID</span>
                      <span className="uran-adv-label">Decryption Key Details</span>
                    </div>

                    {keys.length === 0 ? (
                      <div className="uran-adv-empty">No AES keys configured yet.</div>
                    ) : (
                      keys.map((k) => {
                        const on = pickedKeys.has(k.id);
                        return (
                          <Focusable
                            key={k.id}
                            className="uran-adv-row"
                            onActivate={() => toggleKey(k.id)}
                            onKeyDown={(e: React.KeyboardEvent) => {
                              if (e.key === "ArrowLeft") {
                                e.preventDefault();
                                e.stopPropagation();
                                selectedGameRef.current?.focus();
                              }
                            }}
                          >
                            <span className={`uran-adv-check${on ? " on" : ""}`}>
                              {on ? "✓" : ""}
                            </span>
                            <span className="uran-adv-id">{k.id}</span>
                            <span className="uran-adv-label">
                              {k.is_appkey && (
                                <span className="uran-badge uran-badge-appkey">Root AppKey</span>
                              )}
                              <span
                                style={{
                                  fontFamily: "monospace",
                                  fontSize: "11px",
                                  color: "#7ee2a8",
                                  letterSpacing: "0.5px",
                                  marginRight: 6,
                                }}
                              >
                                {k.masked_key || "••••••••••••••••"}
                              </span>
                              {k.in_local ? (
                                <span
                                  className="uran-badge uran-badge-key"
                                  style={{ display: "inline-flex", alignItems: "center", gap: 3 }}
                                >
                                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#4caf50" }} />
                                  Local
                                </span>
                              ) : (
                                <span className="uran-badge uran-badge-arch">Hubcap</span>
                              )}
                              <span>{k.name}</span>
                            </span>
                          </Focusable>
                        );
                      })
                    )}
                  </>
                )}
              </div>

              {/* Bottom Action Footer */}
              <Focusable className="uran-adv-foot" flow-children="right">
                <span className="uran-adv-msg">{msg}</span>
                <span className="spacer" />
                <DialogButton
                  style={{ minWidth: 0, padding: "7px 16px", fontSize: "12px" }}
                  onClick={revert}
                  disabled={busy}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === "ArrowLeft") {
                      e.preventDefault();
                      e.stopPropagation();
                      selectedGameRef.current?.focus();
                    }
                  }}
                >
                  Revert
                </DialogButton>
                <DialogButton
                  style={{ minWidth: 0, padding: "7px 16px", fontSize: "12px" }}
                  onClick={refresh}
                  disabled={busy}
                >
                  Refresh Hubcap
                </DialogButton>
                <DialogButton
                  style={{
                    minWidth: 0,
                    padding: "7px 18px",
                    fontSize: "12px",
                    background: "#1a73e8",
                    color: "#ffffff",
                    fontWeight: 700,
                  }}
                  onClick={apply}
                  disabled={busy}
                >
                  Apply Selection
                </DialogButton>
              </Focusable>
            </>
          )}
        </Focusable>
      </Focusable>
    </Focusable>
  );
}

export default AdvancedPage;
