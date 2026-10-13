import React from "react";
import { Focusable } from "@decky/ui";
import { definePlugin } from "@decky/api";
import { refreshNotificationChannel, setNotificationMode } from "./notify";
import { getSetting } from "./api";
import { initStorePatch } from "./StorePatch";
import { initContextMenuPatch } from "./LibraryPatch";
import { AssellaLogo } from "./components/icons";
import { SearchTab } from "./tabs/SearchTab";
import { AtomGamesTab } from "./tabs/AtomGamesTab";
import { SettingsTab } from "./tabs/SettingsTab";

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
        </Focusable>

        {activeTab === "search" && <SearchTab />}
        {activeTab === "atom" && <AtomGamesTab />}
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
