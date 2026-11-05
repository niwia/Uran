import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Navigation,
  PanelSection,
  PanelSectionRow,
  Field,
  ToggleField,
  ButtonItem,
  TextField,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { FaChevronDown, FaChevronUp, FaRedo, FaTrash, FaSlidersH, FaSteam, FaExclamationCircle } from "react-icons/fa";
import {
  listAtomGames,
  getAtomGame,
  setSlsonline,
  setNetsock,
  setEos,
  refetchManifests,
  previewAtomUninstall,
  uninstallAtomGame,
  checkAllAtomUpdates,
  type AtomGame,
  type AtomDetail,
  type AtomUpdate,
} from "../api";
import { syncAddedAppIds } from "../StorePatch";
import { notify } from "../notify";
import { formatBytes } from "../components/format";
import { openAdvanced } from "../pages/AdvancedPage";

interface GameAccordionItemProps {
  game: AtomGame;
  isExpanded: boolean;
  onToggle: () => void;
  onGameUninstalled: () => void;
  updateInfo?: AtomUpdate;
}

const GameAccordionItem: React.FC<GameAccordionItemProps> = ({
  game,
  isExpanded,
  onToggle,
  onGameUninstalled,
  updateInfo,
}) => {
  const [detail, setDetail] = useState<AtomDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  useEffect(() => {
    if (!isExpanded || detail) return;
    let cancelled = false;
    setLoadingDetail(true);
    getAtomGame(game.app_id)
      .then((d) => {
        if (!cancelled && d) setDetail(d);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isExpanded, detail, game.app_id]);

  const handleToggleSlsOnline = async (enabled: boolean) => {
    if (!detail) return;
    setBusyAction("slsonline");
    try {
      const res = await setSlsonline(game.app_id, enabled, "480");
      if (res?.ok) {
        setDetail({ ...detail, slsonline: enabled });
        notify("SLS Online", enabled ? "Enabled (0: 480)" : "Disabled");
      } else {
        notify("SLS Online", res?.error || "Failed to update SLS Online");
      }
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleNetsock = async (enabled: boolean) => {
    if (!detail) return;
    setBusyAction("netsock");
    try {
      const res = await setNetsock(game.app_id, enabled);
      if (res?.ok) {
        setDetail({ ...detail, netsock: enabled });
        notify("NetSock", enabled ? "Enabled" : "Disabled");
      } else {
        notify("NetSock", res?.error || "Failed to update NetSock");
      }
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleEos = async (enabled: boolean) => {
    if (!detail) return;
    setBusyAction("eos");
    try {
      const res = await setEos(game.app_id, enabled);
      if (res?.ok) {
        setDetail({ ...detail, eos: enabled ? "manual" : "disabled" });
        notify("EOS", enabled ? "Enabled" : "Disabled");
      } else {
        notify("EOS", res?.error || "Failed to update EOS");
      }
    } finally {
      setBusyAction(null);
    }
  };

  const handleRefetch = async () => {
    setBusyAction("refetch");
    try {
      const res = await refetchManifests(game.app_id);
      if (res?.ok) {
        notify("Refetched", "Updated manifests & keys");
        const fresh = await getAtomGame(game.app_id);
        if (fresh) setDetail(fresh);
      } else {
        notify("Refetch", res?.error || "Refetch failed");
      }
    } finally {
      setBusyAction(null);
    }
  };

  const handleUninstall = async () => {
    try {
      const preview = await previewAtomUninstall(game.app_id);
      showModal(
        <ConfirmModal
          strTitle={`Uninstall ${game.name}?`}
          strDescription={
            preview?.ok
              ? `Remove ${game.name} (App ID ${game.app_id}) from SLSsteam? Installed game files on disk will not be deleted.`
              : `Remove ${game.name} from SLSsteam?`
          }
          strOKButtonText="Uninstall"
          strCancelButtonText="Cancel"
          bDestructiveWarning={true}
          onOK={async () => {
            const res = await uninstallAtomGame(game.app_id);
            if (res?.ok) {
              notify("Uninstalled", `${game.name} removed from SLSsteam`);
              onGameUninstalled();
            } else {
              notify("Uninstall", res?.error || "Failed to uninstall");
            }
          }}
          onCancel={() => {}}
        />
      );
    } catch {
      notify("Uninstall", "Could not preview uninstall");
    }
  };

  const state = game.state ?? (game.installed ? "installed" : "added");
  const issues = game.issues ?? [];
  const attention = state === "added" || issues.length > 0;
  const stateText: Record<string, string> = {
    installed: game.size_on_disk ? formatBytes(game.size_on_disk) : "Installed",
    downloading: "Downloading in Steam",
    queued: "Queued in Steam",
    added: "Added · not downloaded",
  };
  const subtitle = issues.length > 0 ? `Incomplete · ${issues[0]}` : stateText[state];
  const hasUpdate = Boolean(updateInfo?.has_update);
  const busy = busyAction !== null;

  const actionButton = (key: string, icon: React.ReactNode, text: string, onClick: () => void, danger = false) => (
    <PanelSectionRow key={key}>
      <ButtonItem layout="below" onClick={onClick} disabled={busy}>
        <div className={`uran-game-action${danger ? " uran-game-action--danger" : ""}`}>
          {icon}
          <span>{text}</span>
        </div>
      </ButtonItem>
    </PanelSectionRow>
  );

  return (
    <>
      <PanelSectionRow>
        <Field
          label={
            <div className="uran-game-head">
              <span className="uran-game-name">{game.name}</span>
              {attention && (
                <span className="uran-game-attn">
                  <FaExclamationCircle size={12} />
                </span>
              )}
              {hasUpdate && <span className="uran-chip uran-chip--update">Update</span>}
              {detail?.slsonline && <span className="uran-chip">480</span>}
              {isExpanded ? <FaChevronUp size={11} /> : <FaChevronDown size={11} />}
            </div>
          }
          description={<span className={issues.length ? "uran-game-sub uran-game-sub--warn" : "uran-game-sub"}>{subtitle}</span>}
          onClick={onToggle}
          highlightOnFocus
        />
      </PanelSectionRow>

      {isExpanded && (
        <div className="uran-game-panel">
          <div className="uran-game-meta">
            <span>App {game.app_id}</span>
            {game.buildid && <span>Build {game.buildid}</span>}
            <span>{game.key_count} key{game.key_count === 1 ? "" : "s"}</span>
            {game.dlc_only && <span>DLC only</span>}
          </div>
          {issues.length > 0 && (
            <div className="uran-game-warn">
              {issues.join(" · ")}. Refetch writes it back from Hubcap; Remove clears what is left.
            </div>
          )}

          {loadingDetail ? (
            <PanelSectionRow>
              <Field label="Loading..." />
            </PanelSectionRow>
          ) : (
            <>
              <div className="uran-game-group">Online</div>
              <PanelSectionRow>
                <ToggleField
                  label="SLSonline"
                  description={detail?.global_slsonline ? "On for all games in Settings" : "Play online as Spacewar (480)"}
                  checked={detail?.slsonline ?? false}
                  disabled={busyAction === "slsonline" || detail?.global_slsonline}
                  onChange={handleToggleSlsOnline}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label="NetSock"
                  checked={detail?.netsock ?? false}
                  disabled={busyAction === "netsock"}
                  onChange={handleToggleNetsock}
                />
              </PanelSectionRow>
              {detail?.eos_available && (
                <PanelSectionRow>
                  <ToggleField
                    label="EOS proxy"
                    checked={detail?.eos === "manual" || detail?.eos === "auto"}
                    disabled={busyAction === "eos"}
                    onChange={handleToggleEos}
                  />
                </PanelSectionRow>
              )}

              <div className="uran-game-group">Manage</div>
              {state !== "installed" &&
                actionButton("steam", <FaSteam size={12} />, "Open in Steam Library", () =>
                  Navigation.Navigate(`/library/app/${game.app_id}`))}
              {actionButton("refetch", <FaRedo size={12} />,
                busyAction === "refetch" ? "Refetching..." : "Refetch keys & manifests", handleRefetch)}
              {actionButton("depots", <FaSlidersH size={12} />, "Manage depots", () => openAdvanced(game.app_id))}
              {actionButton("remove", <FaTrash size={12} />,
                state === "installed" ? "Uninstall" : "Remove from AT0-M", handleUninstall, true)}
            </>
          )}
        </div>
      )}
    </>
  );
};

const gameCardStyles = `
  .uran-game-head { display: flex; align-items: center; gap: 6px; width: 100%; }
  .uran-game-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .uran-game-attn { color: #ffb74d; flex-shrink: 0; }
  .uran-chip { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 8px;
    background: rgba(126, 226, 168, 0.15); color: #7ee2a8; flex-shrink: 0; }
  .uran-chip--update { background: rgba(255, 183, 77, 0.15); color: #ffb74d; }
  .uran-game-sub { font-size: 12px; color: #8ba5b8; }
  .uran-game-sub--warn { color: #ffb74d; }
  .uran-game-panel { margin: 0 4px 8px 4px; padding: 6px 4px 4px 4px; border-radius: 8px;
    background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.07); }
  .uran-game-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; padding: 2px 10px 6px 10px;
    font-size: 11px; color: #8ba5b8; }
  .uran-game-warn { margin: 0 8px 6px 8px; padding: 6px 8px; border-radius: 6px; font-size: 11px;
    line-height: 1.35; color: #ffcc80; background: rgba(255, 183, 77, 0.10); }
  .uran-game-group { padding: 6px 10px 0 10px; font-size: 10px; font-weight: 700; letter-spacing: 0.08em;
    text-transform: uppercase; color: rgba(255, 255, 255, 0.45); }
  .uran-game-action { display: flex; align-items: center; justify-content: center; gap: 6px; }
  .uran-game-action--danger { color: #ff9a9a; }
`;

export const GamesTab: React.FC = () => {
  const [games, setGames] = useState<AtomGame[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterQuery, setFilterQuery] = useState("");
  const [expandedAppId, setExpandedAppId] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Record<string, AtomUpdate>>({});
  const [checkingUpdates, setCheckingUpdates] = useState(false);

  const loadGames = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAtomGames();
      const arr = res?.games ?? [];
      setGames(arr);
      syncAddedAppIds().catch(() => {});
    } catch {
      setGames([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGames();
  }, [loadGames]);

  const handleCheckUpdates = async () => {
    setCheckingUpdates(true);
    try {
      const res = await checkAllAtomUpdates();
      if (res?.ok && res.updates) {
        setUpdates(res.updates);
        const count = res.update_count ?? 0;
        notify("Updates Check", count > 0 ? `${count} update(s) available` : "All games up to date");
      } else {
        notify("Updates Check", res?.error || "Could not check updates");
      }
    } finally {
      setCheckingUpdates(false);
    }
  };

  const filteredGames = useMemo(() => {
    const q = filterQuery.trim().toLowerCase();
    if (!q) return games;
    return games.filter((g) => g.name.toLowerCase().includes(q) || g.app_id.includes(q));
  }, [games, filterQuery]);

  return (
    <>
      <style>{gameCardStyles}</style>
      <PanelSection title={`AT0-M Games (${games.length})`}>
        {games.length > 5 && (
          <PanelSectionRow>
            <TextField
              label="Filter games"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              placeholder="Filter by name or App ID..."
            />
          </PanelSectionRow>
        )}

        {games.length > 0 && (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              onClick={handleCheckUpdates}
              disabled={checkingUpdates || loading}
            >
              {checkingUpdates ? "Checking Updates..." : "Check All Updates"}
            </ButtonItem>
          </PanelSectionRow>
        )}

        {loading && games.length === 0 ? (
          <PanelSectionRow>
            <Field label="Loading library..." />
          </PanelSectionRow>
        ) : filteredGames.length === 0 ? (
          <PanelSectionRow>
            <Field
              label={games.length === 0 ? "No games configured" : "No matching games"}
              description={
                games.length === 0
                  ? "Use the Search tab or Steam Store to inject games."
                  : "Try a different filter query."
              }
            />
          </PanelSectionRow>
        ) : (
          filteredGames.map((game) => (
            <GameAccordionItem
              key={game.app_id}
              game={game}
              isExpanded={expandedAppId === game.app_id}
              onToggle={() =>
                setExpandedAppId((cur) => (cur === game.app_id ? null : game.app_id))
              }
              onGameUninstalled={() => {
                setExpandedAppId(null);
                loadGames();
              }}
              updateInfo={updates[game.app_id]}
            />
          ))
        )}
      </PanelSection>
    </>
  );
};
