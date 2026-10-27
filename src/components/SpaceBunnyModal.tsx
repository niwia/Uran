import { ConfirmModal, DropdownItem, showModal, TextField, ToggleField } from "@decky/ui";
import React, { useEffect, useState } from "react";
import {
  getSpaceBunnyConfig,
  saveSpaceBunnyConfig,
  SpaceBunnyConfig,
  SpaceBunnyHubcapConfig,
} from "../api";
import { notify } from "../notify";

export interface SpaceBunnyModalProps {
  closeModal?: () => void;
  onSaved?: () => void;
}

const TIMEOUT_OPTIONS = [
  { data: 3, label: "3 seconds" },
  { data: 5, label: "5 seconds (Default)" },
  { data: 10, label: "10 seconds" },
  { data: 15, label: "15 seconds" },
];

const PREFLIGHT_OPTIONS = [
  { data: "contents", label: "Contents (Only if depots missing)" },
  { data: "all", label: "All (Always verify manifest)" },
  { data: "none", label: "None (Skip preflight)" },
];

export const SpaceBunnyModalBody: React.FC<{
  closeModal?: () => void;
  onSaved?: () => void;
}> = ({ closeModal, onSaved }) => {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [confPath, setConfPath] = useState("");
  const [exists, setExists] = useState(false);

  // Form state
  const [standalone, setStandalone] = useState(false);
  const [hubcapEnabled, setHubcapEnabled] = useState(true);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyTimestamp, setApiKeyTimestamp] = useState<number>(0);
  const [timeoutSec, setTimeoutSec] = useState<number>(5);
  const [writeConfig, setWriteConfig] = useState(true);
  const [notifications, setNotifications] = useState(true);
  const [preflight, setPreflight] = useState("contents");
  const [depotIndex, setDepotIndex] = useState(false);
  const [depotComments, setDepotComments] = useState(false);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const res = await getSpaceBunnyConfig();
        if (!alive || !res?.ok || !res.config) return;
        const cfg: SpaceBunnyConfig = res.config;
        setConfPath(cfg.path || "");
        setExists(Boolean(cfg.exists));
        setStandalone(Boolean(cfg.standalone));

        const hub = cfg.hubcap || ({} as Partial<SpaceBunnyHubcapConfig>);
        setHubcapEnabled(hub.enabled ?? true);
        setApiKey(hub.api_key || "");
        setApiKeyTimestamp(hub.api_key_timestamp || 0);
        setTimeoutSec(hub.timeout_sec || 5);
        setWriteConfig(hub.write_config ?? true);
        setNotifications(hub.notify ?? true);
        setPreflight(hub.preflight || "contents");
        setDepotIndex(Boolean(hub.depot_index));
        setDepotComments(Boolean(hub.write_depot_comments));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await saveSpaceBunnyConfig({
        standalone,
        hubcap: {
          enabled: hubcapEnabled,
          api_key: apiKey,
          api_key_timestamp: apiKeyTimestamp,
          timeout_sec: timeoutSec,
          write_config: writeConfig,
          notify: notifications,
          preflight,
          depot_index: depotIndex,
          write_depot_comments: depotComments,
        },
      });
      if (res?.ok) {
        notify("Uran", "SpaceBunny configuration saved");
        onSaved?.();
        closeModal?.();
      } else {
        notify("Uran", res?.error || "Failed saving SpaceBunny configuration");
      }
    } catch (err: any) {
      notify("Uran", err?.message || "Error saving configuration");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "20px", textAlign: "center", opacity: 0.7, fontSize: "12px" }}>
        Loading SpaceBunny configuration...
      </div>
    );
  }

  const formatTimestamp = (ts: number): string => {
    if (!ts) return "No timestamp";
    const s = String(ts);
    if (s.length === 10) {
      // mmhhddyyyy format (minutes, hour, day, year)
      const min = s.slice(0, 2);
      const hr = s.slice(2, 4);
      const day = s.slice(4, 6);
      const yr = s.slice(6, 10);
      return `${yr}-${day} ${hr}:${min} (Internal: ${ts})`;
    }
    return String(ts);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "14px", padding: "4px 0", maxHeight: "65vh", overflowY: "auto" }}>
      {/* Header Info Banner */}
      <div
        style={{
          background: "rgba(255, 255, 255, 0.04)",
          border: "1px solid rgba(255, 255, 255, 0.08)",
          borderRadius: "8px",
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          fontSize: "11px",
          lineHeight: "1.4",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ opacity: 0.65 }}>Bridge Status:</span>
          <span style={{ fontWeight: 600, color: exists ? "#7ee2a8" : "#e5a93c" }}>
            {exists ? "Bridge Active (spacebunny.conf.lua)" : "Initial File (Will Be Created)"}
          </span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ opacity: 0.65 }}>Key Timestamp:</span>
          <span style={{ fontWeight: 500, fontFamily: "monospace" }}>
            {formatTimestamp(apiKeyTimestamp)}
          </span>
        </div>
        {confPath ? (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ opacity: 0.65 }}>File Path:</span>
            <span style={{ opacity: 0.85, fontSize: "10px", wordBreak: "break-all", textAlign: "right" }}>
              {confPath}
            </span>
          </div>
        ) : null}
      </div>

      {/* Standalone Option */}
      <ToggleField
        label="Standalone Mode"
        description="Run SpaceBunny without external network intercepts or dependencies."
        checked={standalone}
        onChange={(v) => setStandalone(v)}
      />

      {/* Hubcap Auto-Fetch Options */}
      <div style={{ borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "12px" }}>
        <ToggleField
          label="Hubcap Auto-Fetch"
          description="Automatically retrieve missing depot decryption keys via Hubcap API."
          checked={hubcapEnabled}
          onChange={(v) => setHubcapEnabled(v)}
        />
      </div>

      {hubcapEnabled ? (
        <>
          <TextField
            label="Hubcap API Key"
            value={apiKey}
            onChange={(e: any) => setApiKey(e.target.value)}
          />

          <DropdownItem
            label="Request Timeout"
            description="Maximum duration to wait for Hubcap API responses."
            rgOptions={TIMEOUT_OPTIONS}
            selectedOption={timeoutSec}
            onChange={(opt: any) => {
              const val = opt?.data ?? opt;
              setTimeoutSec(Number(val));
            }}
          />

          <DropdownItem
            label="Preflight Verification"
            description="Strategy used to verify required depot contents before dispatch."
            rgOptions={PREFLIGHT_OPTIONS}
            selectedOption={preflight}
            onChange={(opt: any) => {
              const val = opt?.data ?? opt;
              setPreflight(String(val));
            }}
          />

          <ToggleField
            label="Auto-Write to config.yaml"
            description="Automatically write newly fetched decryption keys into SLSsteam configuration."
            checked={writeConfig}
            onChange={(v) => setWriteConfig(v)}
          />

          <ToggleField
            label="In-Game Notifications"
            description="Display notification banner when keys are successfully fetched."
            checked={notifications}
            onChange={(v) => setNotifications(v)}
          />

          <ToggleField
            label="Write Depot Comments"
            description="Include depot and game titles as comments next to keys in config.yaml."
            checked={depotComments}
            onChange={(v) => setDepotComments(v)}
          />

          <ToggleField
            label="Depot Indexing"
            description="Enable depot indexing for advanced multi-manifest resolutions."
            checked={depotIndex}
            onChange={(v) => setDepotIndex(v)}
          />
        </>
      ) : null}

      <div style={{ marginTop: "10px", display: "flex", justifyContent: "flex-end" }}>
        <button
          onClick={handleSave}
          disabled={saving}
          style={{
            background: "#1a9fff",
            color: "#ffffff",
            border: "none",
            borderRadius: "6px",
            padding: "8px 18px",
            fontSize: "12px",
            fontWeight: 600,
            cursor: saving ? "not-allowed" : "pointer",
            opacity: saving ? 0.7 : 1,
          }}
        >
          {saving ? "Saving..." : "Save and Apply"}
        </button>
      </div>
    </div>
  );
};

export const showSpaceBunnyModal = (onSaved?: () => void): void => {
  let modalInstance: ReturnType<typeof showModal>;
  modalInstance = showModal(
    <ConfirmModal
      strTitle="SpaceBunny Configuration"
      strOKButtonText="Close"
      bOKDisabled={false}
      onOK={() => modalInstance.Close()}
      onCancel={() => modalInstance.Close()}
    >
      <SpaceBunnyModalBody
        closeModal={() => modalInstance.Close()}
        onSaved={onSaved}
      />
    </ConfirmModal>,
    undefined,
    { bNeverPopOut: true },
  );
};
