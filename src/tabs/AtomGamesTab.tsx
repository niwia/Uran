import React from "react";
import {
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  DialogButton,
  ToggleField,
  Focusable,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { notify } from "../notify";
import {
  listAtomGames,
  getAtomGame,
  refreshAtomMeta,
  previewAtomUninstall,
  uninstallAtomGame,
  checkAllAtomUpdates,
  refetchManifests,
  setSlsonline,
  setNetsock,
  setEos,
  setEosNetsock,
  toggleAdditionalApp,
  refreshGame,
  AtomGame,
  AtomDetail,
  AtomUpdate,
} from "../api";
import { addedAppIds, syncAddedAppIds } from "../StorePatch";
import {
  TrashIcon,
  WindowsIcon,
  LinuxIcon,
  AppleIcon,
  AndroidIcon,
} from "../components/icons";
import { formatBytes } from "../components/format";
import { DepotManagerModal } from "../components/DepotManagerModal";

const URAN_STYLES = `
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
  .uran-game-pill-content {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    width: 100% !important;
    min-width: 0 !important;
    gap: 6px !important;
  }
  .uran-game-pill-title {
    flex: 1 1 0% !important;
    min-width: 0 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    text-align: left !important;
    font-size: 13px !important;
  }
  .uran-game-pill-badge {
    flex-shrink: 0 !important;
    font-size: 13px !important;
    color: #7ee2a8 !important;
    font-weight: 700 !important;
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
  .uran-depot-container {
    display: flex !important;
    flex-direction: column !important;
    gap: 6px !important;
    width: 100% !important;
  }
  .uran-depot-filters {
    display: flex !important;
    align-items: center !important;
    gap: 6px !important;
    margin-bottom: 6px !important;
    flex-wrap: wrap !important;
  }
  .uran-depot-card {
    display: flex !important;
    flex-direction: column !important;
    padding: 8px 10px !important;
    background: rgba(255, 255, 255, 0.04) !important;
    border: 1px solid rgba(255, 255, 255, 0.06) !important;
    border-radius: 6px !important;
    gap: 5px !important;
    width: 100% !important;
    box-sizing: border-box !important;
  }
  .uran-depot-header {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    gap: 6px !important;
    width: 100% !important;
  }
  .uran-depot-tags {
    display: flex !important;
    align-items: center !important;
    gap: 4px !important;
    flex-wrap: wrap !important;
  }
  .uran-depot-os-group {
    display: inline-flex !important;
    align-items: center !important;
    padding: 2px 4px !important;
    background: rgba(255, 255, 255, 0.06) !important;
    border-radius: 4px !important;
  }
  .uran-badge {
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    font-size: 10px !important;
    font-weight: 600 !important;
    padding: 1px 5px !important;
    border-radius: 4px !important;
    letter-spacing: 0.3px !important;
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
  .uran-depot-name {
    font-size: 13px !important;
    color: #ffffff !important;
    font-weight: 500 !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    text-align: left !important;
  }
  .uran-depot-size {
    font-size: 11px !important;
    color: #9aa4b2 !important;
    flex-shrink: 0 !important;
    font-family: monospace !important;
  }
`;

/** Plain-language status for the metadata the page is waiting on. */
function fetchNote(meta?: AtomDetail["meta"]): string {
  const stale: string[] = [];
  if (!meta || meta.store !== "fresh") stale.push("AppIDs / DLCs");
  if (!meta || meta.steamcmd !== "fresh") stale.push("depot info");
  return `Fetching ${stale.join(" and ")}…`;
}

export const AtomGamesTab: React.FC = () => {
  const [games, setGames] = React.useState<AtomGame[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [detail, setDetail] = React.useState<AtomDetail | null>(null);
  const [checkingUpdates, setCheckingUpdates] = React.useState(false);
  const [atomUpdates, setAtomUpdates] = React.useState<Record<string, AtomUpdate>>({});
  const [busy, setBusy] = React.useState(false);
  const [metaLoading, setMetaLoading] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [depotFilter, setDepotFilter] = React.useState<"all" | "windows" | "linux" | "dlc">("all");
  const detailUpdate = detail ? atomUpdates[detail.app_id] : undefined;

  const handleCheckAllUpdates = async () => {
    setCheckingUpdates(true);
    setMsg("Checking AT0-M games against Hubcap…");
    try {
      const res = await checkAllAtomUpdates();
      const updates = res?.updates || {};
      setAtomUpdates(updates);
      const count = res?.update_count ?? 0;
      const failed = res?.error_count ?? 0;
      const pending = res?.pending_count ?? 0;
      const cached = res?.cached ?? 0;

      // A failed check is not "no updates". Never summarise a partial sweep as
      // a clean one — that is how a missing API key used to read as
      // "everything is up to date".
      const parts: string[] = [];
      if (count > 0) {
        parts.push(`${count} update${count > 1 ? "s" : ""} ready on Hubcap`);
      }
      if (pending > 0) {
        parts.push(`${pending} waiting on Hubcap keys`);
      }
      if (failed > 0) {
        parts.push(`${failed} could not be checked`);
      }

      if (parts.length === 0) {
        notify("Uran", "All AT0-M games are up to date with Hubcap");
        setMsg(
          cached > 0
            ? `All ${res?.checked ?? 0} games up to date (${cached} answered from ASSella's cache).`
            : "All AT0-M games are up to date.",
        );
        return;
      }

      const summary = parts.join(" · ");
      notify("Uran", summary);
      setMsg(
        failed > 0 && count === 0 && pending === 0
          ? `${summary}. ${res?.error || "Check failed."}`
          : summary,
      );
    } catch (e: any) {
      setMsg(`Update check failed: ${e}`);
    } finally {
      setCheckingUpdates(false);
    }
  };

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
    setDepotFilter("all");
    try {
      // Phase 1: local-only, renders instantly from disk. The Steam metadata
      // (DLC list + depot attribution) is cached with a TTL, so if it is still
      // fresh the page is complete without touching the network at all.
      const d = await getAtomGame(appId);
      if (!d?.ok) {
        setMsg(d?.error || "Could not open game");
        return;
      }
      setDetail(d as AtomDetail);
      // Phase 2: only when a cached source is stale or missing. The page is
      // already on screen, so the DLC list fills in behind the scenes.
      if (d.meta?.needs_fetch) {
        setMetaLoading(true);
        refreshAtomMeta(appId)
          .then((full) => {
            if (full?.ok) {
              setDetail((cur) =>
                cur && cur.app_id === full.app_id ? (full as AtomDetail) : cur,
              );
            }
          })
          .catch(() => {})
          .finally(() => setMetaLoading(false));
      }
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
    // What the AppIDs above actually mount right now: the base game plus every
    // enabled DLC's depots. Uran keeps this in sync, so it is shown for reference.
    const depots = (detail.depots_detail || []).filter((d) => d.in_config);
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
      <>
        <style>{URAN_STYLES}</style>
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
              description={
                detail.global_slsonline
                  ? "Locked ON via Global SLS Online (0: 480)"
                  : "Map this game to Spacewar (480) for online features."
              }
              checked={detail.global_slsonline || detail.slsonline}
              disabled={busy || notInstalled || detail.global_slsonline}
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

        <PanelSection title={`AppIDs (${(detail.dlcs_detail?.length || 0) + 1})`}>
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.6, padding: "0 0 4px" }}>
              The base game is always mounted. Toggle a DLC and Uran adds or
              removes the depots and decryption keys it owns — turning one off
              removes exactly what it added.
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                padding: "4px 0",
              }}
            >
              <span
                title={detail.name}
                style={{
                  flex: 1,
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {detail.name}
              </span>
              <span className="uran-badge uran-badge-id">Base</span>
              <span className="uran-badge uran-badge-config">Mounted</span>
            </div>
          </PanelSectionRow>
          {metaLoading && (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: "#f0c674", padding: "2px 0 6px" }}>
                {fetchNote(detail.meta)}
              </div>
            </PanelSectionRow>
          )}
          {detail.dlcs_detail && detail.dlcs_detail.length > 0 ? (
            detail.dlcs_detail.map((dlc) => (
              <PanelSectionRow key={dlc.id}>
                <ToggleField
                  label={dlc.name}
                  description={
                    `AppID: ${dlc.id}` +
                    (dlc.is_license_only
                      ? " · License Only"
                      : dlc.depot_count
                      ? ` · ${dlc.depot_count} depot${
                          dlc.depot_count === 1 ? "" : "s"
                        }`
                      : "")
                  }
                  checked={dlc.in_config}
                  disabled={busy}
                  onChange={(v) =>
                    toggle(`DLC ${dlc.id}`, async () => {
                      const res = await toggleAdditionalApp(detail.app_id, dlc.id, v);
                      if (res?.ok) {
                        setDetail((d) =>
                          d
                            ? {
                                ...d,
                                dlcs_detail: d.dlcs_detail?.map((x) =>
                                  x.id === dlc.id ? { ...x, in_config: v } : x,
                                ),
                              }
                            : d,
                        );
                      }
                      return res;
                    })
                  }
                />
              </PanelSectionRow>
            ))
          ) : (
            <PanelSectionRow>
              <div style={{ fontSize: "12px", opacity: 0.6, padding: "4px 0" }}>
                {metaLoading
                  ? "Loading AppIDs…"
                  : "No DLC AppIDs found for this game."}
              </div>
            </PanelSectionRow>
          )}
        </PanelSection>

        <PanelSection title="Depots & Decryption Keys">
          <PanelSectionRow>
            <div style={{ fontSize: "11px", opacity: 0.65, padding: "0 0 6px" }}>
              Configure game content depots, license-only DLCs, and AES decryption keys
              in a full-screen gamepad-friendly manager.
            </div>
          </PanelSectionRow>
          {metaLoading && (
            <PanelSectionRow>
              <div style={{ fontSize: "11px", color: "#f0c674", padding: "2px 0 6px" }}>
                {fetchNote(detail.meta)}
              </div>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "6px" }}>
              <span className="uran-badge uran-badge-config">
                {detail.depots_detail?.filter((d) => d.in_config).length ?? detail.depots?.length ?? 0} Depots Mounted
              </span>
              <span className="uran-badge uran-badge-key">
                {detail.keys_detail?.filter((k) => k.in_config).length ?? 0} Keys Active
              </span>
              {detail.dlcs_detail && (
                <span className="uran-badge uran-badge-dlc">
                  {detail.dlcs_detail.filter((d) => d.in_config).length} DLCs Enabled
                </span>
              )}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy}
              onClick={() => {
                showModal(
                  <DepotManagerModal
                    appId={detail.app_id}
                    appName={detail.name}
                    initialDetail={detail}
                    onUpdate={() => openGame(detail.app_id)}
                  />
                );
              }}
            >
              ⚙️ Manage Depots &amp; Keys
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy}
              onClick={() =>
                toggle("Refresh", async () => {
                  const r = await refreshGame(detail.app_id);
                  if (r?.ok) {
                    const added = r.depots_added?.length || 0;
                    notify(
                      "Uran",
                      `Refreshed ${detail.name} (${added} depot${
                        added === 1 ? "" : "s"
                      })`,
                    );
                    await openGame(detail.app_id);
                  }
                  return r;
                })
              }
            >
              🔄 Refresh Keys &amp; Depots
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>

        {detailUpdate &&
          (detailUpdate.status === "update_available" ||
            detailUpdate.status === "key_pending" ||
            detailUpdate.status === "error") && (
          <PanelSection title="Hubcap Updates">
            <PanelSectionRow>
              <div style={{ width: "100%", fontSize: "12px", lineHeight: 1.6 }}>
                {detailUpdate.status === "key_pending" ? (
                  <div>
                    <div style={{ color: "#f0c674", fontWeight: 600, marginBottom: "4px" }}>
                      Waiting on Hubcap keys
                    </div>
                    <div style={{ opacity: 0.8, marginBottom: detailUpdate.pending_depots?.length ? "8px" : "0" }}>
                      Steam lists {detailUpdate.pending_depots?.length || 0} depot
                      {(detailUpdate.pending_depots?.length || 0) === 1 ? "" : "s"} that
                      Hubcap has not generated yet. Nothing to fetch right now — they
                      will be picked up on a later check
                      {detailUpdate.cooldown_hours
                        ? ` (checked at most every ${detailUpdate.cooldown_hours}h).`
                        : "."}
                    </div>
                    {!!detailUpdate.pending_depots?.length && (
                      <div style={{ marginBottom: "4px" }}>
                        {detailUpdate.pending_depots.map((d) => (
                          <div key={d.id} style={{ opacity: 0.75 }}>
                            &bull; {d.name || `Depot ${d.id}`}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : detailUpdate.status === "error" ? (
                  <div style={{ color: "#ff9a9a" }}>
                    Could not check Hubcap: {detailUpdate.error || "unknown error"}
                  </div>
                ) : (
                  <div>
                    <div style={{ color: "#7ee2a8", fontWeight: 600, marginBottom: "4px" }}>
                      Update Available ({detailUpdate.new_depots?.length || 0} new depots ready)
                    </div>
                    <div style={{ opacity: 0.8, marginBottom: "8px" }}>
                      New depots or keys are ready on Hubcap for this game.
                    </div>
                  <ButtonItem
                    layout="below"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      notify("Uran", `Fetching updates for ${detail.name}…`);
                      try {
                        const r = await refetchManifests(detail.app_id);
                        if (r?.ok) {
                          notify("Uran", `Updated ${detail.name}!`);
                          setMsg(`Updated ${detail.name} with new depots and keys.`);
                          setAtomUpdates((prev) => ({
                            ...prev,
                            [detail.app_id]: {
                              ...prev[detail.app_id],
                              has_update: false,
                              new_depots: [],
                              status: "up_to_date",
                            },
                          }));
                          await refreshDetail();
                        } else {
                          notify("Uran", `Update failed: ${r?.error || "Error"}`);
                          setMsg(`Update failed: ${r?.error || "Error"}`);
                        }
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Fetch &amp; Apply Updates
                  </ButtonItem>
                </div>
                )}
              </div>
            </PanelSectionRow>
          </PanelSection>
        )}

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
      <style>{URAN_STYLES}</style>

      <PanelSection title={`AT0-M Games (${games.length})`}>
        {games.length > 0 && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy || checkingUpdates}
              onClick={handleCheckAllUpdates}
            >
              {checkingUpdates ? "Checking Updates…" : "Check Updates"}
            </ButtonItem>
          </PanelSectionRow>
        )}
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
          games.map((g) => {
            const hasUpdate = !!atomUpdates[g.app_id]?.has_update;
            const isPending = atomUpdates[g.app_id]?.status === "key_pending";
            const checkError = atomUpdates[g.app_id]?.status === "error";
            return (
              <PanelSectionRow key={g.app_id} style={{ marginBottom: "6px" }}>
                <Focusable
                  flow-children="horizontal"
                  className="uran-game-row"
                >
                  <DialogButton
                    className="uran-game-pill"
                    onClick={() => openGame(g.app_id)}
                  >
                    <div className="uran-game-pill-content">
                      <span className="uran-game-pill-title">{g.name}</span>
                      {hasUpdate && (
                        <span className="uran-game-pill-badge" title="Update available on Hubcap">
                          ⬆
                        </span>
                      )}
                      {isPending && (
                        <span
                          className="uran-game-pill-badge"
                          style={{ opacity: 0.65 }}
                          title="Waiting for Hubcap to generate keys for new depots"
                        >
                          ⏳
                        </span>
                      )}
                      {checkError && (
                        <span
                          className="uran-game-pill-badge"
                          style={{ color: "#ff9a9a" }}
                          title="Last check failed"
                        >
                          !
                        </span>
                      )}
                    </div>
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
            );
          })
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

