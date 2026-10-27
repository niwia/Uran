import { callable } from "@decky/api";

// -- Search & inject ----------------------------------------------------------
export type SearchResult = { app_id: string; title: string };
export type SearchResponse = { error?: string; results: SearchResult[] };
export type InjectResult = {
  error?: string;
  name?: string;
  depots?: string[];
  fetching?: boolean;
  blocked?: string;
  already_added?: boolean;
};
export type RecentInject = {
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
export type InjectStatus = {
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
} | null;

// -- AT0-M library ------------------------------------------------------------
export type AtomGame = {
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

export type AtomDepotInfo = {
  id: string;
  name: string;
  raw_name?: string;
  in_config: boolean;
  has_key: boolean;
  is_dlc: boolean;
  dlc_id?: string;
  is_shared: boolean;
  os: string;
  os_list?: string[];
  arch?: string;
  lang?: string;
  size_str?: string;
  owner?: string;
  is_app_key?: boolean;
};

export type AtomDlcInfo = {
  id: string;
  name: string;
  in_config: boolean;
  depot_count?: number;
  is_license_only?: boolean;
};

export type AtomKeyInfo = {
  id: string;
  name: string;
  key?: string;
  masked_key: string;
  is_appkey: boolean;
  in_config: boolean;
  in_local: boolean;
};

export type AtomDetail = AtomGame & {
  slsonline: boolean;
  global_slsonline?: boolean;
  fake_appid: string;
  netsock: boolean;
  eos: string;
  eos_available: boolean;
  registered: boolean;
  depots_detail?: AtomDepotInfo[];
  dlcs_detail?: AtomDlcInfo[];
  dlcs_injected?: boolean;
  keys_detail?: AtomKeyInfo[];
  meta?: { store: string; steamcmd: string; needs_fetch: boolean };
};

export type AtomUpdate = {
  ok?: boolean;
  status?: "up_to_date" | "update_available" | "key_pending" | "error" | string;
  has_update?: boolean;
  new_depots?: { id: string; name?: string }[];
  pending_depots?: { id: string; name?: string }[];
  cooldown_hours?: number;
  from?: string;
  error?: string;
};

export type AllAtomUpdates = {
  ok: boolean;
  updates?: Record<string, AtomUpdate>;
  update_count?: number;
  error_count?: number;
  pending_count?: number;
  checked?: number;
  cached?: number;
  error?: string;
};

// -- Plugin info / updates ----------------------------------------------------
export type UpdateInfo = {
  ok: boolean;
  current_version?: string;
  latest_version?: string;
  release_url?: string;
  has_update?: boolean;
  notes?: string;
  published_at?: string;
  error?: string;
};

// -- Hubcap gateway -----------------------------------------------------------
export type GatewayMode = "auto" | "direct" | "proxy";
export type RouteState = "unknown" | "ok" | "blocked" | "failed";

export const HUBCAP_HOST = "hubcapmanifest.com";
export const GATEWAY_LABELS: Record<GatewayMode, string> = {
  auto: "Automatic — try direct, fall back to the edge proxy if blocked",
  direct: "Direct only — never use the proxy",
  proxy: "Edge proxy only",
};
export const GATEWAY_OPTIONS: { data: GatewayMode; label: string }[] = (
  ["auto", "direct", "proxy"] as GatewayMode[]
).map((data) => ({ data, label: GATEWAY_LABELS[data] }));

export type RouteStatus = {
  mode?: GatewayMode;
  direct: RouteState;
  proxy: RouteState;
  fallback_used?: boolean;
  last_error?: string;
};

export type RouteProbe = {
  ok?: boolean;
  mode?: GatewayMode;
  routes?: {
    direct?: { ok?: boolean; detail?: string; ms?: number };
    proxy?: { ok?: boolean; detail?: string; ms?: number };
  };
};

export function routeLabel(state: RouteState): string {
  switch (state) {
    case "ok":
      return "reachable";
    case "blocked":
      return "blocked";
    case "failed":
      return "unreachable";
    default:
      return "not checked";
  }
}

export function routeTone(state: RouteState): string {
  switch (state) {
    case "ok":
      return "#7ee2a8";
    case "blocked":
    case "failed":
      return "#ff9a9a";
    default:
      return "#9aa4b2";
  }
}

// -- Backend callables (modern @decky/api, positional args) -------------------
// NOTE: backup callables (list_backups / create_backup / restore_backup) are
// intentionally not exposed here. The backend keeps them so Settings can
// re-add backup UI later without backend changes.
export const getRecentInjects = callable<[], RecentInject[]>("get_recent_injects");
export const searchGames = callable<
  [query: string, limit: number, appid: boolean],
  SearchResponse
>("search_games");
export const injectGame = callable<[app_id: string], InjectResult>("inject_game");
export const getSetting = callable<[key: string, defaultValue: any], any>(
  "get_setting",
);
export const setSetting = callable<[key: string, value: any], void>("set_setting");
export const getHubcapKeyStatus = callable<[], {
  ok: boolean;
  source: string;
  configured_path: string;
  masked: string;
  is_override: boolean;
  base_url: string;
  timestamp?: number;
}>("get_hubcap_key_status");
export const startKeyServer = callable<[], {
  ok: boolean;
  error?: string;
  running: boolean;
  port?: number | null;
  urls: string[];
  status: string;
  expires_in?: number;
}>("start_key_server");
export const keyServerStatus = callable<[], {
  running: boolean;
  port?: number | null;
  urls: string[];
  status: string;
  expires_in?: number;
  keys_added?: number;
}>("key_server_status");
export const stopKeyServer = callable<[], { ok: boolean }>("stop_key_server");
export const validateHubcapKey = callable<[key: string], {
  ok: boolean;
  message: string;
  detail: string;
}>("validate_hubcap_key");
export const saveHubcapKey = callable<[key: string], {
  ok: boolean;
  message: string;
}>("save_hubcap_key");
export const getHubcapUserStats = callable<[], {
  ok: boolean;
  username?: string;
  daily_usage?: number;
  daily_limit?: number;
  requests_remaining?: number | null;
  expires_at?: string;
  error?: string;
}>("get_hubcap_user_stats");

// -- AT0-M game management --
export const listAtomGames = callable<[], {
  ok: boolean;
  games: AtomGame[];
}>("list_plugin_games");
export const getAtomGame = callable<[app_id: string], AtomDetail & {
  ok: boolean;
  error?: string;
}>("get_atom_game");
export const refreshAtomMeta = callable<[app_id: string], AtomDetail & {
  ok: boolean;
  error?: string;
}>("refresh_atom_meta");
export const previewAtomUninstall = callable<
  [app_id: string],
  { ok: boolean; name?: string; targets: string[]; error?: string }
>("preview_atom_uninstall");
export const uninstallAtomGame = callable<
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
export const getStoreDebugStatus = callable<
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
export const setSlsonline = callable<
  [app_id: string, enabled: boolean, fake_appid: string],
  { ok: boolean; error?: string }
>("set_slsonline");
export const setNetsock = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_netsock_toggle");
export const setEos = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_eos_toggle");
export const setEosNetsock = callable<
  [app_id: string, enabled: boolean],
  { ok: boolean; error?: string }
>("set_eos_netsock");
export const toggleGameDlcs = callable<
  [app_id: string, enable: boolean],
  { ok: boolean; error?: string; count?: number }
>("toggle_game_dlcs");
export const toggleAdditionalApp = callable<
  [app_id: string, dlc_appid: string, enable: boolean],
  { ok: boolean; error?: string; dlc_id?: string; enabled?: boolean }
>("toggle_additional_app");
export const toggleAdditionalDepot = callable<
  [app_id: string, depot_id: string, enable: boolean],
  { ok: boolean; error?: string; depot_id?: string; enabled?: boolean }
>("toggle_additional_depot");
export const toggleDecryptionKey = callable<
  [app_id: string, target_id: string, enable: boolean],
  { ok: boolean; error?: string; target_id?: string; enabled?: boolean }
>("toggle_decryption_key");
export const refreshGame = callable<
  [app_id: string],
  { ok: boolean; error?: string; depots_added?: string[]; keys_added?: string[] }
>("refresh_game");
export const refetchGame = callable<
  [app_id: string],
  {
    ok: boolean;
    error?: string;
    name?: string;
    depots_added?: string[];
    keys_added?: string[];
    dlcs_added?: string[];
  }
>("refetch_game");
export const applyDepotSelection = callable<
  [app_id: string, depot_ids?: string[], dlc_ids?: string[], key_ids?: string[]],
  {
    ok: boolean;
    error?: string;
    depots_added?: string[];
    keys_added?: string[];
    dlc_appids?: string[];
  }
>("apply_depot_selection");
export const isGlobalSlsOnlineEnabled = callable<[], {
  ok: boolean;
  enabled: boolean;
  config_path?: string;
}>(
  "is_global_slsonline_enabled",
);
export const setGlobalSlsOnline = callable<[enabled: boolean], { ok: boolean; enabled: boolean }>(
  "set_global_slsonline",
);
export const checkForUpdates = callable<[], UpdateInfo>("check_for_updates");
export const getPluginInfo = callable<[], { name: string; version: string }>("get_plugin_info");
export type SlsPluginDeployStatus = {
  ok: boolean;
  error?: string;
  directory?: string;
  active_interceptor?: string | null;
  plugins?: Record<string, {
    label: string;
    kind?: "interceptor" | "companion";
    state: "missing" | "outdated" | "up_to_date" | "unknown";
    active: boolean;
    version?: string | null;
    available_remote?: boolean;
    user_disabled?: boolean;
  }>;
};
export const getSlsPluginDeployStatus = callable<[], SlsPluginDeployStatus>(
  "get_sls_plugin_deploy_status",
);
export const deploySlsPlugin = callable<[filename: string], {
  ok: boolean;
  message?: string;
  error?: string;
}>("deploy_sls_plugin");
export const enableSlsPlugin = callable<[filename: string], {
  ok: boolean;
  error?: string;
}>("enable_sls_plugin");
export const disableSlsPlugin = callable<[filename: string], {
  ok: boolean;
  error?: string;
}>("disable_sls_plugin");

export const checkAtomGameUpdates = callable<[app_id: string], AtomUpdate>(
  "check_atom_game_updates",
);
export const checkAllAtomUpdates = callable<[], AllAtomUpdates>(
  "check_all_atom_updates",
);
export const refetchManifests = callable<
  [app_id: string],
  { ok?: boolean; error?: string; updated?: boolean }
>("refetch_manifests");
export const openExternalUrl = callable<
  [url: string],
  { ok?: boolean; error?: string }
>("open_external_url");
export const getHubcapRoutes = callable<[], RouteStatus>("get_hubcap_routes");
export const testHubcapRoutes = callable<[], RouteProbe>("test_hubcap_routes");
export const getInjectStatus = callable<[app_id: string], InjectStatus>(
  "get_inject_status",
);

// -- Session-once memo --------------------------------------------------------
// Decky has no onOpen hook: the plugin module stays loaded while the QAM page
// lives, and each tab unmounts when the user leaves it. Mount-time status
// checks (health, updates, stats, routes) therefore memoize here so they run
// once per plugin session instead of once per tab visit. Failures evict so a
// later visit retries rather than sticking a failed result forever.
const onceCache = new Map<string, Promise<any>>();

export function once<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const hit = onceCache.get(key);
  if (hit) return hit as Promise<T>;
  const p = fn();
  onceCache.set(key, p);
  p.catch(() => {
    if (onceCache.get(key) === p) onceCache.delete(key);
  });
  return p;
}

export function refreshOnce<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const p = fn();
  onceCache.set(key, p);
  p.catch(() => {
    if (onceCache.get(key) === p) onceCache.delete(key);
  });
  return p;
}

// -- Health (read-only) -------------------------------------------------------
export type HealthPlugins = {
  ok: boolean;
  plugins_enabled: boolean;
  plugins: string[];
  searched?: string[];
};
export type HealthSls = {
  status: "up_to_date" | "outdated" | "no_local" | "error" | string;
  release_tag?: string | null;
  local_mtime?: number | null;
  error?: string | null;
};
export type HealthStatus = {
  ok: boolean;
  plugins: HealthPlugins;
  sls: HealthSls;
};
export type ConfigCheck = {
  ok: boolean;
  needs_attention: boolean;
  summary: string;
  details: string[];
};

export const getHealthStatus = callable<[], HealthStatus>("get_health_status");
export const checkConfigStatus = callable<
  [online: boolean],
  ConfigCheck
>("check_config_status");

// -- SpaceBunny Configuration Bridge -----------------------------------------
export type SpaceBunnyHubcapConfig = {
  enabled: boolean;
  base_url: string;
  api_key: string;
  api_key_timestamp: number;
  timeout_sec: number;
  write_config: boolean;
  notify: boolean;
  preflight: string;
  depot_index: boolean;
  write_depot_comments: boolean;
};

export type SpaceBunnyConfig = {
  standalone: boolean;
  hubcap: SpaceBunnyHubcapConfig;
  exists?: boolean;
  path?: string;
};

export type SpaceBunnyResponse = {
  ok: boolean;
  config?: SpaceBunnyConfig;
  error?: string;
};

export const getSpaceBunnyConfig = callable<[], SpaceBunnyResponse>(
  "get_spacebunny_config",
);

export const saveSpaceBunnyConfig = callable<
  [config: { standalone: boolean; hubcap: Partial<SpaceBunnyHubcapConfig> }],
  SpaceBunnyResponse
>("save_spacebunny_config");

