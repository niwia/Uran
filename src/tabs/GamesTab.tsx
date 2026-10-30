import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  PanelSection,
  PanelSectionRow,
  Field,
  ToggleField,
  ButtonItem,
  TextField,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { FaChevronDown, FaChevronUp, FaRedo, FaTrash, FaExternalLinkAlt } from "react-icons/fa";
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

  const sizeText = game.size_on_disk ? ` · ${formatBytes(game.size_on_disk)}` : "";
  const updateBadge = updateInfo?.has_update ? " [Update Available]" : "";

  return (
    <>
      <PanelSectionRow>
        <Field
          label={
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1, marginRight: "8px" }}>
                {game.name}
              </span>
              <span style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "#8ba5b8", flexShrink: 0 }}>
                {detail?.slsonline && (
                  <span style={{ color: "#7ee2a8", fontWeight: "bold" }}>480</span>
                )}
                {isExpanded ? <FaChevronUp size={12} /> : <FaChevronDown size={12} />}
              </span>
            </div>
          }
          description={`App ID ${game.app_id}${sizeText}${updateBadge}`}
          onClick={onToggle}
          highlightOnFocus
        />
      </PanelSectionRow>

      {isExpanded && (
        <div className="uran-accordion-body">
          {loadingDetail ? (
            <PanelSectionRow>
              <Field label="Loading details..." />
            </PanelSectionRow>
          ) : (
            <>
              <PanelSectionRow>
                <ToggleField
                  label="SLS Online (0: 480)"
                  description="Redirect multiplayer to App ID 480"
                  checked={detail?.slsonline ?? false}
                  disabled={busyAction === "slsonline" || detail?.global_slsonline}
                  onChange={handleToggleSlsOnline}
                />
              </PanelSectionRow>

              <PanelSectionRow>
                <ToggleField
                  label="NetSock Intercept"
                  checked={detail?.netsock ?? false}
                  disabled={busyAction === "netsock"}
                  onChange={handleToggleNetsock}
                />
              </PanelSectionRow>

              {detail?.eos_available && (
                <PanelSectionRow>
                  <ToggleField
                    label="EOS Intercept"
                    checked={detail?.eos === "manual" || detail?.eos === "auto"}
                    disabled={busyAction === "eos"}
                    onChange={handleToggleEos}
                  />
                </PanelSectionRow>
              )}

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={handleRefetch}
                  disabled={busyAction === "refetch"}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                    <FaRedo size={12} />
                    <span>{busyAction === "refetch" ? "Refetching..." : "Refetch Manifests"}</span>
                  </div>
                </ButtonItem>
              </PanelSectionRow>

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() => openAdvanced(game.app_id)}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                    <FaExternalLinkAlt size={12} />
                    <span>Manage Depots & DLCs</span>
                  </div>
                </ButtonItem>
              </PanelSectionRow>

              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={handleUninstall}
                  disabled={busyAction !== null}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}>
                    <FaTrash size={12} />
                    <span>Uninstall Game</span>
                  </div>
                </ButtonItem>
              </PanelSectionRow>
            </>
          )}
        </div>
      )}
    </>
  );
};

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
      <PanelSection title={`Installed Games (${games.length})`}>
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
