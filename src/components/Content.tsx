import React, { useState, useEffect, useRef, useCallback, type ReactNode, type FocusEvent } from "react";
import { Tabs, Router } from "@decky/ui";
import { FaGamepad, FaSteam, FaSearch, FaTools } from "react-icons/fa";
import { listAtomGames, type AtomGame } from "../api";
import { tabStyles } from "../styles";
import { GamesTab } from "../tabs/GamesTab";
import { SearchTab } from "../tabs/SearchTab";
import { SettingsTab } from "../tabs/SettingsTab";
import { NowPlayingTab } from "../tabs/NowPlayingTab";

const tabIcons = {
  nowPlaying: <FaGamepad size={18} />,
  games: <FaSteam size={18} />,
  search: <FaSearch size={18} />,
  settings: <FaTools size={18} />,
};

export const Content: React.FC = () => {
  const [tab, setTab] = useState("Search");
  const [setupComplete, setSetupComplete] = useState(true);
  const [contentFocused, setContentFocused] = useState(false);
  const [games, setGames] = useState<AtomGame[]>([]);
  const [runningAppId, setRunningAppId] = useState<string | null>(null);
  const previousRunningAppId = useRef<string | null>(null);

  const reloadGames = useCallback(async () => {
    try {
      const res = await listAtomGames();
      setGames(res?.games ?? []);
    } catch {
      setGames([]);
    }
  }, []);

  useEffect(() => {
    reloadGames();
  }, [reloadGames]);

  // Poll for currently running app via Decky's Router
  useEffect(() => {
    const poll = () => {
      try {
        const app = (Router as any).MainRunningApp;
        const currentAppId = app?.appid ? String(app.appid) : null;
        setRunningAppId(currentAppId);
      } catch {
        setRunningAppId(null);
      }
    };
    poll();
    const interval = window.setInterval(poll, 2000);
    return () => window.clearInterval(interval);
  }, []);

  const nowPlayingGame = games.find((g) => g.app_id === runningAppId) || null;

  // Auto-switch to NowPlaying if a managed game launches
  useEffect(() => {
    const previous = previousRunningAppId.current;
    previousRunningAppId.current = runningAppId;
    if (runningAppId && runningAppId !== previous && nowPlayingGame) {
      setTab("NowPlaying");
    } else if (!runningAppId && previous && tab === "NowPlaying") {
      setTab("Search");
    }
  }, [runningAppId, nowPlayingGame, tab]);

  const handleFocusCapture = (event: FocusEvent<HTMLDivElement>) => {
    const focusedElement = event.target as HTMLElement | null;
    setContentFocused(!focusedElement?.closest?.('[role="tab"]'));
  };

  const tabContent = (content: ReactNode) => (
    <div className="uran-tab-content">{content}</div>
  );

  const tabs = [
    ...(nowPlayingGame
      ? [
          {
            id: "NowPlaying",
            title: tabIcons.nowPlaying,
            content: tabContent(<NowPlayingTab game={nowPlayingGame} onRefresh={reloadGames} />),
          },
        ]
      : []),
    {
      id: "Search",
      title: tabIcons.search,
      content: tabContent(<SearchTab />),
    },
    {
      id: "Games",
      title: tabIcons.games,
      content: tabContent(<GamesTab />),
    },
    {
      id: "Settings",
      title: tabIcons.settings,
      content: tabContent(<SettingsTab onSetupStatusChange={setSetupComplete} />),
    },
  ];

  const availableTabIds = new Set(tabs.map(({ id }) => id));
  const activeTab = availableTabIds.has(tab) ? tab : "Search";

  return (
    <div
      className={`uran-tabs${contentFocused ? " uran-tabs--content-focused" : ""}`}
      style={{
        height: "95%",
        width: "300px",
        position: "fixed",
        marginTop: "-12px",
        overflow: "hidden",
      }}
      onFocusCapture={handleFocusCapture}
    >
      <style>{tabStyles}</style>
      <Tabs
        activeTab={activeTab}
        onShowTab={(nextTab: string) => {
          if (availableTabIds.has(nextTab)) setTab(nextTab);
        }}
        tabs={tabs}
      />
    </div>
  );
};
