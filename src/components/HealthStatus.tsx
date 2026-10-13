import React from "react";
import { PanelSectionRow } from "@decky/ui";
import { getHealthStatus, once, HealthStatus as Health } from "../api";

/** Compact read-only health line, shared by the Search and Settings tabs. */
export const HealthStatusRow: React.FC = () => {
  const [health, setHealth] = React.useState<Health | null>(null);

  React.useEffect(() => {
    let alive = true;
    // Session-once: both tabs share one fetch, first visible mount wins.
    void once("health", getHealthStatus)
      .then((h) => {
        if (alive && h) setHealth(h);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  if (!health) return null;

  const plugins = health.plugins;
  const sls = health.sls;
  const names = plugins?.plugins ?? [];

  const pluginText = !plugins
    ? "Plugins: unknown"
    : names.length > 0
      ? `Plugins (${names.length}): ${names.join(", ")}${plugins.plugins_enabled ? "" : " (disabled in config)"}`
      : "Plugins: none found";
  const pluginColor = names.length > 0 ? "#7ee2a8" : "#ff9a9a";

  let slsText = "SLS: unknown";
  let slsColor = "#9aa4b2";
  if (sls) {
    if (sls.status === "up_to_date") {
      slsText = sls.release_tag ? `SLS ${sls.release_tag}: up to date` : "SLS: up to date";
      slsColor = "#7ee2a8";
    } else if (sls.status === "outdated") {
      slsText = sls.release_tag ? `SLS update available (${sls.release_tag})` : "SLS update available";
      slsColor = "#f0c674";
    } else if (sls.status === "no_local") {
      slsText = "SLS not installed";
    }
  }

  return (
    <PanelSectionRow>
      <div style={{ fontSize: "11px", lineHeight: 1.7, width: "100%", opacity: 0.9 }}>
        <div>
          <span style={{ color: pluginColor }}>● </span>
          {pluginText}
        </div>
        <div>
          <span style={{ color: slsColor }}>● </span>
          {slsText}
        </div>
      </div>
    </PanelSectionRow>
  );
};
