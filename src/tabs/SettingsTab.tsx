import React from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DropdownItem,
  ToggleField,
  Focusable,
} from "@decky/ui";
import QRCode from "qrcode";
import {
  NOTIFICATION_MODE_OPTIONS,
  notify,
  refreshNotificationChannel,
  setNotificationMode,
} from "../notify";
import {
  getSetting,
  setSetting,
  startKeyServer,
  keyServerStatus,
  stopKeyServer,
  getHubcapUserStats,
  checkConfigStatus,
  ConfigCheck,
  getStoreDebugStatus,
  isGlobalSlsOnlineEnabled,
  setGlobalSlsOnline,
  getHubcapRoutes,
  testHubcapRoutes,
  checkForUpdates,
  getPluginInfo,
  openExternalUrl,
  HUBCAP_HOST,
  GATEWAY_LABELS,
  GATEWAY_OPTIONS,
  routeLabel,
  routeTone,
  UpdateInfo,
  GatewayMode,
  RouteStatus,
  once,
  refreshOnce,
} from "../api";
import { setStorePatchEnabled } from "../StorePatch";
import { HealthStatusRow } from "../components/HealthStatus";
import { formatExpiry } from "../components/format";

export const SettingsTab: React.FC = () => {
  const [steamStoreEnabled, setSteamStoreEnabled] = React.useState(true);
  const [addDelistedDlcs, setAddDelistedDlcs] = React.useState(true);
  const [fetchDlcsOnInject, setFetchDlcsOnInject] = React.useState(true);
  const [storeStatus, setStoreStatus] = React.useState<{
    available: boolean;
    port?: number | null;
    store_tab: boolean;
    target_count: number;
    message: string;
    logs: string[];
  } | null>(null);
  const [globalSlsOnline, setGlobalSlsOnlineState] = React.useState(false);
  const [checkingUpdate, setCheckingUpdate] = React.useState(false);
  const [gatewayMode, setGatewayMode] = React.useState<GatewayMode>("auto");
  const [routeStatus, setRouteStatus] = React.useState<RouteStatus | null>(null);
  const [testingRoutes, setTestingRoutes] = React.useState(false);
  const [updateInfo, setUpdateInfo] = React.useState<UpdateInfo | null>(null);
  const [notificationMode, setNotificationModeState] = React.useState<
    "auto" | "steam" | "desktop" | "none"
  >("auto");
  const [msg, setMsg] = React.useState("");
  const [pluginInfo, setPluginInfo] = React.useState<{ name: string; version: string }>({
    name: "Uran",
    version: "",
  });
  const [stats, setStats] = React.useState<{
    ok: boolean;
    username?: string;
    daily_usage?: number;
    daily_limit?: number;
    requests_remaining?: number | null;
    expires_at?: string;
    error?: string;
  }>({ ok: false });

  // Version comes from the backend, which reads plugin.json — the single
  // source of truth. Never hardcode it here. The update check hits GitHub,
  // so it runs session-once, not on every tab visit.
  React.useEffect(() => {
    void getPluginInfo()
      .then((info) => info && setPluginInfo(info))
      .catch(() => {});
    void once("plugin-updates", checkForUpdates)
      .then((res) => res?.ok && setUpdateInfo(res))
      .catch(() => {});
  }, []);

  // -- QR key capture --
  const [keyServer, setKeyServer] = React.useState<{
    running: boolean;
    urls: string[];
    status: string;
    expires_in?: number;
  }>({ running: false, urls: [], status: "idle" });
  const [qrSvg, setQrSvg] = React.useState<string | null>(null);
  const [qrError, setQrError] = React.useState<string>("");
  const [checkingConfig, setCheckingConfig] = React.useState(false);
  const [configCheck, setConfigCheck] = React.useState<ConfigCheck | null>(null);

  const runConfigCheck = async () => {
    setCheckingConfig(true);
    try {
      const r = await checkConfigStatus(true);
      if (r) setConfigCheck(r);
    } catch {}
    setCheckingConfig(false);
  };

  const loadStats = React.useCallback(async () => {
    try {
      // Manual refresh points (e.g. after a key is accepted) bypass the
      // session memo and update it, so later tab visits see fresh stats.
      const s = await refreshOnce("hubcap-stats", getHubcapUserStats);
      if (s) setStats(s);
    } catch {
      setStats({ ok: false });
    }
  }, []);

  const loadStatsOnce = React.useCallback(async () => {
    try {
      const s = await once("hubcap-stats", getHubcapUserStats);
      if (s) setStats(s);
    } catch {
      setStats({ ok: false });
    }
  }, []);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [
          nm,
          storeEnabled,
          initialStoreStatus,
          gSls,
          gw,
          routes,
          delistedDlcs,
          dlcsOnInject,
        ] = await Promise.all([
          getSetting("notification_mode", "auto"),
          getSetting("steam_store_enabled", true),
          // CEF port scan + route state: session-once, not per tab visit.
          once("store-debug", () => getStoreDebugStatus(false)),
          isGlobalSlsOnlineEnabled(),
          getSetting("hubcap_gateway", "auto"),
          once("hubcap-routes", getHubcapRoutes),
          getSetting("add_delisted_dlcs", true),
          getSetting("fetch_dlcs_on_inject", true),
        ]);
        if (!alive) return;
        setSteamStoreEnabled(storeEnabled !== false);
        setStorePatchEnabled(storeEnabled !== false);
        setStoreStatus(initialStoreStatus);
        setGlobalSlsOnlineState(!!gSls?.enabled);
        setGatewayMode(
          gw === "direct" || gw === "proxy" ? (gw as GatewayMode) : "auto",
        );
        setRouteStatus(routes ?? null);
        setAddDelistedDlcs(delistedDlcs !== false);
        setFetchDlcsOnInject(dlcsOnInject !== false);
        if (nm) setNotificationModeState(nm);
      } catch {}
      loadStatsOnce();
    })();
    return () => {
      alive = false;
    };
  }, [loadStatsOnce]);

  const changeSteamStoreEnabled = async (enabled: boolean) => {
    setSteamStoreEnabled(enabled);
    setStorePatchEnabled(enabled);
    await setSetting("steam_store_enabled", enabled);
  };

  const stopQr = async () => {
    try {
      await stopKeyServer();
    } catch {}
    setKeyServer({ running: false, urls: [], status: "idle" });
    setQrSvg(null);
  };

  const startQr = async () => {
    setQrError("");
    setQrSvg(null);
    try {
      const r = await startKeyServer();
      if (!r?.ok) {
        setQrError(r?.error || "Could not start the local server");
        return;
      }
      const url = r.urls?.[0];
      if (!url) {
        setQrError(
          "No network address found. Connect the Deck to Wi-Fi, then try again.",
        );
        return;
      }
      const svg = await QRCode.toString(url, {
        type: "svg",
        errorCorrectionLevel: "M",
        margin: 1,
        width: 220,
        color: { dark: "#000000", light: "#ffffff" },
      });
      setQrSvg(svg);
      setKeyServer({
        running: true,
        urls: r.urls,
        status: r.status,
        expires_in: r.expires_in,
      });
    } catch (e: any) {
      setQrError(e?.message || "Failed to start");
    }
  };

  React.useEffect(() => {
    if (!keyServer.running) return;
    let alive = true;
    const t = setInterval(async () => {
      try {
        const s = await keyServerStatus();
        if (!alive || !s) return;
        setKeyServer((prev) => ({
          ...prev,
          running: s.running,
          status: s.status,
          expires_in: s.expires_in,
        }));
        if (!s.running || s.status === "accepted") {
          clearInterval(t);
          if (s.status === "accepted") {
            notify("Uran", "Hubcap key received");
            setMsg("Key received from your phone");
            setQrSvg(null);
            loadStats();
          }
        }
      } catch {}
    }, 1500);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [keyServer.running, loadStats]);

  const changeNotificationMode = async (opt: any) => {
    const val = opt.data;
    setNotificationModeState(val);
    await setSetting("notification_mode", val);
    await setNotificationMode(val);
    await refreshNotificationChannel();
  };

  return (
    <>
      <PanelSection title="Hubcap API">
        {stats.ok ? (
          <PanelSectionRow>
            <div
              style={{
                background: "rgba(255, 255, 255, 0.04)",
                border: "1px solid rgba(255, 255, 255, 0.1)",
                borderRadius: "8px",
                padding: "10px 14px",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                fontSize: "12px",
                width: "100%",
                boxSizing: "border-box",
                overflow: "hidden",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", minWidth: 0 }}>
                <span style={{ opacity: 0.65, flexShrink: 0 }}>user :</span>
                <span style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginLeft: "12px", textAlign: "right" }}>
                  {stats.username || "—"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", minWidth: 0 }}>
                <span style={{ opacity: 0.65, flexShrink: 0 }}>API :</span>
                <span style={{ fontWeight: 600, marginLeft: "12px", textAlign: "right" }}>
                  {stats.daily_usage ?? 0}/{stats.daily_limit ?? 0}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", minWidth: 0 }}>
                <span style={{ opacity: 0.65, flexShrink: 0 }}>expiry :</span>
                <span style={{ fontWeight: 600, marginLeft: "12px", textAlign: "right" }}>
                  {formatExpiry(stats.expires_at)}
                </span>
              </div>
            </div>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.7, padding: "4px 0" }}>
              {stats.error || "No API key configured."}
            </div>
          </PanelSectionRow>
        )}

        <PanelSectionRow>
          <ToggleField
            label="Show QR code"
            description="Scan with your phone to paste the key — no keyboard needed."
            checked={keyServer.running}
            onChange={(v) => (v ? startQr() : stopQr())}
          />
        </PanelSectionRow>

        {keyServer.running && (
          <>
            <PanelSectionRow>
              <div
                style={{
                  display: "flex",
                  justifyContent: "center",
                  padding: "8px 0",
                }}
              >
                {qrSvg ? (
                  <div
                    style={{
                      background: "#fff",
                      padding: "10px",
                      borderRadius: "10px",
                      lineHeight: 0,
                    }}
                    dangerouslySetInnerHTML={{ __html: qrSvg }}
                  />
                ) : (
                  <div style={{ opacity: 0.6, fontSize: "12px" }}>
                    Generating…
                  </div>
                )}
              </div>
            </PanelSectionRow>
            <PanelSectionRow>
              <div
                style={{
                  fontSize: "12px",
                  textAlign: "center",
                  color:
                    keyServer.status === "accepted" ? "#7ee2a8" : "#9aa4b2",
                }}
              >
                {keyServer.status === "accepted"
                  ? "Key received ✓ — you can close this"
                  : `Scan with your phone${
                      keyServer.expires_in
                        ? ` · closes in ${Math.max(0, keyServer.expires_in)}s`
                        : ""
                    }`}
              </div>
            </PanelSectionRow>
          </>
        )}
        {qrError && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#e57373" }}>{qrError}</div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="SLS Online (0: 480)">
        <PanelSectionRow>
          <ToggleField
            label="Global SLS Online"
            description="Map AppID 0 to 480 in SLS config so all games use Spacewar networking simultaneously. Locks individual game toggles ON."
            checked={globalSlsOnline}
            onChange={async (v) => {
              setGlobalSlsOnlineState(v);
              const res = await setGlobalSlsOnline(v);
              if (!res?.ok) {
                notify("Uran", "Failed to update Global SLS Online");
                setGlobalSlsOnlineState(!v);
              } else {
                notify("Uran", v ? "Global SLS Online enabled" : "Global SLS Online disabled");
              }
            }}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Hubcap Connection">
        <PanelSectionRow>
          <DropdownItem
            label="Route"
            description={
              GATEWAY_LABELS[gatewayMode] ??
              "Automatic (try direct, fall back to the edge proxy if blocked)"
            }
            rgOptions={GATEWAY_OPTIONS}
            selectedOption={gatewayMode}
            onChange={(opt: any) => {
              const next = opt?.data ?? opt;
              setGatewayMode(next);
              setSetting("hubcap_gateway", next);
              notify("Uran", `Hubcap route: ${GATEWAY_LABELS[next] ?? next}`);
            }}
          />
        </PanelSectionRow>

        <PanelSectionRow>
          <div
            style={{ fontSize: "12px", opacity: 0.85, lineHeight: 1.6, width: "100%" }}
          >
            <div style={{ marginBottom: "6px", fontWeight: 600 }}>Route status</div>
            {routeStatus ? (
              <>
                <div style={{ color: routeTone(routeStatus.direct) }}>
                  &bull; Direct ({HUBCAP_HOST}): {routeLabel(routeStatus.direct)}
                </div>
                <div style={{ color: routeTone(routeStatus.proxy) }}>
                  &bull; Edge proxy: {routeLabel(routeStatus.proxy)}
                </div>
                {routeStatus.fallback_used && (
                  <div style={{ color: "#f0c674", marginTop: "2px" }}>
                    The edge proxy is in use because the direct route is blocked.
                  </div>
                )}
                {routeStatus.last_error && (
                  <div
                    style={{
                      marginTop: "4px",
                      opacity: 0.7,
                      fontSize: "11px",
                      wordBreak: "break-word",
                    }}
                  >
                    Last detail: {routeStatus.last_error}
                  </div>
                )}
              </>
            ) : (
              <div style={{ opacity: 0.6 }}>Not checked yet.</div>
            )}
          </div>
        </PanelSectionRow>

        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={testingRoutes}
            onClick={async () => {
              setTestingRoutes(true);
              const r = await testHubcapRoutes();
              setTestingRoutes(false);
              if (!r) {
                notify("Uran", "Could not test the routes.");
                return;
              }
              const direct = r.routes?.direct?.ok;
              const proxy = r.routes?.proxy?.ok;
              setRouteStatus({
                direct: direct ? "ok" : "blocked",
                proxy: proxy ? "ok" : "failed",
                fallback_used: false,
                last_error: `direct: ${r.routes?.direct?.detail ?? "?"} · proxy: ${
                  r.routes?.proxy?.detail ?? "?"
                }`,
              });
              notify(
                "Uran",
                direct && proxy
                  ? "Both routes reachable."
                  : direct
                    ? "Direct works; the edge proxy is unreachable."
                    : proxy
                      ? "Direct is blocked; the edge proxy works."
                      : "Neither route is reachable.",
              );
            }}
          >
            {testingRoutes ? "Testing…" : "Test Connection"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="DLC Configuration">
        <PanelSectionRow>
          <ToggleField
            label="Add Delisted DLCs"
            description="Include delisted and historical DLCs in future game adds and DLC fetches. Turning this off does not remove DLCs already configured."
            checked={addDelistedDlcs}
            onChange={async (v) => {
              setAddDelistedDlcs(v);
              await setSetting("add_delisted_dlcs", v);
              notify("Uran", v ? "Add Delisted DLCs enabled" : "Add Delisted DLCs disabled");
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Fetch DLCs on Add"
            description="Automatically fetch and mount DLCs into SLS config when adding a game to Uran."
            checked={fetchDlcsOnInject}
            onChange={async (v) => {
              setFetchDlcsOnInject(v);
              await setSetting("fetch_dlcs_on_inject", v);
              notify("Uran", v ? "Auto-fetch DLCs enabled" : "Auto-fetch DLCs disabled");
            }}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Steam Store">
        <PanelSectionRow>
          <ToggleField
            label="Steam Store"
            checked={steamStoreEnabled}
            onChange={changeSteamStoreEnabled}
            description={
              storeStatus?.port
                ? `Port: ${storeStatus.port}`
                : storeStatus?.available
                ? "Port: 8080"
                : "CEF debugging unavailable"
            }
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Notifications">
        <PanelSectionRow>
          <DropdownItem
            label="Notification channel"
            rgOptions={NOTIFICATION_MODE_OPTIONS}
            selectedOption={notificationMode}
            onChange={changeNotificationMode}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="SLS Config">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={checkingConfig}
            onClick={runConfigCheck}
          >
            {checkingConfig ? "Checking…" : "Check Config"}
          </ButtonItem>
        </PanelSectionRow>
        {configCheck && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", lineHeight: 1.6, width: "100%" }}>
              <div
                style={{
                  color: !configCheck.ok
                    ? "#ff9a9a"
                    : configCheck.needs_attention
                      ? "#f0c674"
                      : "#7ee2a8",
                  fontWeight: 600,
                  marginBottom: "4px",
                }}
              >
                {configCheck.summary}
              </div>
              {configCheck.details.slice(0, 10).map((d) => (
                <div key={d} style={{ opacity: 0.8, fontSize: "11px" }}>
                  • {d}
                </div>
              ))}
              {configCheck.details.length > 10 && (
                <div style={{ opacity: 0.6, fontSize: "11px" }}>
                  …and {configCheck.details.length - 10} more
                </div>
              )}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection>
        <HealthStatusRow />
        <PanelSectionRow>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              width: "100%",
              fontSize: "12px",
              paddingTop: "6px",
              borderTop: "1px solid rgba(255, 255, 255, 0.08)",
            }}
          >
            <span style={{ opacity: 0.65 }}>
              Uran v{pluginInfo.version || "0.5.1"}
            </span>
            {updateInfo?.has_update && (
              <Focusable
                style={{
                  color: "#7ee2a8",
                  fontSize: "12px",
                  fontWeight: 600,
                  textDecoration: "underline",
                  cursor: "pointer",
                }}
                onClick={() => {
                  const url = updateInfo.release_url;
                  if (url) void openExternalUrl(url);
                }}
              >
                v{updateInfo.latest_version} update available
              </Focusable>
            )}
          </div>
        </PanelSectionRow>
      </PanelSection>

      {msg && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8, padding: "8px" }}>
            {msg}
          </div>
        </PanelSectionRow>
      )}
    </>
  );
};
