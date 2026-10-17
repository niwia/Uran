import React, { useState, useEffect } from "react";
import {
  ModalRoot,
  DialogBody,
  DialogButton,
  ToggleField,
  Focusable,
  Spinner,
} from "@decky/ui";
import {
  AtomDetail,
  AtomDepotInfo,
  AtomDlcInfo,
  AtomKeyInfo,
  getAtomGame,
  toggleAdditionalApp,
  toggleAdditionalDepot,
  toggleDecryptionKey,
  refreshGame,
} from "../api";
import { notify } from "../notify";
import {
  WindowsIcon,
  LinuxIcon,
  AppleIcon,
  AndroidIcon,
} from "./icons";

export interface DepotManagerModalProps {
  appId: string;
  appName: string;
  initialDetail?: AtomDetail | null;
  closeModal?: () => void;
  onUpdate?: () => void;
}

const MODAL_STYLES = `
  .uran-modal-container {
    display: flex !important;
    flex-direction: column !important;
    width: 100% !important;
    max-height: 85vh !important;
    color: #ffffff !important;
    box-sizing: border-box !important;
  }
  .uran-modal-header {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    padding: 16px 20px 14px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08) !important;
    background: rgba(0, 0, 0, 0.25) !important;
  }
  .uran-modal-title-col {
    display: flex !important;
    flex-direction: column !important;
    gap: 4px !important;
    min-width: 0 !important;
    flex: 1 1 auto !important;
  }
  .uran-modal-title {
    font-size: 19px !important;
    font-weight: 700 !important;
    color: #ffffff !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
  }
  .uran-modal-subtitle {
    font-size: 12px !important;
    color: rgba(255, 255, 255, 0.65) !important;
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
    flex-wrap: wrap !important;
  }
  .uran-modal-nav-bar {
    display: flex !important;
    gap: 8px !important;
    padding: 10px 20px !important;
    background: rgba(0, 0, 0, 0.15) !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
  }
  .uran-modal-tab-btn {
    flex: 1 1 0% !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 8px 12px !important;
    font-size: 13px !important;
    border-radius: 8px !important;
    cursor: pointer !important;
    transition: all 0.15s ease !important;
  }
  .uran-modal-filter-bar {
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    padding: 10px 20px !important;
    border-bottom: 1px solid rgba(255, 255, 255, 0.04) !important;
    background: rgba(255, 255, 255, 0.02) !important;
  }
  .uran-modal-filter-btn {
    padding: 4px 12px !important;
    font-size: 11px !important;
    height: 28px !important;
    min-height: 28px !important;
    min-width: 0 !important;
    border-radius: 6px !important;
  }
  .uran-modal-content {
    flex: 1 1 auto !important;
    overflow-y: auto !important;
    padding: 12px 20px 20px !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
  }
  .uran-modal-section-info {
    font-size: 12px !important;
    color: rgba(255, 255, 255, 0.55) !important;
    padding: 4px 0 8px !important;
    line-height: 1.4 !important;
  }
  .uran-modal-footer {
    display: flex !important;
    justify-content: space-between !important;
    align-items: center !important;
    padding: 12px 20px !important;
    border-top: 1px solid rgba(255, 255, 255, 0.08) !important;
    background: rgba(0, 0, 0, 0.25) !important;
  }
  .uran-modal-row-wrapper {
    background: rgba(255, 255, 255, 0.03) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 8px !important;
    margin-bottom: 6px !important;
    overflow: hidden !important;
    transition: border-color 0.15s ease !important;
  }
  .uran-modal-row-wrapper:hover,
  .uran-modal-row-wrapper:focus-within {
    border-color: rgba(26, 115, 232, 0.5) !important;
  }
  .uran-badge {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    padding: 1px 6px !important;
    border-radius: 4px !important;
    line-height: 14px !important;
  }
  .uran-badge-id {
    font-family: monospace !important;
    background: rgba(255, 255, 255, 0.08) !important;
    color: #c0caf5 !important;
  }
  .uran-badge-arch {
    background: rgba(122, 162, 247, 0.15) !important;
    color: #7aa2f7 !important;
    border: 1px solid rgba(122, 162, 247, 0.3) !important;
  }
  .uran-badge-lang {
    background: rgba(224, 175, 104, 0.15) !important;
    color: #e0af68 !important;
    border: 1px solid rgba(224, 175, 104, 0.3) !important;
  }
  .uran-badge-dlc {
    background: rgba(187, 154, 247, 0.15) !important;
    color: #bb9af7 !important;
    border: 1px solid rgba(187, 154, 247, 0.3) !important;
  }
  .uran-badge-key {
    background: rgba(126, 226, 168, 0.15) !important;
    color: #7ee2a8 !important;
    border: 1px solid rgba(126, 226, 168, 0.3) !important;
  }
  .uran-badge-nokey {
    background: rgba(247, 118, 142, 0.12) !important;
    color: #f7768e !important;
    border: 1px solid rgba(247, 118, 142, 0.25) !important;
  }
  .uran-badge-config {
    background: rgba(65, 166, 181, 0.15) !important;
    color: #7dcfff !important;
    border: 1px solid rgba(65, 166, 181, 0.3) !important;
  }
  .uran-badge-license {
    background: rgba(156, 39, 176, 0.2) !important;
    color: #ce93d8 !important;
    border: 1px solid rgba(156, 39, 176, 0.35) !important;
  }
  .uran-badge-appkey {
    background: rgba(33, 150, 243, 0.2) !important;
    color: #90caf9 !important;
    border: 1px solid rgba(33, 150, 243, 0.35) !important;
  }
  .uran-badge-size {
    background: rgba(255, 255, 255, 0.06) !important;
    color: #e0e0e0 !important;
    font-family: monospace !important;
  }
`;

export const DepotManagerModal: React.FC<DepotManagerModalProps> = ({
  appId,
  appName,
  initialDetail = null,
  closeModal,
  onUpdate,
}) => {
  const [detail, setDetail] = useState<AtomDetail | null>(initialDetail);
  const [loading, setLoading] = useState<boolean>(!initialDetail);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"depots" | "apps" | "keys">("depots");
  const [depotFilter, setDepotFilter] = useState<"all" | "windows" | "linux" | "dlc">("all");

  const reloadDetail = async () => {
    try {
      const fresh = await getAtomGame(appId);
      if (fresh) setDetail(fresh);
    } catch (e) {
      console.error("[DepotManagerModal] Failed to reload game detail:", e);
    }
  };

  useEffect(() => {
    if (!initialDetail) {
      setLoading(true);
      reloadDetail().finally(() => setLoading(false));
    }
  }, [appId]);

  // -- Toggle actions ---------------------------------------------------------
  const handleToggleDepot = async (depotId: string, enable: boolean) => {
    setBusyAction(`depot-${depotId}`);
    setDetail((prev) => {
      if (!prev || !prev.depots_detail) return prev;
      return {
        ...prev,
        depots_detail: prev.depots_detail.map((d) =>
          d.id === depotId ? { ...d, in_config: enable } : d
        ),
      };
    });

    try {
      const res = await toggleAdditionalDepot(appId, depotId, enable);
      if (!res.ok) {
        notify("Depot Error", res.error || "Failed to update depot");
        await reloadDetail();
      } else {
        notify(
          "Depots Updated",
          `${enable ? "Mounted" : "Unmounted"} depot ${depotId}`
        );
        onUpdate?.();
      }
    } catch (err: any) {
      notify("Depot Error", err?.message || String(err));
      await reloadDetail();
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleDlc = async (dlcId: string, enable: boolean) => {
    setBusyAction(`dlc-${dlcId}`);
    setDetail((prev) => {
      if (!prev || !prev.dlcs_detail) return prev;
      return {
        ...prev,
        dlcs_detail: prev.dlcs_detail.map((d) =>
          d.id === dlcId ? { ...d, in_config: enable } : d
        ),
      };
    });

    try {
      const res = await toggleAdditionalApp(appId, dlcId, enable);
      if (!res.ok) {
        notify("DLC Error", res.error || "Failed to toggle DLC");
        await reloadDetail();
      } else {
        notify(
          "DLC Updated",
          `${enable ? "Enabled" : "Disabled"} DLC ${dlcId}`
        );
        onUpdate?.();
      }
    } catch (err: any) {
      notify("DLC Error", err?.message || String(err));
      await reloadDetail();
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleKey = async (targetId: string, enable: boolean) => {
    setBusyAction(`key-${targetId}`);
    setDetail((prev) => {
      if (!prev || !prev.keys_detail) return prev;
      return {
        ...prev,
        keys_detail: prev.keys_detail.map((k) =>
          k.id === targetId ? { ...k, in_config: enable } : k
        ),
      };
    });

    try {
      const res = await toggleDecryptionKey(appId, targetId, enable);
      if (!res.ok) {
        notify("Key Error", res.error || "Failed to toggle key");
        await reloadDetail();
      } else {
        notify(
          "Key Updated",
          `${enable ? "Configured" : "Excluded"} key ${targetId}`
        );
        onUpdate?.();
      }
    } catch (err: any) {
      notify("Key Error", err?.message || String(err));
      await reloadDetail();
    } finally {
      setBusyAction(null);
    }
  };

  const handleRefreshHubcap = async () => {
    setRefreshing(true);
    try {
      notify("Hubcap", "Checking freshest depots and keys from Hubcap…");
      const res = await refreshGame(appId);
      if (res?.ok) {
        const dCount = res.depots_added?.length ?? 0;
        const kCount = res.keys_added?.length ?? 0;
        notify(
          "Hubcap Refresh",
          `Updated config: +${dCount} depot(s), +${kCount} key(s)`
        );
        await reloadDetail();
        onUpdate?.();
      } else {
        notify("Refresh Error", res?.error || "Failed to refresh");
      }
    } catch (err: any) {
      notify("Refresh Error", err?.message || String(err));
    } finally {
      setRefreshing(false);
    }
  };

  // -- Filtered collections ---------------------------------------------------
  const depots = detail?.depots_detail || [];
  const dlcs = detail?.dlcs_detail || [];
  const keys = detail?.keys_detail || [];

  const mountedDepotsCount = depots.filter((d) => d.in_config).length;
  const enabledDlcsCount = dlcs.filter((d) => d.in_config).length;
  const activeKeysCount = keys.filter((k) => k.in_config).length;

  const hasWindows = depots.some((d) => d.os_list?.includes("windows"));
  const hasLinux = depots.some((d) => d.os_list?.includes("linux"));
  const hasDlc = depots.some((d) => d.is_dlc);

  const filteredDepots = depots.filter((d) => {
    if (depotFilter === "windows" && !d.os_list?.includes("windows")) return false;
    if (depotFilter === "linux" && !d.os_list?.includes("linux")) return false;
    if (depotFilter === "dlc" && !d.is_dlc) return false;
    return true;
  });

  return (
    <ModalRoot
      onCancel={closeModal}
      onEscKeypress={closeModal}
      closeModal={closeModal}
      bAllowFullSize={true}
    >
      <style>{MODAL_STYLES}</style>
      <Focusable className="uran-modal-container">
        {/* Header with Title, Stats, and Top Action Buttons */}
        <Focusable className="uran-modal-header" flow-children="row">
          <div className="uran-modal-title-col">
            <div className="uran-modal-title">{appName || `App ${appId}`}</div>
            <div className="uran-modal-subtitle">
              <span>
                AppID: <strong style={{ color: "#7ee2a8", fontFamily: "monospace" }}>{appId}</strong>
              </span>
              <span>•</span>
              <span>{mountedDepotsCount} Depots Mounted</span>
              <span>•</span>
              <span>{enabledDlcsCount} DLCs Active</span>
              <span>•</span>
              <span>{activeKeysCount} Keys Configured</span>
            </div>
          </div>
          <Focusable style={{ display: "flex", gap: "8px", alignItems: "center" }} flow-children="row">
            <DialogButton
              disabled={refreshing}
              onClick={handleRefreshHubcap}
              style={{
                minWidth: "fit-content",
                padding: "6px 14px",
                fontSize: "12px",
                borderRadius: "6px",
              }}
            >
              {refreshing ? "Refreshing…" : "🔄 Refresh Hubcap"}
            </DialogButton>
            <DialogButton
              onClick={closeModal}
              style={{
                minWidth: "fit-content",
                padding: "6px 14px",
                fontSize: "12px",
                borderRadius: "6px",
                background: "rgba(255, 255, 255, 0.1)",
              }}
            >
              ✕ Close
            </DialogButton>
          </Focusable>
        </Focusable>

        {/* 3 Main Tabs: AdditionalDepots | AdditionalApps | DecryptionKeys */}
        <Focusable className="uran-modal-nav-bar" flow-children="row">
          <DialogButton
            className="uran-modal-tab-btn"
            style={{
              background: activeTab === "depots" ? "#1a73e8" : "rgba(255,255,255,0.06)",
              color: activeTab === "depots" ? "#ffffff" : "#c5cdd8",
              fontWeight: activeTab === "depots" ? 700 : 500,
            }}
            onClick={() => setActiveTab("depots")}
          >
            🗄️ AdditionalDepots ({depots.length})
          </DialogButton>
          <DialogButton
            className="uran-modal-tab-btn"
            style={{
              background: activeTab === "apps" ? "#1a73e8" : "rgba(255,255,255,0.06)",
              color: activeTab === "apps" ? "#ffffff" : "#c5cdd8",
              fontWeight: activeTab === "apps" ? 700 : 500,
            }}
            onClick={() => setActiveTab("apps")}
          >
            📦 AdditionalApps ({dlcs.length + 1})
          </DialogButton>
          <DialogButton
            className="uran-modal-tab-btn"
            style={{
              background: activeTab === "keys" ? "#1a73e8" : "rgba(255,255,255,0.06)",
              color: activeTab === "keys" ? "#ffffff" : "#c5cdd8",
              fontWeight: activeTab === "keys" ? 700 : 500,
            }}
            onClick={() => setActiveTab("keys")}
          >
            🔑 DecryptionKeys ({keys.length})
          </DialogButton>
        </Focusable>

        {/* Sub-filter bar for Depots tab */}
        {activeTab === "depots" && (hasWindows || hasLinux || hasDlc) && (
          <Focusable className="uran-modal-filter-bar" flow-children="row">
            <span style={{ fontSize: "11px", opacity: 0.6, marginRight: 4 }}>Filter:</span>
            <DialogButton
              className="uran-modal-filter-btn"
              style={{
                background: depotFilter === "all" ? "#3a5c8d" : "rgba(255,255,255,0.08)",
                color: depotFilter === "all" ? "#ffffff" : "#c5cdd8",
              }}
              onClick={() => setDepotFilter("all")}
            >
              All ({depots.length})
            </DialogButton>
            {hasWindows && (
              <DialogButton
                className="uran-modal-filter-btn"
                style={{
                  background: depotFilter === "windows" ? "#3a5c8d" : "rgba(255,255,255,0.08)",
                  color: depotFilter === "windows" ? "#ffffff" : "#c5cdd8",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
                onClick={() => setDepotFilter("windows")}
              >
                <WindowsIcon size={12} />
                Windows
              </DialogButton>
            )}
            {hasLinux && (
              <DialogButton
                className="uran-modal-filter-btn"
                style={{
                  background: depotFilter === "linux" ? "#3a5c8d" : "rgba(255,255,255,0.08)",
                  color: depotFilter === "linux" ? "#ffffff" : "#c5cdd8",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "4px",
                }}
                onClick={() => setDepotFilter("linux")}
              >
                <LinuxIcon size={12} />
                Linux
              </DialogButton>
            )}
            {hasDlc && (
              <DialogButton
                className="uran-modal-filter-btn"
                style={{
                  background: depotFilter === "dlc" ? "#3a5c8d" : "rgba(255,255,255,0.08)",
                  color: depotFilter === "dlc" ? "#ffffff" : "#c5cdd8",
                }}
                onClick={() => setDepotFilter("dlc")}
              >
                DLC Only
              </DialogButton>
            )}
          </Focusable>
        )}

        {/* Scrollable Content Body */}
        <Focusable className="uran-modal-content" flow-children="column">
          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", padding: "40px 0" }}>
              <Spinner />
              <span style={{ marginLeft: 12, fontSize: "13px", opacity: 0.7 }}>Loading game details…</span>
            </div>
          ) : (
            <>
              {/* === TAB 1: AdditionalDepots === */}
              {activeTab === "depots" && (
                <>
                  <div className="uran-modal-section-info">
                    Depots mounted by SLSsteam in config.yaml. Shared Steamworks redists (e.g. VC++ runtime)
                    and Root AppKey are filtered out automatically so only actual game content is shown.
                  </div>
                  {filteredDepots.length > 0 ? (
                    filteredDepots.map((d) => (
                      <Focusable key={d.id} className="uran-modal-row-wrapper">
                        <ToggleField
                          label={
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 600, fontSize: "14px", color: "#ffffff" }}>
                                {d.name || `Depot ${d.id}`}
                              </span>
                              <span className="uran-badge uran-badge-id">{d.id}</span>
                            </div>
                          }
                          description={
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", marginTop: "4px" }}>
                              {d.os_list && d.os_list.length > 0 && (
                                <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                                  {d.os_list.includes("windows") && <WindowsIcon size={13} />}
                                  {d.os_list.includes("linux") && <LinuxIcon size={13} />}
                                  {d.os_list.includes("macos") && <AppleIcon size={13} />}
                                  {d.os_list.includes("android") && <AndroidIcon size={13} />}
                                </span>
                              )}
                              {d.arch && <span className="uran-badge uran-badge-arch">{d.arch}</span>}
                              {d.lang && <span className="uran-badge uran-badge-lang">{d.lang}</span>}
                              {d.size_str && <span className="uran-badge uran-badge-size">{d.size_str}</span>}
                              {d.is_dlc && (
                                <span className="uran-badge uran-badge-dlc">
                                  {d.owner || d.dlc_id ? `DLC ${d.owner || d.dlc_id}` : "DLC"}
                                </span>
                              )}
                              <span className={`uran-badge ${d.has_key ? "uran-badge-key" : "uran-badge-nokey"}`}>
                                {d.has_key ? "Key Available" : "No Key"}
                              </span>
                              {d.in_config && <span className="uran-badge uran-badge-config">Mounted</span>}
                            </div>
                          }
                          checked={d.in_config}
                          disabled={busyAction === `depot-${d.id}` || refreshing}
                          onChange={(checked) => handleToggleDepot(d.id, checked)}
                        />
                      </Focusable>
                    ))
                  ) : (
                    <div style={{ padding: "30px 0", textAlign: "center", opacity: 0.6, fontSize: "13px" }}>
                      No depots match the current filter.
                    </div>
                  )}
                </>
              )}

              {/* === TAB 2: AdditionalApps === */}
              {activeTab === "apps" && (
                <>
                  <div className="uran-modal-section-info">
                    Steam AppIDs authorized for this game in config.yaml. DLCs without dedicated depots are
                    pure license activations and do not require depot mounting.
                  </div>
                  {/* Base Game Row (Always Active) */}
                  <Focusable className="uran-modal-row-wrapper">
                    <ToggleField
                      label={
                        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                          <span style={{ fontWeight: 600, fontSize: "14px", color: "#ffffff" }}>
                            {appName}
                          </span>
                          <span className="uran-badge uran-badge-id">{appId}</span>
                        </div>
                      }
                      description={
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", marginTop: "4px" }}>
                          <span className="uran-badge uran-badge-config" style={{ background: "#2e7d32" }}>
                            Base Game • Core App
                          </span>
                          <span style={{ fontSize: "11px", opacity: 0.7 }}>
                            Primary application identifier (always active)
                          </span>
                        </div>
                      }
                      checked={true}
                      disabled={true}
                      onChange={() => {}}
                    />
                  </Focusable>

                  {/* DLC Rows */}
                  {dlcs.length > 0 ? (
                    dlcs.map((dlc) => (
                      <Focusable key={dlc.id} className="uran-modal-row-wrapper">
                        <ToggleField
                          label={
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 600, fontSize: "14px", color: "#ffffff" }}>
                                {dlc.name}
                              </span>
                              <span className="uran-badge uran-badge-id">{dlc.id}</span>
                            </div>
                          }
                          description={
                            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap", marginTop: "4px" }}>
                              {dlc.is_license_only ? (
                                <span className="uran-badge uran-badge-license">
                                  License Only (0 Byte / No Depot)
                                </span>
                              ) : (
                                <span className="uran-badge uran-badge-dlc">
                                  {dlc.depot_count ? `${dlc.depot_count} Depot${dlc.depot_count === 1 ? "" : "s"}` : "DLC"}
                                </span>
                              )}
                              {dlc.in_config && <span className="uran-badge uran-badge-config">Active</span>}
                            </div>
                          }
                          checked={dlc.in_config}
                          disabled={busyAction === `dlc-${dlc.id}` || refreshing}
                          onChange={(checked) => handleToggleDlc(dlc.id, checked)}
                        />
                      </Focusable>
                    ))
                  ) : (
                    <div style={{ padding: "30px 0", textAlign: "center", opacity: 0.6, fontSize: "13px" }}>
                      No DLC AppIDs found for this game.
                    </div>
                  )}
                </>
              )}

              {/* === TAB 3: DecryptionKeys === */}
              {activeTab === "keys" && (
                <>
                  <div className="uran-modal-section-info">
                    AES decryption keys configured for this game. Includes the Root AppKey (game executable)
                    and individual content depot keys. Green dot indicates key is cached locally.
                  </div>
                  {keys.length > 0 ? (
                    keys.map((k) => (
                      <Focusable key={k.id} className="uran-modal-row-wrapper">
                        <ToggleField
                          label={
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                              <span style={{ fontWeight: 600, fontSize: "14px", color: "#ffffff" }}>
                                {k.name}
                              </span>
                              <span className="uran-badge uran-badge-id">{k.id}</span>
                              {k.is_appkey && (
                                <span className="uran-badge uran-badge-appkey">Root AppKey</span>
                              )}
                            </div>
                          }
                          description={
                            <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap", marginTop: "4px" }}>
                              <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#7ee2a8", letterSpacing: "0.5px" }}>
                                {k.masked_key || "••••••••••••••••"}
                              </span>
                              {k.in_local ? (
                                <span className="uran-badge uran-badge-key" style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
                                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#4caf50", display: "inline-block" }} />
                                  Local Cache
                                </span>
                              ) : (
                                <span className="uran-badge uran-badge-arch">Hubcap</span>
                              )}
                              {k.in_config && <span className="uran-badge uran-badge-config">Configured</span>}
                            </div>
                          }
                          checked={k.in_config}
                          disabled={busyAction === `key-${k.id}` || refreshing}
                          onChange={(checked) => handleToggleKey(k.id, checked)}
                        />
                      </Focusable>
                    ))
                  ) : (
                    <div style={{ padding: "30px 0", textAlign: "center", opacity: 0.6, fontSize: "13px" }}>
                      No AES keys configured yet. Click &quot;Refresh Hubcap&quot; to fetch keys.
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </Focusable>

        {/* Footer with Gamepad instructions & Close button */}
        <Focusable className="uran-modal-footer" flow-children="row">
          <div style={{ fontSize: "11px", opacity: 0.5, display: "flex", alignItems: "center", gap: "6px" }}>
            <span>Gamepad: Navigate with D-Pad, press (A) to toggle, press (B) to close.</span>
          </div>
          <DialogButton
            onClick={closeModal}
            style={{ minWidth: "100px", padding: "8px 18px", fontSize: "13px", borderRadius: "6px" }}
          >
            Close
          </DialogButton>
        </Focusable>
      </Focusable>
    </ModalRoot>
  );
};

export default DepotManagerModal;
