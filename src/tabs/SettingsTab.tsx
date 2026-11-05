import React, { useState, useEffect, useCallback } from "react";
import {
  PanelSection,
  PanelSectionRow,
  Field,
  ToggleField,
  ButtonItem,
  DropdownItem,
  TextField,
} from "@decky/ui";
import { FaKey, FaQrcode, FaSyncAlt } from "react-icons/fa";
import {
  NOTIFICATION_MODE_OPTIONS,
  notify,
  refreshNotificationChannel,
  setNotificationMode,
} from "../notify";
import {
  getSetting,
  setSetting,
  getHubcapKeyStatus,
  getHubcapUserStats,
  saveHubcapKey,
  validateHubcapKey,
  getHealthStatus,
  once,
  refreshOnce,
  checkConfigStatus,
  isGlobalSlsOnlineEnabled,
  setGlobalSlsOnline,
  testHubcapRoutes,
  checkForUpdates,
  getPluginInfo,
  GATEWAY_LABELS,
  type HealthStatus,
  type ConfigCheck,
  type UpdateInfo,
  type GatewayMode,
  type RouteProbe,
} from "../api";
import { setStorePatchEnabled } from "../StorePatch";
import { formatExpiry } from "../components/format";
import { showQrKeyModal } from "../components/QrKeyModal";

interface SettingsTabProps {
  onSetupStatusChange?: (setupComplete: boolean) => void;
}

export const SettingsTab: React.FC<SettingsTabProps> = ({ onSetupStatusChange }) => {
  // General settings
  const [steamStoreEnabled, setSteamStoreEnabled] = useState(true);
  const [addDelistedDlcs, setAddDelistedDlcs] = useState(true);
  const [notificationMode, setNotificationModeState] = useState<"auto" | "steam" | "desktop" | "none">("auto");

  // Health & Environment
  const [health, setHealth] = useState<HealthStatus | null>(null);

  // Hubcap Key & User stats
  const [keyStatus, setKeyStatus] = useState<{
    ok: boolean;
    source: string;
    configured_path: string;
    masked: string;
    is_override: boolean;
    timestamp?: number;
  } | null>(null);
  const [stats, setStats] = useState<{
    ok: boolean;
    username?: string;
    daily_usage?: number;
    daily_limit?: number;
    requests_remaining?: number | null;
    expires_at?: string;
    error?: string;
  }>({ ok: false });

  // Key manual input
  const [manualKey, setManualKey] = useState("");
  const [showManualKeyInput, setShowManualKeyInput] = useState(false);
  const [savingKey, setSavingKey] = useState(false);

  // Advanced & Diagnostics
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [globalSlsOnline, setGlobalSlsOnlineState] = useState(false);
  const [gatewayMode, setGatewayMode] = useState<GatewayMode>("auto");
  const [routeProbe, setRouteProbe] = useState<RouteProbe | null>(null);
  const [testingRoutes, setTestingRoutes] = useState(false);
  const [checkingConfig, setCheckingConfig] = useState(false);
  const [configCheck, setConfigCheck] = useState<ConfigCheck | null>(null);
  const [pluginInfo, setPluginInfo] = useState<{ name: string; version: string }>({
    name: "Uran",
    version: "0.7.1",
  });
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);

  // Health (plugin presence, SLSsteam version) and Hubcap stats are cached for
  // the session: opening Settings must not re-run the checks every time.
  // `fresh` re-runs them (after saving a key, or from Refresh).
  const loadHealthAndKey = useCallback(async (fresh: boolean = false) => {
    try {
      const cached = fresh ? refreshOnce : once;
      const [h, k, s] = await Promise.all([
        cached("health", getHealthStatus).catch(() => null),
        getHubcapKeyStatus().catch(() => null),
        cached("hubcap_stats", getHubcapUserStats).catch(() => ({ ok: false })),
      ]);
      if (h) setHealth(h);
      if (k) setKeyStatus(k);
      if (s) setStats(s);

      const isSlsReady = h?.sls?.status !== "no_local";
      const hasPlugins = (h?.plugins?.plugins?.length ?? 0) > 0 && (h?.plugins?.missing?.length ?? 0) === 0;
      const hasKey = Boolean(k?.masked);
      onSetupStatusChange?.(isSlsReady && hasPlugins && hasKey);
    } catch {
      // ignore
    }
  }, [onSetupStatusChange]);

  useEffect(() => {
    loadHealthAndKey();

    getSetting("steam_store_enabled", true)
      .then((v) => setSteamStoreEnabled(Boolean(v)))
      .catch(() => {});
    getSetting("add_delisted_dlcs", true)
      .then((v) => setAddDelistedDlcs(Boolean(v)))
      .catch(() => {});
    getSetting("notification_mode", "auto")
      .then((v) => setNotificationModeState(v as any))
      .catch(() => {});
    getSetting("hubcap_gateway", "auto")
      .then((v) => setGatewayMode(v as GatewayMode))
      .catch(() => {});

    isGlobalSlsOnlineEnabled()
      .then((v) => setGlobalSlsOnlineState(Boolean(v?.enabled)))
      .catch(() => {});

    getPluginInfo()
      .then((info) => info && setPluginInfo(info))
      .catch(() => {});
  }, [loadHealthAndKey]);

  // Key save handler
  const handleSaveKey = async () => {
    const raw = manualKey.trim();
    if (!raw) return;
    setSavingKey(true);
    try {
      const val = await validateHubcapKey(raw);
      if (!val?.ok) {
        notify("Hubcap Key", val?.message || "Invalid API key format");
        return;
      }
      const saved = await saveHubcapKey(raw);
      if (saved?.ok) {
        notify("Hubcap Key", "API key saved successfully");
        setManualKey("");
        setShowManualKeyInput(false);
        loadHealthAndKey(true);
      } else {
        notify("Hubcap Key", saved?.message || "Failed to save key");
      }
    } finally {
      setSavingKey(false);
    }
  };

  const handleToggleSteamStore = async (val: boolean) => {
    setSteamStoreEnabled(val);
    await setSetting("steam_store_enabled", val);
    setStorePatchEnabled(val);
    notify("Steam Store", val ? "Store injection enabled" : "Store injection disabled");
  };

  const handleToggleAddDelisted = async (val: boolean) => {
    setAddDelistedDlcs(val);
    await setSetting("add_delisted_dlcs", val);
  };

  const handleNotificationModeChange = async (opt: any) => {
    const val = opt.data;
    setNotificationModeState(val);
    setNotificationMode(val);
    await setSetting("notification_mode", val);
    await refreshNotificationChannel();
  };

  const handleToggleGlobalSlsOnline = async (val: boolean) => {
    const res = await setGlobalSlsOnline(val);
    if (res?.ok) {
      setGlobalSlsOnlineState(val);
      notify("Global SLS Online", val ? "Enabled for all games (0: 480)" : "Disabled");
    } else {
      notify("Global SLS Online", "Failed to toggle Global SLS Online");
    }
  };

  const handleGatewayChange = async (opt: any) => {
    const mode = opt.data as GatewayMode;
    setGatewayMode(mode);
    await setSetting("hubcap_gateway", mode);
    notify("Hubcap Gateway", `Switched to ${GATEWAY_LABELS[mode] || mode}`);
  };

  const handleTestRoutes = async () => {
    setTestingRoutes(true);
    try {
      const res = await testHubcapRoutes();
      if (res?.ok) {
        setRouteProbe(res);
        const directMs = res.routes?.direct?.ms ? `${res.routes.direct.ms}ms` : "unreachable";
        notify("Route Test", `Direct: ${directMs}`);
      }
    } finally {
      setTestingRoutes(false);
    }
  };

  const handleCheckConfig = async () => {
    setCheckingConfig(true);
    try {
      const res = await checkConfigStatus(true);
      if (res?.ok) {
        setConfigCheck(res);
        notify("Config Check", res.summary);
      }
    } finally {
      setCheckingConfig(false);
    }
  };

  const handleCheckUpdate = async () => {
    setCheckingUpdate(true);
    try {
      const res = await checkForUpdates();
      if (res?.ok) {
        setUpdateInfo(res);
        notify(
          "Update Check",
          res.has_update ? `Update available: v${res.latest_version}` : "Plugin is up to date!",
        );
      }
    } finally {
      setCheckingUpdate(false);
    }
  };

  // Setup checks
  const isSlsInstalled = health?.sls?.status !== "no_local";
  const pluginsList = health?.plugins?.plugins ?? [];
  const missingPlugins = health?.plugins?.missing ?? [];
  const hasPlugins = pluginsList.length > 0 && missingPlugins.length === 0;
  const hasKey = Boolean(keyStatus?.masked);
  const setupIncomplete = !isSlsInstalled || !hasPlugins || !hasKey;

  const pluginsText = hasPlugins ? pluginsList.join(", ") : "None detected";

  return (
    <>
      {setupIncomplete && (
        <PanelSection title="Setup Notice">
          <PanelSectionRow>
            <div className="uran-alert-banner">
              <div style={{ fontWeight: 700, marginBottom: "4px" }}>Setup Incomplete</div>
              <div style={{ fontSize: "12px", lineHeight: 1.4 }}>
                {!isSlsInstalled && <div>• SLSsteam is not detected on this system.</div>}
                {!hasPlugins && (
                  <div>
                    • {pluginsList.length === 0
                      ? "No SLSsteam plugins found."
                      : `Missing SLSsteam plugins: ${missingPlugins.join(", ")}.`}{" "}
                    Install them with ASSella (Settings → AT0-M).
                  </div>
                )}
                {!hasKey && <div>• Hubcap API key is not configured.</div>}
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Environment & Status">
        <PanelSectionRow>
          <Field
            label="SLSsteam"
            description={
              health?.sls?.status === "no_local"
                ? "Not installed / not found"
                : health?.sls?.status === "outdated"
                ? "Outdated binary"
                : "Installed & active"
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field
            label="Active SLS Plugins"
            description={pluginsText}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Hubcap API Key">
        <PanelSectionRow>
          <Field
            label="API Key"
            description={
              keyStatus?.masked ? (
                <span>
                  {keyStatus.masked}{" "}
                  {stats.ok && (
                    <span style={{ opacity: 0.75 }}>
                      ({stats.requests_remaining ?? 0} requests left)
                    </span>
                  )}
                </span>
              ) : (
                "Not configured"
              )
            }
          />
        </PanelSectionRow>

        {stats.ok && (
          <PanelSectionRow>
            <Field
              label="Account Stats"
              description={`User: ${stats.username || "Anonymous"} · Daily usage: ${stats.daily_usage ?? 0}/${stats.daily_limit ?? 0} · Expiry: ${formatExpiry(stats.expires_at)}`}
            />
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => showQrKeyModal(() => loadHealthAndKey(true))}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
              <FaQrcode size={13} />
              <span>Scan QR Code with Phone</span>
            </div>
          </ButtonItem>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => setShowManualKeyInput((s) => !s)}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
              <FaKey size={12} />
              <span>{showManualKeyInput ? "Cancel Key Input" : "Enter Key Manually"}</span>
            </div>
          </ButtonItem>
        </PanelSectionRow>

        {showManualKeyInput && (
          <>
            <PanelSectionRow>
              <TextField
                label="Hubcap API Key"
                value={manualKey}
                onChange={(e) => setManualKey(e.target.value)}
                placeholder="Paste key here..."
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleSaveKey}
                disabled={savingKey || !manualKey.trim()}
              >
                {savingKey ? "Saving..." : "Save Key"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>

      <PanelSection title="DLC & Store Settings">
        <PanelSectionRow>
          <ToggleField
            label="Auto-add Delisted DLCs"
            description="Include delisted and bonus DLC manifests"
            checked={addDelistedDlcs}
            onChange={handleToggleAddDelisted}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Steam Store Button"
            description="Add an 'Add to Uran' button to the Steam Store page"
            checked={steamStoreEnabled}
            onChange={handleToggleSteamStore}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Notifications">
        <PanelSectionRow>
          <DropdownItem
            label="Notification Mode"
            rgOptions={NOTIFICATION_MODE_OPTIONS}
            selectedOption={notificationMode}
            onChange={handleNotificationModeChange}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection
        title={
          <div
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", cursor: "pointer", width: "100%" }}
            onClick={() => setShowAdvanced((a) => !a)}
          >
            <span>Advanced & Diagnostics</span>
            <span style={{ fontSize: "12px", opacity: 0.8 }}>{showAdvanced ? "Hide" : "Show"}</span>
          </div>
        }
      >
        {showAdvanced && (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Global SLS Online"
                description="Redirect all multiplayer to App ID 480 (Spacewar)"
                checked={globalSlsOnline}
                onChange={handleToggleGlobalSlsOnline}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <DropdownItem
                label="Gateway Route"
                rgOptions={[
                  { data: "auto", label: "Auto (Fastest)" },
                  { data: "direct", label: "Direct Connection" },
                  { data: "proxy", label: "Cloudflare Worker Proxy" },
                ]}
                selectedOption={gatewayMode}
                onChange={handleGatewayChange}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleTestRoutes}
                disabled={testingRoutes}
              >
                {testingRoutes ? "Testing Routes..." : "Test Gateway Latency"}
              </ButtonItem>
            </PanelSectionRow>

            {routeProbe?.routes && (
              <PanelSectionRow>
                <div style={{ fontSize: "12px", opacity: 0.8, padding: "2px 0" }}>
                  Direct: {routeProbe.routes.direct?.ms ? `${routeProbe.routes.direct.ms}ms` : "unreachable"} · Proxy: {routeProbe.routes.proxy?.ms ? `${routeProbe.routes.proxy.ms}ms` : "unreachable"}
                </div>
              </PanelSectionRow>
            )}

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleCheckConfig}
                disabled={checkingConfig}
              >
                {checkingConfig ? "Checking Config..." : "Verify SLSsteam Config"}
              </ButtonItem>
            </PanelSectionRow>

            {configCheck && (
              <PanelSectionRow>
                <div style={{ fontSize: "12px", opacity: 0.85, padding: "4px 0" }}>
                  <div style={{ fontWeight: 600 }}>{configCheck.summary}</div>
                  {configCheck.details?.map((d, i) => (
                    <div key={i} style={{ opacity: 0.7, fontSize: "11px" }}>• {d}</div>
                  ))}
                </div>
              </PanelSectionRow>
            )}

            <PanelSectionRow>
              <Field
                label="Plugin Version"
                description={`v${pluginInfo.version}`}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                onClick={handleCheckUpdate}
                disabled={checkingUpdate}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                  <FaSyncAlt size={12} />
                  <span>{checkingUpdate ? "Checking..." : "Check for Updates"}</span>
                </div>
              </ButtonItem>
            </PanelSectionRow>

            {updateInfo?.has_update && (
              <PanelSectionRow>
                <div style={{ color: "#7ee2a8", fontSize: "12px", padding: "4px 0" }}>
                  Update available: v{updateInfo.latest_version}
                </div>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>
    </>
  );
};
