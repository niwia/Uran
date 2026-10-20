/**
 * LibraryPatch.tsx — Context menu hooks and library management actions for Uran.
 *
 * Hooks into Steam's native "Manage" context menu on games and downloads:
 *   - Add/Remove FakeAppId
 *   - Fetch DLCs (via Hubcap API)
 *   - Fetch/Update Manifests (via Hubcap API)
 *   - Remove Pinned Manifests
 *   - Why is this game not downloading? (diagnostic check)
 */
import { MenuItem, findModuleExport } from "@decky/ui";
import { callable, routerHook } from "@decky/api";
import { notify } from "./notify";

const SP_REACT = (window as any).SP_REACT;
const h = SP_REACT?.createElement?.bind(SP_REACT);

// -- Backend callables --------------------------------------------------------
type FakeAppIds = { ok?: boolean; ids?: string[] };
type SimpleResult = {
  ok?: boolean;
  error?: string;
  already?: boolean;
  removed?: string[];
};
type ManifestRefetchResult = {
  ok?: boolean;
  app_id?: string;
  manifests?: string[];
  depotcache?: string;
  written?: number;
  manifest_ids?: Record<string, string>;
  removed_files?: string[];
  removed_pins?: string[];
  error?: string;
};
const getFakeAppIds = callable<[], FakeAppIds>("get_fake_app_ids");
const addFakeAppId = callable<[app_id: string], SimpleResult>("add_fake_app_id");
const removeFakeAppId = callable<[app_id: string], SimpleResult>(
  "remove_fake_app_id",
);
const refetchManifests = callable<[app_id: string], ManifestRefetchResult>(
  "refetch_manifests",
);
const whyNotDownloading = callable<
  [app_id: string],
  {
    ok?: boolean;
    app_id?: string;
    name?: string;
    reason?: string;
    detail?: string;
    headline?: string;
    message?: string;
    error?: string;
  }
>("why_not_downloading");

const removeManifestIdPins = callable<
  [app_id: string],
  { ok?: boolean; app_id?: string; removed_pins?: string[]; error?: string }
>("remove_manifest_id_pins");

const fetchDlcs = callable<
  [app_id: string],
  {
    ok?: boolean;
    app_id?: string;
    count?: number;
    dlc_ids?: string[];
    apps_added?: string[];
    depots_added?: string[];
    keys_added?: string[];
    failed_keys?: string[];
    skipped_dlcs?: string[];
    message?: string;
    error?: string;
  }
>("fetch_dlcs_for_app");

const feDebug = callable<[msg: string], void>("fe_debug");

function feLog(msg: string): void {
  try {
    feDebug(msg);
  } catch {}
  try {
    console.log("[ASSella Library] " + msg);
  } catch {}
}

const fakeAppIdsCache = new Set<string>();

async function refreshFakeAppIds(): Promise<void> {
  try {
    const res = await getFakeAppIds();
    fakeAppIdsCache.clear();
    (res?.ids || []).forEach((id) => fakeAppIdsCache.add(id));
  } catch {}
}

// Initial cache load
refreshFakeAppIds();

// -- Context Menu Patch (Manage submenu) -------------------------------------
let _contextMenuPatches: (() => void)[] = [];

function appIdFromMenuElement(element: any): string {
  const props = element?.props;
  if (!props) return "";
  for (const candidate of [props.overview, props.app, props.item, props]) {
    const appid = candidate?.appid;
    if (appid) return String(appid);
  }
  return "";
}

export function initContextMenuPatch(): () => void {
  const MenuInstanceClass: any = findModuleExport((e: any) => {
    if (!e || typeof e !== "function" || !e.prototype) return false;
    const p = e.prototype;
    return (
      typeof p.ShowMenu === "function" &&
      typeof p.HideMenu === "function" &&
      typeof p.ShowSubMenu === "function"
    );
  });

  if (!MenuInstanceClass) {
    feLog("initContextMenuPatch: MenuInstanceClass not found");
    return () => {};
  }

  const baseProto = MenuInstanceClass.prototype;
  if (!baseProto || typeof baseProto.ShowSubMenu !== "function") {
    feLog("initContextMenuPatch: ShowSubMenu not found on prototype");
    return () => {};
  }

  feLog("initContextMenuPatch: hooking base ShowSubMenu");

  const isAssellaItem = (c: any) =>
    c?.props?.["data-assella-fakeappid"] ||
    c?.props?.["data-assella-fetch-decryption-keys"] ||
    c?.props?.["data-assella-fetch-dlcs"] ||
    c?.props?.["data-assella-fetch-manifest"] ||
    c?.props?.["data-assella-remove-manifest-pins"] ||
    c?.props?.["data-assella-why-not-downloading"] ||
    c?.props?.["data-assella-remove-installed-depots"];

  const origShowSubMenu = baseProto.ShowSubMenu;
  baseProto.ShowSubMenu = function (
    element: any,
    renderFn: any,
    ...rest: any[]
  ) {
    try {
      const appId = appIdFromMenuElement(this?.ReactElement);
      if (appId && typeof renderFn === "function") {
        const origRender = renderFn;
        const wrappedRender = () => {
          const el = origRender();
          const kids = el?.props?.children;
          if (!Array.isArray(kids)) return el;

          const isShortcut = parseInt(appId, 10) >= 1000000000;
          const menuTexts = (() => {
            const found = { uninstall: false, remove: false };
            const stack: any[] = [...kids];
            while (stack.length > 0) {
              const node = stack.pop();
              if (!node) continue;
              const text = node?.props?.children;
              if (typeof text === "string") {
                if (text.includes("Uninstall")) found.uninstall = true;
                if (text.includes("Remove non-Steam game")) found.remove = true;
              }
              const sub = node?.props?.children;
              if (Array.isArray(sub)) stack.push(...sub);
              else if (sub && typeof sub === "object") stack.push(sub);
            }
            return found;
          })();

          const isManageMenu =
            el?.props?.label === "Manage" ||
            menuTexts.uninstall ||
            (isShortcut && menuTexts.remove);

          if (!isManageMenu) return el;

          const isFake = fakeAppIdsCache.has(appId);

          const fakeMenuItem = h(
            MenuItem,
            {
              key: "assella-fakeappid",
              "data-assella-fakeappid": appId,
              onSelected: async () => {
                try {
                  if (isFake) {
                    const r = await removeFakeAppId(appId);
                    if (r?.ok) {
                      fakeAppIdsCache.delete(appId);
                      notify("Uran", `Removed FakeAppid for ${appId}`);
                    } else {
                      notify(
                        "Uran",
                        r?.error || "Failed to remove FakeAppid",
                      );
                    }
                  } else {
                    const r = await addFakeAppId(appId);
                    if (r?.ok) {
                      fakeAppIdsCache.add(appId);
                      const msg = r?.already
                        ? `FakeAppid already set for ${appId}`
                        : `FakeAppid added for ${appId}: 480`;
                      notify("Uran", msg);
                    } else {
                      notify(
                        "Uran",
                        r?.error || "Failed to add FakeAppid",
                      );
                    }
                  }
                } catch (e) {
                  notify("Uran", `Error: ${e}`);
                }
              },
            },
            isFake ? "Remove FakeAppid" : "Add FakeAppid (480)",
          );

          const fetchDlcsMenuItem = h(
            MenuItem,
            {
              key: "assella-fetch-dlcs",
              "data-assella-fetch-dlcs": appId,
              onSelected: async () => {
                try {
                  notify("Uran", `Fetching DLCs for ${appId}...`);
                  const r = await fetchDlcs(appId);
                  if (r?.ok) {
                    const count = r.count ?? 0;
                    if (count === 0) {
                      notify("Uran", `No DLCs found for ${appId}`);
                    } else {
                      const apps = r.apps_added?.length ?? 0;
                      const depots = r.depots_added?.length ?? 0;
                      const keys = r.keys_added?.length ?? 0;
                      const skipped = r.skipped_dlcs?.length ?? 0;
                      const parts: string[] = [];
                      if (apps > 0) parts.push(`${apps} app(s)`);
                      if (depots > 0) parts.push(`${depots} depot(s)`);
                      if (keys > 0) parts.push(`${keys} key(s)`);
                      const summary =
                        parts.length > 0
                          ? `Added: ${parts.join(", ")}`
                          : "DLCs already configured";
                      const skipNote =
                        skipped > 0 ? ` (${skipped} skipped)` : "";
                      notify(
                        "Uran",
                        `Found ${count} DLC(s) for ${appId}. ${summary}${skipNote}`,
                      );
                    }
                  } else {
                    notify(
                      "Uran",
                      r?.error || `Failed to fetch DLCs for ${appId}`,
                    );
                  }
                } catch (e) {
                  notify("Uran", `Error: ${e}`);
                }
              },
            },
            "Fetch DLCs",
          );

          const fetchManifestMenuItem = h(
            MenuItem,
            {
              key: "assella-fetch-manifest",
              "data-assella-fetch-manifest": appId,
              onSelected: async () => {
                try {
                  notify(
                    "Uran",
                    `Fetching Hubcap manifest bundle for ${appId}...`,
                  );
                  const r = await refetchManifests(appId);
                  if (r?.ok) {
                    const written = r.written ?? 0;
                    const manifests = r.manifests || [];
                    const clearedPins = r.removed_pins?.length ?? 0;
                    const clearedMsg =
                      clearedPins > 0
                        ? ` (cleared ${clearedPins} old pin(s))`
                        : "";
                    notify(
                      "Uran",
                      manifests.length > 0
                        ? `Extracted ${written} manifest(s) to depotcache${clearedMsg}`
                        : "Manifest bundle downloaded and parsed",
                    );
                  } else {
                    notify(
                      "Uran",
                      r?.error || `Failed to fetch manifest for ${appId}`,
                    );
                  }
                } catch (e) {
                  notify("Uran", `Error: ${e}`);
                }
              },
            },
            "Fetch manifest (Hubcap)",
          );

          const removeManifestPinsMenuItem = h(
            MenuItem,
            {
              key: "assella-remove-manifest-pins",
              "data-assella-remove-manifest-pins": appId,
              onSelected: async () => {
                try {
                  const r = await removeManifestIdPins(appId);
                  if (r?.ok) {
                    const count = r.removed_pins?.length ?? 0;
                    notify(
                      "Uran",
                      count > 0
                        ? `Removed ${count} pinned manifest(s) for ${appId}`
                        : `No pinned manifests found for ${appId}`,
                    );
                  } else {
                    notify(
                      "Uran",
                      r?.error || `Failed to remove manifest pins for ${appId}`,
                    );
                  }
                } catch (e) {
                  notify("Uran", `Error: ${e}`);
                }
              },
            },
            "Remove pinned manifests",
          );


          const whyNotDownloadingMenuItem = h(
            MenuItem,
            {
              key: "assella-why-not-downloading",
              "data-assella-why-not-downloading": appId,
              onSelected: async () => {
                try {
                  const r = await whyNotDownloading(appId);
                  if (r?.ok && r.message) {
                    notify("Uran", r.message);
                  } else {
                    notify(
                      "Uran",
                      r?.error || `Could not inspect app ${appId}`,
                    );
                  }
                } catch (e) {
                  notify("Uran", `Error: ${e}`);
                }
              },
            },
            "Why not downloading?",
          );

          // Remove any duplicate instances before injecting
          const filteredKids = kids.filter((c: any) => !isAssellaItem(c));

          // Place our ASSella items at the beginning of the Manage menu
          const assellaItems = [
            fakeMenuItem,
            fetchDlcsMenuItem,
            fetchManifestMenuItem,
            removeManifestPinsMenuItem,
            whyNotDownloadingMenuItem,
          ];

          return {
            ...el,
            props: {
              ...el.props,
              children: [...assellaItems, ...filteredKids],
            },
          };
        };

        return origShowSubMenu.call(this, element, wrappedRender, ...rest);
      }
    } catch (e) {
      feLog("ShowSubMenu hook error: " + e);
    }
    return origShowSubMenu.call(this, element, renderFn, ...rest);
  };

  _contextMenuPatches.push(() => {
    baseProto.ShowSubMenu = origShowSubMenu;
  });

  return () => {
    _contextMenuPatches.forEach((unpatch) => unpatch());
    _contextMenuPatches = [];
  };
}
