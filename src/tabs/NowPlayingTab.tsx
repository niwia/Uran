import React, { useEffect, useState, useCallback } from "react";
import {
  PanelSection,
  PanelSectionRow,
  Field,
  ToggleField,
  ButtonItem,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import {
  getAtomGame,
  setSlsonline,
  setNetsock,
  setEos,
  refetchManifests,
  previewAtomUninstall,
  uninstallAtomGame,
  type AtomDetail,
  type AtomGame,
} from "../api";
import { notify } from "../notify";
import { openAdvanced } from "../pages/AdvancedPage";

interface NowPlayingTabProps {
  game: AtomGame;
  onRefresh?: () => void;
}

export const NowPlayingTab: React.FC<NowPlayingTabProps> = ({ game, onRefresh }) => {
  const [detail, setDetail] = useState<AtomDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const loadDetail = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAtomGame(game.app_id);
      if (data) setDetail(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [game.app_id]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const handleToggleSlsOnline = async (enabled: boolean) => {
    if (!detail) return;
    setBusyAction("slsonline");
    try {
      const res = await setSlsonline(game.app_id, enabled, "480");
      if (res?.ok) {
        setDetail({ ...detail, slsonline: enabled });
        notify("SLS Online", enabled ? "Enabled (0: 480)" : "Disabled");
        onRefresh?.();
      } else {
        notify("SLS Online", res?.error || "Failed to change SLS Online");
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
        notify("NetSock Intercept", enabled ? "Enabled" : "Disabled");
        onRefresh?.();
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
        notify("EOS Intercept", enabled ? "Enabled" : "Disabled");
        onRefresh?.();
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
        loadDetail();
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
              ? `Remove ${game.name} (${game.app_id}) from SLSsteam? Installed game files on disk will not be deleted.`
              : `Uninstall ${game.name}?`
          }
          strOKButtonText="Uninstall"
          strCancelButtonText="Cancel"
          bDestructiveWarning={true}
          onOK={async () => {
            const res = await uninstallAtomGame(game.app_id);
            if (res?.ok) {
              notify("Uninstalled", `${game.name} removed from SLSsteam`);
              onRefresh?.();
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

  return (
    <>
      <PanelSection title="Now Playing">
        <PanelSectionRow>
          <Field
            label={game.name}
            description={`App ID ${game.app_id} · Running`}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Quick Settings">
        <PanelSectionRow>
          <ToggleField
            label="SLS Online (0: 480)"
            description={detail?.sls_config_ready ? "Use AppID 480 for Steam networking" : detail?.sls_config_error || "SLSsteam config unavailable"}
            checked={detail?.slsonline ?? false}
            disabled={loading || busyAction === "slsonline" || !detail?.sls_config_ready || detail?.global_slsonline}
            onChange={handleToggleSlsOnline}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="NetSock Intercept"
            checked={detail?.netsock ?? false}
            disabled={loading || busyAction === "netsock" || !detail?.sls_config_ready}
            onChange={handleToggleNetsock}
          />
        </PanelSectionRow>
        {detail?.eos_available && (
          <PanelSectionRow>
            <ToggleField
              label="EOS Intercept"
              checked={detail?.eos === "manual" || detail?.eos === "auto"}
              disabled={loading || busyAction === "eos"}
              onChange={handleToggleEos}
            />
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Actions">
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleRefetch}
            disabled={busyAction === "refetch"}
          >
            {busyAction === "refetch" ? "Refetching..." : "Refetch Manifests & Keys"}
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={() => openAdvanced(game.app_id)}
          >
            Manage Depots & DLCs
          </ButtonItem>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            onClick={handleUninstall}
            disabled={busyAction !== null}
          >
            Uninstall Game
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
};
