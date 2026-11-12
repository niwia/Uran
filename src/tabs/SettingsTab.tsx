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
  peekOnce,
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

export const SettingsTab: React.FC = () => {
  // General settings
  const [steamStoreEnabled, setSteamStoreEnabled] = useState(true);
  const [addDelistedDlcs, setAddDelistedDlcs] = useState(true);
  const [notificationMode, setNotificationModeState] = useState<"auto" | "steam" | "desktop" | "none">("auto");

  // Health & Environment
  const [health, setHealth] = useState<HealthStatus | null>(() => peekOnce<HealthStatus>("health") ?? null);
  const [setupChecksComplete, setSetupChecksComplete] = useState(() => peekOnce<HealthStatus>("health") !== undefined);
  const [refreshingStatus, setRefreshingStatus] = useState(false);

  // Hubcap Key & User stats
  type KeyStatusState = {
    ok: boolean;
    source: string;
    configured_path: string;
    masked: string;
    is_override: boolean;
    timestamp?: number;
  };
  type HubcapStatsState = {
    ok: boolean;
    username?: string;
    daily_usage?: number;
    daily_limit?: number;
    requests_remaining?: number | null;
    expires_at?: string;
    error?: string;
  };
  const [keyStatus, setKeyStatus] = useState<KeyStatusState | null>(
    () => peekOnce<KeyStatusState>("hubcap_key_status") ?? null,
  );
  const [stats, setStats] = useState<HubcapStatsState>(
    () => peekOnce<HubcapStatsState>("hubcap_stats") ?? { ok: false },
  );

  // Key manual input
  const [manualKey, setManualKey] = useState("");
  const [showManualKeyInput, setShowManualKeyInput] = useState(false);
  const [savingKey, setSavingKey] = useState(false);

  // Advanced & Diagnostics
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showWelcomeScreen, setShowWelcomeScreen] = useState(false);
  const [globalSlsOnline, setGlobalSlsOnlineState] = useState(false);
  const [gatewayMode, setGatewayMode] = useState<GatewayMode>("auto");
  const [routeProbe, setRouteProbe] = useState<RouteProbe | null>(null);
  const [testingRoutes, setTestingRoutes] = useState(false);
  const [checkingConfig, setCheckingConfig] = useState(false);
  const [configCheck, setConfigCheck] = useState<ConfigCheck | null>(null);
  const [pluginInfo, setPluginInfo] = useState<{ name: string; version: string }>({
    name: "Uran",
    version: "0.8.1",
  });
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);

  // Health (plugin presence, SLSsteam version) and Hubcap stats are cached for
  // the session: opening Settings must not re-run the checks every time.
  // `fresh` re-runs them (after saving a key, or from Refresh).
  const loadHealthAndKey = useCallback(async (fresh: boolean = false) => {
    try {
      const cached = fresh ? refreshOnce : once;
      const [h, k] = await Promise.all([
        cached("health", () => getHealthStatus(fresh)).catch(() => null),
        cached("hubcap_key_status", getHubcapKeyStatus).catch(() => null),
      ]);
      if (h) setHealth(h);
      if (k) setKeyStatus(k);
      void cached("hubcap_stats", getHubcapUserStats)
        .then(setStats)
        .catch(() => setStats({ ok: false }));
    } catch {
      // ignore
    }
  }, []);

  const handleRefreshStatus = async () => {
    setRefreshingStatus(true);
    try {
      await loadHealthAndKey(true);
    } finally {
      setRefreshingStatus(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    const hasCachedHealth = peekOnce<HealthStatus>("health") !== undefined;
    const hasCachedKey = peekOnce<KeyStatusState>("hubcap_key_status") !== undefined;
    const hasCachedStats = peekOnce<HubcapStatsState>("hubcap_stats") !== undefined;
    if (!hasCachedHealth || !hasCachedKey) {
      void loadHealthAndKey().finally(() => {
        if (mounted) setSetupChecksComplete(true);
      });
    } else if (!hasCachedStats) {
      void once("hubcap_stats", getHubcapUserStats)
        .then((s) => {
          if (mounted) setStats(s);
        })
        .catch(() => {
          if (mounted) setStats({ ok: false });
        });
    }

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

    return () => {
      mounted = false;
    };
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

  const slsBinaryMissing = health?.sls?.status === "no_local";
  const slsDetected = Boolean(health && (
    (!slsBinaryMissing && health.sls.status !== "error" && health.sls.status !== "checking")
    || health.sls.local_mtime != null
    || health.process?.sls_active
  ));
  const slsRunningInactive = Boolean(health?.process?.steam_running) && health?.process?.sls_active === false;
  const slsReady = slsDetected && !slsRunningInactive;
  const slsConfigReady = Boolean(health?.sls_config?.ok);
  const slsConfigError = health?.sls_config?.error || "SLSsteam config is unavailable";
  const pluginsList = health?.plugins?.plugins ?? [];
  const hasPluginFiles = pluginsList.length > 0;
  const pluginsEnabled = health?.plugins?.plugins_enabled === true;
  const hasKey = Boolean(keyStatus?.masked);
  const setupIncomplete = !slsReady || !slsConfigReady || !pluginsEnabled || !hasPluginFiles || !hasKey;
  const displaySetupNotice = setupChecksComplete && (setupIncomplete || showWelcomeScreen);

  const pluginsText = hasPluginFiles ? pluginsList.join(", ") : "No Lua plugins detected";
  const slsConfigText = !health
    ? "Checking SLSsteam config..."
    : !slsConfigReady
    ? slsConfigError
    : pluginsEnabled
    ? "Ready (Plugins: yes)"
    : "Plugins: no (disabled in config.yaml)";
  const slsText = !health
    ? "Checking SLSsteam..."
    : slsBinaryMissing
    ? "Not installed / not found"
    : slsRunningInactive
    ? "Installed, but not loaded into running Steam"
    : health.sls.status === "error"
    ? slsDetected ? "Installed; release check unavailable" : "Could not verify SLSsteam"
    : health?.sls?.status === "outdated"
    ? "Installed & active (outdated binary)"
    : health.process?.steam_running
    ? "Installed & active"
    : "Installed (Steam is not running)";

  return (
    <>
      {displaySetupNotice && (
        <PanelSection title="Welcome / Setup">
          <PanelSectionRow>
            <div className="uran-alert-banner">
              <div style={{ fontWeight: 700, marginBottom: "4px" }}>
                {setupIncomplete ? "Finish setting up Uran" : "Setup preview"}
              </div>
              <div style={{ fontSize: "12px", lineHeight: 1.4 }}>
                {!slsDetected && <div>• SLSsteam is not detected on this system.</div>}
                {slsRunningInactive && <div>• SLSsteam is installed but not loaded into running Steam.</div>}
                {!slsConfigReady && <div>• {slsConfigError}</div>}
                {slsConfigReady && !pluginsEnabled && (
                  <div>• Plugins: yes is disabled in SLSsteam config.yaml. Enable it via ASSella or manually.</div>
                )}
                {!hasPluginFiles && (
                  <div>• No SLSsteam Lua plugins found. Install plugins via ASSella or manually.</div>
                )}
                {!hasKey && <div>• Hubcap API key is not configured.</div>}
                {!setupIncomplete && <div>• All setup checks pass.</div>}
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="SLSsteam & Plugins">
        <PanelSectionRow>
          <Field label="SLSsteam" description={slsText} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="SLSsteam Config" description={slsConfigText} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Active SLS Plugins" description={pluginsText} />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={refreshingStatus}
            onClick={() => void handleRefreshStatus()}
          >
            {refreshingStatus ? "Checking status..." : "Refresh Status"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Hubcap Account & Network">
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
      </PanelSection>

      <PanelSection title="Preferences">
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
        <PanelSectionRow>
          <DropdownItem
            label="Notification Mode"
            rgOptions={NOTIFICATION_MODE_OPTIONS}
            selectedOption={notificationMode}
            onChange={handleNotificationModeChange}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Advanced & About">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => setShowAdvanced((current) => !current)}>
            {showAdvanced ? "Hide advanced settings" : "Show advanced settings"}
          </ButtonItem>
        </PanelSectionRow>
        {showAdvanced && (
          <>
            <PanelSectionRow>
              <ToggleField
                label="Show welcome screen"
                description="Preview the setup notice shown when requirements are incomplete"
                checked={showWelcomeScreen}
                onChange={setShowWelcomeScreen}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label="Global SLS Online"
                description={slsConfigReady ? "Redirect all multiplayer to App ID 480 (Spacewar)" : slsConfigError}
                checked={globalSlsOnline}
                disabled={!slsConfigReady}
                onChange={handleToggleGlobalSlsOnline}
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
