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
  getPluginsStatus,
  installPlugin,
  setPluginEnabled,
  installEssentialPlugins,
  refreshPluginManifest,
  GATEWAY_LABELS,
  type HealthStatus,
  type ConfigCheck,
  type UpdateInfo,
  type GatewayMode,
  type RouteProbe,
  type PluginsStatus,
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
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [managedPlugins, setManagedPlugins] = useState<PluginsStatus | null>(null);
  const [setupChecksComplete, setSetupChecksComplete] = useState(false);
  const [pluginBusy, setPluginBusy] = useState(false);
  const [checkingPlugins, setCheckingPlugins] = useState(false);

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
  const [showWelcomeScreen, setShowWelcomeScreen] = useState(false);
  const [globalSlsOnline, setGlobalSlsOnlineState] = useState(false);
  const [gatewayMode, setGatewayMode] = useState<GatewayMode>("auto");
  const [routeProbe, setRouteProbe] = useState<RouteProbe | null>(null);
  const [testingRoutes, setTestingRoutes] = useState(false);
  const [checkingConfig, setCheckingConfig] = useState(false);
  const [configCheck, setConfigCheck] = useState<ConfigCheck | null>(null);
  const [pluginInfo, setPluginInfo] = useState<{ name: string; version: string }>({
    name: "Uran",
    version: "0.8.0",
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
        cached("health", getHealthStatus).catch(() => null),
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

  const loadPlugins = useCallback(async (refresh: false | "session" | "force" = false) => {
    const shouldRefresh = refresh !== false;
    if (shouldRefresh) setCheckingPlugins(true);
    try {
      let status: PluginsStatus;
      try {
        if (refresh === "force") {
          status = await refreshOnce("plugin_manifest_refresh", refreshPluginManifest);
        } else if (refresh === "session") {
          status = await once("plugin_manifest_refresh", refreshPluginManifest);
        } else {
          status = await getPluginsStatus();
          // Keep the session memo in sync with post-action disk state so
          // revisiting Settings doesn't revert to stale pre-action plugin status.
          if (status.ok) {
            void refreshOnce("plugin_manifest_refresh", () => Promise.resolve(status));
          }
        }
      } catch (error) {
        status = { ok: false, error: String(error), plugins: [] };
      }

      if (status.ok || !shouldRefresh) {
        setManagedPlugins(status);
        return status;
      }

      // A failed upstream request may still leave a previously verified local
      // manifest usable. Prefer it over an empty error state, but label it stale.
      try {
        const local = await getPluginsStatus();
        if (local.ok) {
          const reason = status.error || "The upstream manifest could not be refreshed.";
          const fallback = { ...local, error: `Upstream refresh failed; showing the ${local.source || "local"} manifest. ${reason}` };
          setManagedPlugins(fallback);
          return fallback;
        }
      } catch {
        // Keep the upstream error below if there is no usable local copy.
      }
      setManagedPlugins(status);
      return status;
    } finally {
      if (shouldRefresh) setCheckingPlugins(false);
    }
  }, []);
  const loadPluginsBackground = useCallback(() => {
    // Refresh upstream once per Decky session; explicit Check Again always
    // bypasses this memo. The backend falls back to verified local manifests.
    return loadPlugins("session");
  }, [loadPlugins]);
  const runPluginAction = async (action: () => Promise<unknown>) => {
    setPluginBusy(true);
    try {
      await action();
      await loadPlugins(false);
      await loadHealthAndKey(true);
    } catch (error) {
      notify("Plugin operation failed", String(error));
    } finally {
      setPluginBusy(false);
    }
  };

  useEffect(() => {
    let mounted = true;
    void Promise.all([loadHealthAndKey(), loadPluginsBackground()]).finally(() => {
      if (mounted) setSetupChecksComplete(true);
    });

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
  }, [loadHealthAndKey, loadPluginsBackground]);

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

  const handleCheckPluginUpdates = async () => {
    const status = await loadPlugins("force");
    if (!status?.ok) {
      notify("SLSsteam Plugins", status?.error || "Could not refresh the plugin manifest");
      return;
    }
    if (status.source !== "remote" || status.error) {
      notify(
        "SLSsteam Plugins",
        status.error || `Upstream unavailable; showing the verified ${status.source || "local"} manifest.`,
      );
      return;
    }
    const updates = status.plugins.filter((plugin) => plugin.status === "update_available").length;
    notify(
      "SLSsteam Plugins",
      updates ? `${updates} plugin update${updates === 1 ? "" : "s"} available.` : "All managed plugins are up to date.",
    );
  };

  // Plugin controls are only useful once the SLS binary/config/loader and at
  // least one plugin are present. Keep the setup action visible until then.
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
  const requiredPlugins = managedPlugins?.plugins.filter((plugin) => plugin.required) ?? [];
  const essentialsCurrent = requiredPlugins.length > 0 && requiredPlugins.every(
    (plugin) => plugin.deployable && plugin.installed && plugin.enabled && plugin.status === "installed",
  );
  const pluginControlsReady = slsReady && slsConfigReady && pluginsEnabled && hasPluginFiles && Boolean(managedPlugins?.ok);
  const hasKey = Boolean(keyStatus?.masked);
  const needsPluginSetupAction = !essentialsCurrent || !pluginsEnabled || !hasPluginFiles;
  const setupIncomplete = !slsReady || !slsConfigReady || needsPluginSetupAction || !hasKey;
  const displaySetupNotice = setupChecksComplete && (setupIncomplete || showWelcomeScreen);
  const essentialButtonDisabled = pluginBusy || checkingPlugins || !slsReady || !slsConfigReady
    || !managedPlugins?.ok || !requiredPlugins.length || !needsPluginSetupAction;

  const pluginsText = !slsConfigReady
    ? "Unknown (SLSsteam config unavailable)"
    : !hasPluginFiles
    ? "No Lua plugins detected"
    : pluginsList.join(", ");
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
  const manifestSource = managedPlugins?.source === "remote"
    ? "Upstream signed manifest"
    : managedPlugins?.source === "cache"
    ? "Verified cached manifest (may be stale)"
    : managedPlugins?.source === "bundled"
    ? "Bundled manifest (offline fallback)"
    : managedPlugins?.source || "Manifest source unavailable";

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
                {slsConfigReady && !pluginsEnabled && <div>• SLSsteam plugin loading is off. Install essentials to enable it.</div>}
                {slsConfigReady && pluginsEnabled && !hasPluginFiles && <div>• No SLSsteam Lua plugins are installed yet.</div>}
                {managedPlugins && !essentialsCurrent && <div>• Essential plugins are missing or need an update.</div>}
                {!setupIncomplete && <div>• All setup checks pass.</div>}
                {!managedPlugins && <div>• Checking the signed plugin manifest…</div>}
                {managedPlugins?.ok && managedPlugins.source !== "remote" && (
                  <div>• Using the verified {managedPlugins.source || "local"} manifest; it may be stale.</div>
                )}
                {managedPlugins?.error && <div>• {managedPlugins.error}</div>}
                {!hasKey && <div>• Hubcap API key is not configured.</div>}
              </div>
            </div>
          </PanelSectionRow>
          {setupIncomplete && needsPluginSetupAction && (
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={essentialButtonDisabled}
                onClick={() => void runPluginAction(installEssentialPlugins)}
              >
                {essentialsCurrent
                  ? "Enable SLSsteam plugin loader"
                  : "Install essential plugins"}
              </ButtonItem>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <PanelSection title="SLSsteam Plugins">
        <PanelSectionRow>
          <Field label="SLSsteam" description={slsText} />
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Active SLS Plugins" description={pluginsText} />
        </PanelSectionRow>

        {!pluginControlsReady && (
          <PanelSectionRow>
            <Field
              label="Plugin controls hidden until ready"
              description={
                !slsDetected ? "SLSsteam must be detected first."
                : slsRunningInactive ? "SLSsteam is installed, but not loaded into running Steam."
                : !slsConfigReady ? slsConfigError
                : !pluginsEnabled ? "Plugin loading is off; installing a plugin through Uran enables it automatically."
                : !hasPluginFiles ? "Install an essential plugin to make the plugin controls available."
                : checkingPlugins || !managedPlugins ? "Checking signed plugin manifest..."
                : !managedPlugins.ok ? "Could not load a verified plugin manifest. Check again to retry."
                : "Plugin controls are unavailable."
              }
            />
          </PanelSectionRow>
        )}

        {!pluginControlsReady && slsReady && slsConfigReady && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={checkingPlugins}
              onClick={() => void handleCheckPluginUpdates()}
            >
              {checkingPlugins ? "Checking plugin manifest..." : "Check again for plugin updates"}
            </ButtonItem>
          </PanelSectionRow>
        )}

        {pluginControlsReady && (
          <>
            <PanelSectionRow>
              <Field
                label="Plugin manifest"
                description={`${manifestSource}${managedPlugins?.serial ? ` · serial ${managedPlugins.serial}` : ""}`}
              />
            </PanelSectionRow>
            {managedPlugins?.error && (
              <PanelSectionRow>
                <Field label="Refresh notice" description={managedPlugins.error} />
              </PanelSectionRow>
            )}
            {(managedPlugins?.plugins ?? []).map((plugin) => (
              <React.Fragment key={plugin.filename}>
                <PanelSectionRow>
                  <Field
                    label={`${plugin.name} · v${plugin.version}${plugin.required ? " · Essential" : ""}`}
                    description={
                      plugin.disabled_reason
                        || (plugin.status === "off" ? "Disabled in Uran" : plugin.status.replaceAll("_", " "))
                    }
                  />
                </PanelSectionRow>
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    disabled={pluginBusy || checkingPlugins || !plugin.deployable}
                    onClick={() => void runPluginAction(() => installPlugin(plugin.filename))}
                  >
                    {plugin.status === "update_available" ? `Update ${plugin.name}` : plugin.status === "installed" ? `Reinstall ${plugin.name}` : `Install ${plugin.name}`}
                  </ButtonItem>
                </PanelSectionRow>
                {plugin.installed && !plugin.required && (
                  <PanelSectionRow>
                    <ButtonItem
                      layout="below"
                      disabled={pluginBusy || checkingPlugins}
                      onClick={() => void runPluginAction(() => setPluginEnabled(plugin.filename, !plugin.enabled))}
                    >
                      {plugin.enabled ? `Disable ${plugin.name}` : `Enable ${plugin.name}`}
                    </ButtonItem>
                  </PanelSectionRow>
                )}
              </React.Fragment>
            ))}
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={pluginBusy || checkingPlugins}
                onClick={() => void handleCheckPluginUpdates()}
              >
                {checkingPlugins ? "Checking for plugin updates..." : "Check again for plugin updates"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
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
