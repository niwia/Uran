import React from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  DialogButton,
  DropdownItem,
  ToggleField,
  Focusable,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import {
  NOTIFICATION_MODE_OPTIONS,
  injectFinishedText,
  notify,
  refreshNotificationChannel,
  setNotificationMode,
} from "./notify";
import QRCode from "qrcode";
import { initStorePatch, setStorePatchEnabled, tagInAssellaCollection, addedAppIds, pendingAppIds, syncAddedAppIds } from "./StorePatch";
import { initContextMenuPatch } from "./LibraryPatch";

const UranLogo: React.FC<{ size?: number | string; style?: React.CSSProperties }> = ({
  size = "1em",
  style,
}) => (
  <svg
    viewBox="0 0 245 231"
    width={size}
    height={size}
    style={{ display: "inline-block", verticalAlign: "middle", ...style }}
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      d="M36.487 78.134 C67.549 7.126 172.463 7.277 198.569 83.303 C199.061 84.365 199.834 85.072 200.889 85.413 C208.341 86.841 220.656 80.813 225.483 74.672 C227.405 75.872 226.643 89.66 226.655 92.238 C224.1 123.211 212.477 149.067 189.886 168.655 C179.025 177.792 167.202 185.109 154.419 190.606 C152.017 191.769 149.697 193.108 147.471 194.625 C145.209 196.811 141.132 199.06 140.159 202.333 C137.792 201.31 138.282 199.197 140.347 197.43 C142.163 195.876 144.002 194.334 145.842 192.792 C147.951 190.833 149.92 188.723 151.747 186.461 C152.978 184.843 154.477 183.605 156.247 182.758 C169.171 181.899 175.346 175.618 180.196 162.88 C183.829 153.832 180.103 145.402 172.323 141.055 C170.143 139.703 167.835 139.286 165.386 139.779 C161.391 141.712 158.215 144.682 155.848 148.688 C154.97 148.991 154.255 148.726 153.704 147.879 C150.037 141.75 145.42 135.318 144.108 128.014 C143.932 127.394 144.073 126.902 144.506 126.51 C147.225 128.077 154.993 130.844 156.645 126.788 C157.407 117.702 148.572 103.839 143.545 96.749 C139.093 89.116 113.351 67.886 106.063 71.121 C92.096 78.299 79.336 89.571 67.033 99.554 C65.873 99.845 64.924 99.479 64.186 98.455 C61.69 95.245 59.534 91.795 57.718 88.093 C56.441 85.375 55.222 82.621 54.05 79.84 C53.148 78.463 52.281 78.577 51.461 80.169 C41.033 94.032 33.674 111.876 36.944 130.036 C38.244 137.302 39.955 144.455 42.052 151.494 C43.177 155.032 44.021 158.646 44.595 162.324 C44.583 163.347 44.103 163.941 43.154 164.118 C42.638 162.779 41.947 161.566 41.08 160.453 C35.163 153.667 30.23 146.161 26.258 137.921 C18.231 121.278 16.462 102.284 19.813 84.011 C20.141 83.518 20.516 83.467 20.938 83.859 C22.906 87.511 25.344 90.759 28.249 93.615 C29.726 95.131 30.921 94.955 31.835 93.072 C33.311 88.067 34.858 83.088 36.487 78.134 Z M160.336 50.257 C160.922 49.941 161.32 49.473 161.508 48.854 C160.207 48.197 158.825 47.83 157.383 47.742 C154.126 47.489 153.247 48.892 154.735 51.925 C155.802 52.797 156.997 53.416 158.309 53.795 M167.999 63.601 C168.901 64.145 169.827 64.625 170.776 65.042 C171.28 66.862 172.182 68.404 173.494 69.655 C175.111 71.032 177.677 70.552 176.318 67.873 C174.01 65.345 173.846 63.058 172.405 60.164 C169.018 55.286 164.706 58.622 167.999 63.601 Z"
      fill="#ffffff"
    />
    <path
      d="M147.044 42.747 C148.29 40.5 153.105 41.13 157.8 44.156 C162.495 47.181 165.292 51.456 164.046 53.704 C162.801 55.952 157.986 55.321 153.291 52.296 C148.596 49.27 145.799 44.995 147.044 42.747 Z"
      fill="#040302"
    />
    <path
      d="M167.213 58.201 C169.114 56.719 173.166 59.263 176.263 63.884 C179.36 68.504 180.329 73.452 178.427 74.935 C176.525 76.417 172.473 73.873 169.376 69.252 C166.279 64.631 165.311 59.684 167.213 58.201 Z"
      fill="#040302"
    />
  </svg>
);
const AssellaLogo = UranLogo;

const TrashIcon: React.FC<{ size?: number | string; style?: React.CSSProperties }> = ({
  size = "1em",
  style,
}) => (
  <svg
    viewBox="0 0 24 24"
    width={size}
    height={size}
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    style={{ display: "inline-block", verticalAlign: "middle", ...style }}
  >
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </svg>
);

// -- Backend callables (modern @decky/api, positional args) -------------------
type SearchResult = { app_id: string; title: string };
type SearchResponse = { error?: string; results: SearchResult[] };
type InjectResult = {
  error?: string;
  name?: string;
  depots?: string[];
  fetching?: boolean;
};
type RecentInject = {
  app_id: string;
  name: string;
  done?: boolean;
  depots_resolved?: string[];
  depot_keys?: string[];
  injected_depots?: string[];
  injected_keys?: string[];
  registered?: boolean;
  blocked?: string;
  error?: string;
  manifests?: string[];
  manifest_error?: string;
  lua_keys?: string[];
  keys_missing?: string[];
  depots_registered?: string[];
  dlcs?: string[];
  dlc_depots?: string[];
  dlc_keys?: string[];
  dlc_error?: string;
};
type BackupEntry = { name: string; stamp: string; size: number; mtime: number };
type RestoreResult = { error?: string; success?: boolean; verified?: boolean };


const getRecentInjects = callable<[], RecentInject[]>("get_recent_injects");
const searchGames = callable<
  [query: string, limit: number, appid: boolean],
  SearchResponse
>("search_games");
const injectGame = callable<[app_id: string], InjectResult>("inject_game");
const getSetting = callable<[key: string, defaultValue: any], any>(
  "get_setting",
);
const setSetting = callable<[key: string, value: any], void>("set_setting");
const listBackups = callable<[], BackupEntry[]>("list_backups");
const createBackup = callable<[], string>("create_backup");
const restoreBackup = callable<[backup_name: string], RestoreResult>(
  "restore_backup",
);
const getHubcapKeyStatus = callable<[], {
  ok: boolean;
  source: string;
  configured_path: string;
  masked: string;
  is_override: boolean;
  base_url: string;
}>("get_hubcap_key_status");
const startKeyServer = callable<[], {
  ok: boolean;
  error?: string;
  running: boolean;
  port?: number | null;
  urls: string[];
  status: string;
  expires_in?: number;
}>("start_key_server");
const keyServerStatus = callable<[], {
  running: boolean;
  port?: number | null;
  urls: string[];
  status: string;
  expires_in?: number;
  keys_added?: number;
}>("key_server_status");
const stopKeyServer = callable<[], { ok: boolean }>("stop_key_server");
const validateHubcapKey = callable<[key: string], {
  ok: boolean;
  message: string;
  detail: string;
}>("validate_hubcap_key");
const saveHubcapKey = callable<[key: string], {
  ok: boolean;
  message: string;
}>("save_hubcap_key");
const getHubcapUserStats = callable<[], {
  ok: boolean;
  username?: string;
  daily_usage?: number;
  daily_limit?: number;
  requests_remaining?: number | null;
  expires_at?: string;
  error?: string;
}>("get_hubcap_user_stats");

// -- AT0M game management --
const listAtomGames = callable<[], {
  ok: boolean;
  games: AtomGame[];
}>("list_plugin_games");
const getAtomGame = callable<[app_id: string], AtomDetail & {
  ok: boolean;
  error?: string;
}>("get_atom_game");
const previewAtomUninstall = callable<
  [app_id: string],
  { ok: boolean; name?: string; targets: string[]; error?: string }
>("preview_atom_uninstall");
const uninstallAtomGame = callable<
  [app_id: string],
  {
    ok: boolean;
    removed?: string[];
    failed?: string[];
    config_cleaned?: boolean;
    registered?: boolean;
    error?: string;
  }
>("uninstall_atom_game");
const getStoreDebugStatus = callable<
  [refresh: boolean],
  {
    available: boolean;
    port?: number | null;
    store_tab: boolean;
    url?: string;
    target_count: number;
    checked_at: number;
    message: string;
    logs: string[];
  }
>("get_store_debug_status");
const setSlsonline = callable<
  [app_id: string, enabled: boolean, fake_appid: string],
  { ok: boolean; error?: string }
>("set_slsonline");
const setNetsock = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_netsock_toggle");
const setEos = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_eos_toggle");
const setEosNetsock = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_eos_netsock");
const toggleGameDlcs = callable<
  [app_id: string, enable: boolean],
  { ok: boolean; error?: string; count?: number }
>("toggle_game_dlcs");
const getInjectStatus = callable<
  [app_id: string],
  {
    done?: boolean;
    running?: boolean;
    error?: string;
    blocked?: string;
    registered?: boolean;
    keys_missing?: string[];
    depot_keys?: string[];
    injected_depots?: string[];
    injected_keys?: string[];
    manifests?: string[];
    manifest_error?: string;
  } | null
>("get_inject_status");

// -- Search Tab ---------------------------------------------------------------
const SearchTab: React.FC = () => {
  const [query, setQuery] = React.useState("");
  const [searchByAppId, setSearchByAppId] = React.useState(false);
  const [results, setResults] = React.useState<SearchResult[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [recent, setRecent] = React.useState<RecentInject[]>([]);
  const [, bumpVersion] = React.useReducer((n: number) => n + 1, 0);

  const loadRecent = async () => {
    try {
      const r = await getRecentInjects();
      setRecent(r ?? []);
    } catch {}
  };

  React.useEffect(() => {
    loadRecent();
    const t = setInterval(loadRecent, 5000);
    return () => clearInterval(t);
  }, []);

  const doSearch = async () => {
    const q = query.trim();
    const minLen = searchByAppId ? 1 : 3;
    if (q.length < minLen) {
      setMsg(searchByAppId ? "Enter an App ID" : "Enter at least 3 characters");
      return;
    }
    setSearching(true);
    setMsg("");
    try {
      const r = await searchGames(q, 20, searchByAppId);
      if (r?.error) {
        setMsg(r.error);
        setResults([]);
      } else {
        const res = r?.results ?? [];
        setResults(res);
        setMsg(
          res.length === 0
            ? "No results found"
            : `${res.length} result${res.length !== 1 ? "s" : ""}`,
        );
      }
    } catch (e: any) {
      setMsg(`Search error: ${e}`);
      setResults([]);
    }
    setSearching(false);
  };

  const doInject = async (appId: string, title: string) => {
    if (addedAppIds.has(appId)) {
      const msg = `${title} is already registered in your library.`;
      notify("Uran", msg);
      setMsg(msg);
      return;
    }
    pendingAppIds.add(appId);
    bumpVersion();
    setMsg(`Adding ${title} to SLS...`);
    try {
      const r = await injectGame(appId);
      if ((r as any)?.already_added) {
        pendingAppIds.delete(appId);
        addedAppIds.add(appId);
        bumpVersion();
        const err = (r as any).error || `${title} is already registered in your library.`;
        notify("Uran", err);
        setMsg(err);
        return;
      }
      if (r && !r.error) {
        const name = r.name ?? title;
        const depots = r.depots?.length ?? 0;
        const toastMsg = `Added ${name} to SLS`;
        notify("Uran", toastMsg);
        setMsg(toastMsg);

        const startedAt = Date.now();
        const MAX_WAIT_MS = 300000;
        const timer = setInterval(async () => {
          try {
            const job = await getInjectStatus(appId);
            if (job?.done) {
              clearInterval(timer);
              pendingAppIds.delete(appId);
              addedAppIds.add(appId);
              bumpVersion();
              notify("Uran", injectFinishedText(name, job));
            } else if (Date.now() - startedAt > MAX_WAIT_MS) {
              clearInterval(timer);
              pendingAppIds.delete(appId);
              addedAppIds.add(appId);
              bumpVersion();
              notify("Uran", `Background work for ${name} timed out`);
            }
          } catch {
            // keep polling
          }
        }, 2000);
      } else {
        pendingAppIds.delete(appId);
        bumpVersion();
        const err = r?.error || "Unknown error";
        notify("Uran", err);
        setMsg(err);
      }
    } catch (e: any) {
      pendingAppIds.delete(appId);
      bumpVersion();
      notify("Uran", `Error: ${e}`);
      setMsg(`Error: ${e}`);
    }
  };

  return (
    <>
      <PanelSection title="Search Games">
        <PanelSectionRow>
          <TextField
            label={searchByAppId ? "App ID (numeric)" : "Game Name"}
            value={query}
            onChange={(e: any) => setQuery(e.target.value)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Search by App ID"
            description="Match exact game_id instead of name"
            checked={searchByAppId}
            onChange={setSearchByAppId}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={
              searching || query.trim().length < (searchByAppId ? 1 : 3)
            }
            onClick={doSearch}
          >
            {searching ? "Searching..." : "Search"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {msg && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8, padding: "8px" }}>
            {msg}
          </div>
        </PanelSectionRow>
      )}

      {results.length > 0 && (
        <PanelSection title={`Results (${results.length})`}>
          {results.map((item) => {
            const isAdded = addedAppIds.has(item.app_id);
            const isPending = pendingAppIds.has(item.app_id);
            return (
              <PanelSectionRow key={item.app_id}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width: "100%",
                    gap: "8px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      overflow: "hidden",
                      flex: 1,
                    }}
                  >
                    <span
                      style={{
                        fontSize: "13px",
                        fontWeight: 600,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {item.title}
                    </span>
                    <span style={{ fontSize: "11px", opacity: 0.6 }}>
                      App ID: {item.app_id}
                    </span>
                  </div>
                  <div style={{ flexShrink: 0 }}>
                    <DialogButton
                      style={{
                        height: "28px",
                        minWidth: "70px",
                        padding: "0 10px",
                        fontSize: "12px",
                      }}
                      disabled={isAdded || isPending}
                      onClick={() => doInject(item.app_id, item.title)}
                    >
                      {isAdded ? "Added" : isPending ? "Adding..." : "Add"}
                    </DialogButton>
                  </div>
                </div>
              </PanelSectionRow>
            );
          })}
        </PanelSection>
      )}

      {recent.length > 0 && (
        <PanelSection title="Recent Activity">
          {recent.slice(0, 5).map((r) => (
            <PanelSectionRow key={r.app_id}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  width: "100%",
                  fontSize: "12px",
                }}
              >
                <span
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: "70%",
                  }}
                >
                  {r.name || r.app_id}
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    color: r.error
                      ? "#e57373"
                      : r.done
                      ? "#81c784"
                      : "#ffb74d",
                  }}
                >
                  {r.error ? "Failed" : r.done ? "Done" : "Working..."}
                </span>
              </div>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
    </>
  );
};

// -- AT0M Games Tab -----------------------------------------------------------
type AtomGame = {
  app_id: string;
  name: string;
  installed: boolean;
  downloading?: boolean;
  install_path: string;
  size_on_disk: number;
  buildid: string;
  depots: string[];
  key_count: number;
  dlc_only: boolean;
};

type AtomDepotInfo = {
  id: string;
  name: string;
  in_config: boolean;
  has_key: boolean;
  is_dlc: boolean;
  is_shared: boolean;
  os: string;
};

type AtomDlcInfo = {
  id: string;
  name: string;
  in_config: boolean;
};

type AtomDetail = AtomGame & {
  slsonline: boolean;
  fake_appid: string;
  netsock: boolean;
  eos: string;
  eos_available: boolean;
  registered: boolean;
  depots_detail?: AtomDepotInfo[];
  dlcs_detail?: AtomDlcInfo[];
  dlcs_injected?: boolean;
};

const formatBytes = (n: number): string => {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
};

const AtomGamesTab: React.FC = () => {
  const [games, setGames] = React.useState<AtomGame[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [detail, setDetail] = React.useState<AtomDetail | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const r = await listAtomGames();
      setGames(r?.games ?? []);
      syncAddedAppIds().catch(() => {});
    } catch {
      setGames([]);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  const openGame = async (appId: string) => {
    setMsg("");
    try {
      const d = await getAtomGame(appId);
      if (d?.ok) setDetail(d as AtomDetail);
      else setMsg(d?.error || "Could not open game");
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    }
  };

  const refreshDetail = async () => {
    if (detail) await openGame(detail.app_id);
  };

  const toggle = async (
    label: string,
    fn: () => Promise<{ ok?: boolean; error?: string }>,
  ) => {
    setBusy(true);
    setMsg("");
    try {
      const r = await fn();
      if (!r?.ok) setMsg(r?.error || `${label} failed`);
      else setMsg(`${label} updated`);
      await refreshDetail();
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const askUninstall = async (g: AtomGame) => {
    setBusy(true);
    try {
      const p = await previewAtomUninstall(g.app_id);
      if (p?.ok) {
        const targets = p.targets || [];
        let modal: ReturnType<typeof showModal>;
        modal = showModal(
          <ConfirmModal
            strTitle={`Uninstall ${g.name}?`}
            strOKButtonText="Uninstall"
            strCancelButtonText="Cancel"
            bDestructiveWarning
            bDisableBackgroundDismiss
            onCancel={() => modal.Close()}
            onOK={() => {
              modal.Close();
              void doUninstall(g);
            }}
          >
            <div style={{ maxHeight: "45vh", overflowY: "auto", fontSize: "12px" }}>
              <p>This permanently deletes these files and folders:</p>
              {targets.length ? (
                <ul style={{ margin: "6px 0", paddingLeft: "18px" }}>
                  {targets.map((target) => (
                    <li key={target} style={{ fontSize: "11px", wordBreak: "break-all" }}>
                      {target}
                    </li>
                  ))}
                </ul>
              ) : (
                <p>No game files were found. Uran will only remove its library and config entries.</p>
              )}
              <p>It will also remove this game from SLSsteam&apos;s config.</p>
              <p style={{ color: "#e57373" }}>This cannot be undone.</p>
            </div>
          </ConfirmModal>,
          undefined,
          { strTitle: `Uninstall ${g.name}?`, bNeverPopOut: true },
        );
      }
      else setMsg(p?.error || "Could not prepare uninstall");
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const doUninstall = async (game: AtomGame) => {
    setBusy(true);
    setMsg("");
    try {
      const r = await uninstallAtomGame(game.app_id);
      if (r?.ok) {
        addedAppIds.delete(game.app_id);
        notify("Uran", `Uninstalled ${game.name}`);
        setMsg(`Uninstalled ${game.name}`);
        setDetail(null);
        await load();
      } else {
        const issues = [...(r?.failed || [])];
        if (r?.config_cleaned === false) issues.push("SLSsteam config cleanup failed");
        if (r?.registered) issues.push("game is still registered in Uran");
        setMsg(`Uninstall incomplete: ${issues.join("; ") || r?.error || "unknown error"}`);
        await load();
      }
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  // ---- Detail page ----
  if (detail) {
    const notInstalled = !detail.installed;
    return (
      <>
        <PanelSection>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={() => {
                setDetail(null);
                setMsg("");
              }}
            >
              ← Back to games
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title={detail.name}>
          <PanelSectionRow>
            <div style={{ fontSize: "13px", lineHeight: 1.8 }}>
              <div>
                AppID <b>{detail.app_id}</b>
              </div>
              {detail.installed && detail.size_on_disk > 0 && (
                <div>Size: {formatBytes(detail.size_on_disk)}</div>
              )}
              {detail.buildid && <div>Build: {detail.buildid}</div>}
              <div>
                Depots: {detail.depots?.length ?? 0} · Keys:{" "}
                {detail.key_count ?? 0}
              </div>
              <div
                style={{
                  color: detail.installed ? "#7ee2a8" : "#9aa4b2",
                }}
              >
                {detail.installed
                  ? "Installed"
                  : detail.downloading
                  ? "Downloading"
                  : "Not installed"}
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title="Integrations">
          <PanelSectionRow>
            <ToggleField
              label="SLSonline"
              description="Map this game to Spacewar (480) for online features."
              checked={detail.slsonline}
              disabled={busy}
              onChange={(v) =>
                toggle("SLSonline", () =>
                  setSlsonline(detail.app_id, v, detail.fake_appid || "480"),
                )
              }
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label="NetSock"
              description="Steam Networking Sockets multiplayer patch."
              checked={detail.netsock}
              disabled={busy || notInstalled || !detail.slsonline}
              onChange={(v) =>
                toggle("NetSock", () => setNetsock(detail.app_id, v))
              }
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label="EOS Proxy"
              description="Apply the Epic Online Services proxy."
              checked={detail.eos === "active"}
              disabled={
                busy || notInstalled || !detail.slsonline || !detail.eos_available
              }
              onChange={(v) => toggle("EOS Proxy", () => setEos(detail.app_id, v))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label="EOS + NetSock"
              description="Enable the EOS proxy and NetSock together."
              checked={detail.eos === "active" && detail.netsock}
              disabled={
                busy || notInstalled || !detail.slsonline || !detail.eos_available
              }
              onChange={(v) =>
                toggle("EOS + NetSock", () =>
                  setEosNetsock(detail.app_id, v),
                )
              }
            />
          </PanelSectionRow>
        </PanelSection>

        <PanelSection title="DLC & Depots">
          <PanelSectionRow>
            <ToggleField
              label="Inject DLCs"
              description="Register all DLC AppIDs into AdditionalApps and sync keyed depots."
              checked={!!detail.dlcs_injected}
              disabled={busy}
              onChange={(v) =>
                toggle("Inject DLCs", () => toggleGameDlcs(detail.app_id, v))
              }
            />
          </PanelSectionRow>

          {detail.dlcs_detail && detail.dlcs_detail.length > 0 && (
            <PanelSectionRow>
              <div style={{ width: "100%", fontSize: "12px" }}>
                <div style={{ fontWeight: "bold", opacity: 0.85, marginBottom: "6px" }}>
                  DLC AppIDs ({detail.dlcs_detail.length})
                </div>
                {detail.dlcs_detail.map((dlc) => (
                  <div
                    key={dlc.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "4px 0",
                      borderBottom: "1px solid rgba(255,255,255,0.05)",
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0, paddingRight: "8px" }}>
                      <span style={{ fontFamily: "monospace", opacity: 0.75 }}>{dlc.id}</span>{" "}
                      <span>{dlc.name}</span>
                    </div>
                    <span
                      style={{
                        fontSize: "10px",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        background: dlc.in_config ? "rgba(126, 226, 168, 0.2)" : "rgba(255, 255, 255, 0.08)",
                        color: dlc.in_config ? "#7ee2a8" : "#8a929e",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {dlc.in_config ? "Active in config" : "Not in config"}
                    </span>
                  </div>
                ))}
              </div>
            </PanelSectionRow>
          )}

          {detail.depots_detail && detail.depots_detail.length > 0 && (
            <PanelSectionRow>
              <div style={{ width: "100%", fontSize: "12px" }}>
                <div style={{ fontWeight: "bold", opacity: 0.85, marginBottom: "6px" }}>
                  Depots ({detail.depots_detail.length})
                </div>
                {detail.depots_detail.map((d) => (
                  <div
                    key={d.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      padding: "5px 0",
                      borderBottom: "1px solid rgba(255,255,255,0.05)",
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0, paddingRight: "8px" }}>
                      <div>
                        <b style={{ fontFamily: "monospace" }}>{d.id}</b>{" "}
                        <span style={{ opacity: 0.9 }}>{d.name}</span>
                      </div>
                      <div style={{ fontSize: "10px", opacity: 0.65, marginTop: "2px" }}>
                        {d.os ? `[${d.os}] ` : ""}
                        {d.is_dlc ? "[DLC] " : ""}
                        {d.is_shared ? "[Shared] " : ""}
                        {d.has_key ? "Key present" : "No key"}
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: "10px",
                        padding: "2px 6px",
                        borderRadius: "4px",
                        background: d.in_config ? "rgba(126, 226, 168, 0.2)" : "rgba(255, 255, 255, 0.08)",
                        color: d.in_config ? "#7ee2a8" : "#8a929e",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {d.in_config ? "Added in config" : "Not in config"}
                    </span>
                  </div>
                ))}
              </div>
            </PanelSectionRow>
          )}
        </PanelSection>

        <PanelSection>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy}
              onClick={() => askUninstall(detail)}
            >
              Uninstall
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>

        {msg && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.85, padding: "8px" }}>
              {msg}
            </div>
          </PanelSectionRow>
        )}
      </>
    );
  }

  // ---- List page ----
  return (
    <>
      <style>{`
        .uran-game-row {
          display: flex !important;
          align-items: center !important;
          gap: 6px !important;
          width: 100% !important;
          margin-bottom: 8px !important;
        }
        .uran-game-pill {
          min-width: 0 !important;
          flex: 1 1 0% !important;
          height: 38px !important;
          min-height: 38px !important;
          padding: 0 12px !important;
          display: flex !important;
          align-items: center !important;
          justify-content: flex-start !important;
          overflow: hidden !important;
          border-radius: 8px !important;
        }
        .uran-game-pill > div,
        .uran-game-pill > span {
          width: 100% !important;
          min-width: 0 !important;
          overflow: hidden !important;
          text-overflow: ellipsis !important;
          white-space: nowrap !important;
          text-align: left !important;
        }
        .uran-uninstall-btn {
          width: 38px !important;
          min-width: 38px !important;
          max-width: 38px !important;
          height: 38px !important;
          min-height: 38px !important;
          padding: 0 !important;
          flex-shrink: 0 !important;
          display: flex !important;
          align-items: center !important;
          justify-content: center !important;
          border-radius: 8px !important;
        }
        .uran-uninstall-btn:hover,
        .uran-uninstall-btn:focus,
        .uran-uninstall-btn:focus-within {
          color: #ff6b6b !important;
        }
      `}</style>

      <PanelSection title={`AT0-M Games (${games.length})`}>
        {loading ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.7 }}>Loading…</div>
          </PanelSectionRow>
        ) : games.length === 0 ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", opacity: 0.7 }}>
              No AT0-M games registered yet.
            </div>
          </PanelSectionRow>
        ) : (
          games.map((g) => (
            <PanelSectionRow key={g.app_id} style={{ marginBottom: "6px" }}>
              <Focusable
                flow-children="horizontal"
                className="uran-game-row"
              >
                <DialogButton
                  className="uran-game-pill"
                  onClick={() => openGame(g.app_id)}
                >
                  <span
                    style={{
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      display: "block",
                      width: "100%",
                      fontSize: "13px",
                    }}
                  >
                    {g.name}
                  </span>
                </DialogButton>
                <DialogButton
                  className="uran-uninstall-btn"
                  disabled={busy}
                  onClick={() => askUninstall(g)}
                >
                  <TrashIcon size={16} />
                </DialogButton>
              </Focusable>
            </PanelSectionRow>
          ))
        )}
      </PanelSection>

      {msg && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.85, padding: "8px" }}>
            {msg}
          </div>
        </PanelSectionRow>
      )}

    </>
  );
};

function formatExpiry(raw?: string): string {
  if (!raw) return "—";
  try {
    const datePart = raw.split(" ")[0].split("T")[0];
    const parts = datePart.split("-");
    if (parts.length === 3) {
      const yy = parts[0].length === 4 ? parts[0].slice(2) : parts[0];
      return `${parts[2]}/${parts[1]}/${yy}`;
    }
  } catch {}
  return raw;
}

// -- Settings Tab -------------------------------------------------------------
const SettingsTab: React.FC = () => {
  const [showRestartButton, setShowRestartButton] = React.useState(false);
  const [steamStoreEnabled, setSteamStoreEnabled] = React.useState(true);
  const [storeStatus, setStoreStatus] = React.useState<{
    available: boolean;
    port?: number | null;
    store_tab: boolean;
    target_count: number;
    message: string;
    logs: string[];
  } | null>(null);
  const [manifestIdPinning, setManifestIdPinning] = React.useState(false);
  const [notificationMode, setNotificationModeState] = React.useState<
    "auto" | "steam" | "desktop" | "none"
  >("auto");
  const [msg, setMsg] = React.useState("");
  const [stats, setStats] = React.useState<{
    ok: boolean;
    username?: string;
    daily_usage?: number;
    daily_limit?: number;
    requests_remaining?: number | null;
    expires_at?: string;
    error?: string;
  }>({ ok: false });

  // -- QR key capture --
  const [keyServer, setKeyServer] = React.useState<{
    running: boolean;
    urls: string[];
    status: string;
    expires_in?: number;
  }>({ running: false, urls: [], status: "idle" });
  const [qrSvg, setQrSvg] = React.useState<string | null>(null);
  const [qrError, setQrError] = React.useState<string>("");

  const loadStats = React.useCallback(async () => {
    try {
      const s = await getHubcapUserStats();
      if (s) setStats(s);
    } catch {
      setStats({ ok: false });
    }
  }, []);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [srb, mip, nm, storeEnabled, initialStoreStatus] = await Promise.all([
          getSetting("show_restart_button", false),
          getSetting("manifestid_pinning", false),
          getSetting("notification_mode", "auto"),
          getSetting("steam_store_enabled", true),
          getStoreDebugStatus(false),
        ]);
        if (!alive) return;
        setShowRestartButton(!!srb);
        setManifestIdPinning(!!mip);
        setSteamStoreEnabled(storeEnabled !== false);
        setStorePatchEnabled(storeEnabled !== false);
        setStoreStatus(initialStoreStatus);
        if (nm) setNotificationModeState(nm);
      } catch {}
      loadStats();
    })();
    return () => {
      alive = false;
    };
  }, [loadStats]);

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
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ opacity: 0.65 }}>user :</span>
                <span style={{ fontWeight: 600 }}>{stats.username || "—"}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ opacity: 0.65 }}>API :</span>
                <span style={{ fontWeight: 600 }}>
                  {stats.daily_usage ?? 0}/{stats.daily_limit ?? 0}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ opacity: 0.65 }}>expiry :</span>
                <span style={{ fontWeight: 600 }}>{formatExpiry(stats.expires_at)}</span>
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

      <PanelSection title="Injection">
        <PanelSectionRow>
          <ToggleField
            label="Pin ManifestIds"
            description="Write ManifestIds pins for fetched depots."
            checked={manifestIdPinning}
            onChange={(v) => {
              setManifestIdPinning(v);
              setSetting("manifestid_pinning", v);
            }}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Show Exit Steam button"
            description="Show a manual Exit Steam button on store pages."
            checked={showRestartButton}
            onChange={(v) => {
              setShowRestartButton(v);
              setSetting("show_restart_button", v);
            }}
          />
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

// -- Backups Tab --------------------------------------------------------------
const BackupsTab: React.FC = () => {
  const [backups, setBackups] = React.useState<BackupEntry[]>([]);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const load = async () => {
    setBusy(true);
    try {
      const r = await listBackups();
      setBackups(r ?? []);
    } catch {}
    setBusy(false);
  };

  const create = async () => {
    setBusy(true);
    try {
      const r = await createBackup();
      setMsg(`Created backup: ${r}`);
      load();
    } catch {
      setMsg("Backup creation failed");
    }
    setBusy(false);
  };

  const restore = async (name: string) => {
    setBusy(true);
    try {
      const r = await restoreBackup(name);
      if (r?.error) {
        setMsg(`Error: ${r.error}`);
        notify("Uran", `Restore failed: ${r.error}`);
      } else {
        const text = r?.verified
          ? `Restored config from ${name}`
          : `Restored (unverified): ${name}`;
        setMsg(text);
        notify("Uran", text);
        await load();
      }
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    }
    setBusy(false);
  };

  React.useEffect(() => {
    load();
  }, []);

  return (
    <>
      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy} onClick={create}>
          Create Backup Now
        </ButtonItem>
      </PanelSectionRow>
      <PanelSection title={`Backups (${backups.length})`}>
        {backups.length === 0 && (
          <PanelSectionRow>
            <div style={{ opacity: 0.6, padding: "8px" }}>None</div>
          </PanelSectionRow>
        )}
        {backups.map((b: BackupEntry) => {
          const isPreRestore = b.stamp.startsWith("pre_restore.");
          const rawTs = isPreRestore
            ? b.stamp.slice("pre_restore.".length)
            : b.stamp.replace("sls.", "");
          const dateMatch = rawTs.match(
            /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/,
          );
          const displayTs = dateMatch
            ? `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]} ${dateMatch[4]}:${dateMatch[5]}`
            : rawTs;
          const label = isPreRestore ? `Pre-restore · ${displayTs}` : displayTs;

          return (
            <PanelSectionRow key={b.name}>
              <ButtonItem onClick={() => restore(b.name)} layout="below">
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    width: "100%",
                  }}
                >
                  <span style={{ fontSize: "13px" }}>{label}</span>
                  <span
                    style={{
                      fontSize: "11px",
                      color: "#888",
                      marginLeft: "8px",
                    }}
                  >
                    {Math.round(b.size / 1024)} KB
                  </span>
                </div>
              </ButtonItem>
            </PanelSectionRow>
          );
        })}
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

// -- Depot Keys Tab ------------------------------------------------------------

// -- Plugin Entry -------------------------------------------------------------
let lastActiveTab = "search";

export default definePlugin(() => {
  const storePatchCleanup = initStorePatch();
  const contextMenuCleanup = initContextMenuPatch();

  getSetting("notification_mode", "auto")
    .then((v) => {
      setNotificationMode(v);
      return refreshNotificationChannel();
    })
    .catch(() => {});

  const Content = () => {
    const [activeTab, setActiveTab] = React.useState(lastActiveTab);

    const selectTab = (tab: string) => {
      lastActiveTab = tab;
      setActiveTab(tab);
    };

    const tabStyle = (active: boolean): any => ({
      flex: 1,
      textAlign: "center" as const,
      padding: "8px 4px",
      cursor: "pointer",
      fontSize: "13px",
      fontWeight: active ? 700 : 400,
      color: active ? "#fff" : "#999",
      background: active ? "rgba(255,255,255,0.08)" : "transparent",
      borderRadius: "6px",
      border: active
        ? "1px solid rgba(255,255,255,0.15)"
        : "1px solid transparent",
      transition: "background 0.15s, border-color 0.15s, color 0.15s",
      userSelect: "none" as const,
      WebkitUserSelect: "none" as const,
      outline: "none" as const,
    });

    const focusClass = "assella-tab-focus";
    const activeFocusClass = "assella-tab-active-focus";

    return (
      <>
        <style>{`
          .${focusClass}{background:rgba(255,255,255,0.12) !important;color:#ddd !important;border-color:rgba(255,255,255,0.25) !important}
          .${activeFocusClass}{background:rgba(255,255,255,0.18) !important;color:#fff !important;border-color:rgba(255,255,255,0.35) !important}
        `}</style>
        <Focusable
          flow-children="horizontal"
          style={{ display: "flex", gap: "4px", padding: "0 0 12px 0" }}
        >
          <Focusable
            focusClassName={
              activeTab === "search" ? activeFocusClass : focusClass
            }
            onActivate={() => selectTab("search")}
            style={tabStyle(activeTab === "search")}
          >
            Search
          </Focusable>
          <Focusable
            focusClassName={
              activeTab === "atom" ? activeFocusClass : focusClass
            }
            onActivate={() => selectTab("atom")}
            style={tabStyle(activeTab === "atom")}
          >
            AT0-M
          </Focusable>
          <Focusable
            focusClassName={
              activeTab === "settings" ? activeFocusClass : focusClass
            }
            onActivate={() => selectTab("settings")}
            style={tabStyle(activeTab === "settings")}
          >
            Settings
          </Focusable>
          <Focusable
            focusClassName={
              activeTab === "backups" ? activeFocusClass : focusClass
            }
            onActivate={() => selectTab("backups")}
            style={tabStyle(activeTab === "backups")}
          >
            Backups
          </Focusable>
        </Focusable>

        {activeTab === "search" && <SearchTab />}
        {activeTab === "atom" && <AtomGamesTab />}
        {activeTab === "backups" && <BackupsTab />}
        {activeTab === "settings" && <SettingsTab />}
      </>
    );
  };

  return {
    name: "ASSella",
    content: <Content />,
    icon: (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
        <AssellaLogo size="20px" />
      </div>
    ),
    onDismount() {
      storePatchCleanup();
      contextMenuCleanup();
    },
  };
});
