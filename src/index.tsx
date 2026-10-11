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
import { initStorePatch, tagInAssellaCollection, addedAppIds, pendingAppIds } from "./StorePatch";
import { initContextMenuPatch } from "./LibraryPatch";

const AssellaLogo: React.FC<{ size?: number | string; style?: React.CSSProperties }> = ({
  size = "1em",
  style,
}) => (
  <svg
    viewBox="0 0 100 100"
    width={size}
    height={size}
    style={{ display: "inline-block", verticalAlign: "middle", ...style }}
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      d="M20.956 50.804 L49.999 16.921 L79.025 50.826 C85.468 58.562 84.421 70.081 76.679 76.52 C68.909 82.998 57.43 81.891 50.936 74.175 C50.435 73.58 49.516 73.582 49.018 74.181 C42.577 81.925 31.053 82.967 23.319 76.519 C15.559 70.065 14.558 58.574 20.956 50.804 Z"
      fill="#f4c8ab"
    />
    <path
      d="M49.051 14.187 C49.55 13.605 50.451 13.605 50.95 14.187 L80.93 49.207 C80.933 49.211 80.937 49.215 80.94 49.22 C88.272 58.013 87.086 71.117 78.28 78.44 C69.88 85.444 57.551 84.695 49.985 76.851 C42.461 84.72 30.094 85.422 21.721 78.441 C12.899 71.105 11.754 58.036 19.036 49.205 C19.041 49.199 19.046 49.193 19.051 49.187 Z M49.999 16.921 L20.957 50.804 C14.558 58.574 15.559 70.065 23.319 76.519 C31.054 82.968 42.578 81.926 49.019 74.181 C49.516 73.583 50.435 73.58 50.936 74.175 C57.431 81.891 68.91 82.998 76.68 76.52 C84.422 70.081 85.469 58.562 79.025 50.827 Z"
      fill="#000000"
    />
    <path
      d="M26.9 42 C42.3 46 57.7 46 73.1 42 C61.033 54 53.333 65 50 75 C46.667 65 38.967 54 26.9 42 Z"
      fill="#000000"
    />
    <path
      d="M72.762 56.826 C72.858 56.142 73.49 55.666 74.174 55.762 C74.858 55.858 75.334 56.49 75.238 57.174 C74.486 62.529 70.557 66.922 65.298 68.214 C64.628 68.379 63.951 67.969 63.786 67.298 C63.621 66.628 64.031 65.951 64.702 65.786 C68.968 64.738 72.152 61.169 72.762 56.826 Z"
      fill="#000000"
    />
  </svg>
);

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
  { ok: boolean; removed?: string[]; failed?: string[]; error?: string }
>("uninstall_atom_game");
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
    pendingAppIds.add(appId);
    bumpVersion();
    setMsg(`Adding ${title} to SLS...`);
    try {
      const r = await injectGame(appId);
      if (r && !r.error) {
        tagInAssellaCollection(appId);

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

type AtomDetail = AtomGame & {
  slsonline: boolean;
  fake_appid: string;
  netsock: boolean;
  eos: string;
  eos_available: boolean;
  registered: boolean;
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
  const [confirm, setConfirm] = React.useState<{
    game: AtomGame;
    preview: { targets: string[] };
  } | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const r = await listAtomGames();
      setGames(r?.games ?? []);
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
      if (p?.ok) setConfirm({ game: g, preview: p });
      else setMsg(p?.error || "Could not prepare uninstall");
    } catch (e: any) {
      setMsg(`Error: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const doUninstall = async () => {
    if (!confirm) return;
    const { game } = confirm;
    setConfirm(null);
    setBusy(true);
    setMsg("");
    try {
      const r = await uninstallAtomGame(game.app_id);
      if (r?.ok) {
        notify("Uran", `Uninstalled ${game.name}`);
        setMsg(`Uninstalled ${game.name}`);
        setDetail(null);
        await load();
      } else {
        setMsg(`Uninstall incomplete: ${(r?.failed || []).join("; ")}`);
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
            <PanelSectionRow key={g.app_id}>
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

      {confirm && (
        <ConfirmModal
          onCancel={() => setConfirm(null)}
          onOk={doUninstall}
          okButtonText="Uninstall"
          title={`Uninstall ${confirm.game.name}?`}
          body={
            <>
              <p>This will permanently delete:</p>
              <ul style={{ margin: "6px 0", paddingLeft: "18px" }}>
                {confirm.preview.targets.map((t) => (
                  <li key={t} style={{ fontSize: "11px", wordBreak: "break-all" }}>
                    {t}
                  </li>
                ))}
              </ul>
              <p>and remove the game from SLSsteam&apos;s config.</p>
              <p style={{ color: "#e57373" }}>This cannot be undone.</p>
            </>
          }
        />
      )}
    </>
  );
};

// -- Settings Tab -------------------------------------------------------------
const SettingsTab: React.FC = () => {
  const [showRestartButton, setShowRestartButton] = React.useState(false);
  const [fetchDlcsOnInject, setFetchDlcsOnInject] = React.useState(false);
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
        const [srb, fdl, mip, nm] = await Promise.all([
          getSetting("show_restart_button", false),
          getSetting("fetch_dlcs_on_inject", false),
          getSetting("manifestid_pinning", false),
          getSetting("notification_mode", "auto"),
        ]);
        if (!alive) return;
        setShowRestartButton(!!srb);
        setFetchDlcsOnInject(!!fdl);
        setManifestIdPinning(!!mip);
        if (nm) setNotificationModeState(nm);
      } catch {}
      loadStats();
    })();
    return () => {
      alive = false;
    };
  }, [loadStats]);

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

  // Poll while the capture server is up so the UI flips on its own.
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
      <PanelSection title="Hubcap API Key">
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

        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.75, lineHeight: 1.5 }}>
            The key is shared with ASSella via{" "}
            <code>~/.config/Tachibana Labs/ACCELA.conf</code>.
          </div>
        </PanelSectionRow>

        {stats.ok && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", lineHeight: 1.7, opacity: 0.9 }}>
              {stats.username && (
                <div>
                  Account <b>{stats.username}</b>
                </div>
              )}
              {stats.requests_remaining != null && (
                <div>
                  Requests today: {stats.daily_usage}/{stats.daily_limit} (
                  {stats.requests_remaining} left)
                </div>
              )}
              {stats.expires_at && <div>Key expires: {stats.expires_at}</div>}
            </div>
          </PanelSectionRow>
        )}
        {!stats.ok && stats.error && (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#e57373" }}>
              {stats.error}
            </div>
          </PanelSectionRow>
        )}
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
            label="Fetch DLCs on inject"
            description="Also register the game's DLC AppIDs."
            checked={fetchDlcsOnInject}
            onChange={(v) => {
              setFetchDlcsOnInject(v);
              setSetting("fetch_dlcs_on_inject", v);
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
              activeTab === "backups" ? activeFocusClass : focusClass
            }
            onActivate={() => selectTab("backups")}
            style={tabStyle(activeTab === "backups")}
          >
            Backups
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
