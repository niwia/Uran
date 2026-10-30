import React from "react";
import { staticClasses } from "@decky/ui";
import { definePlugin, routerHook } from "@decky/api";
import { refreshNotificationChannel, setNotificationMode } from "./notify";
import { getSetting } from "./api";
import { initStorePatch } from "./StorePatch";
import { initContextMenuPatch } from "./LibraryPatch";
import { AssellaLogo } from "./components/icons";
import { Content } from "./components/Content";
import { AdvancedPage } from "./pages/AdvancedPage";

export default definePlugin(() => {
  const storePatchCleanup = initStorePatch();
  const contextMenuCleanup = initContextMenuPatch();

  // Full-screen Advanced window (opened from Manage Depots & DLCs button)
  routerHook.addRoute("/uran/advanced", () => <AdvancedPage />);

  getSetting("notification_mode", "auto")
    .then((v) => {
      setNotificationMode(v);
      return refreshNotificationChannel();
    })
    .catch(() => {});

  return {
    name: "ASSella",
    titleView: <div className={staticClasses.Title}>ASSella</div>,
    alwaysRender: true,
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
