import React from "react";
import {
  PanelSection,
  PanelSectionRow,
  TextField,
  ButtonItem,
  DialogButton,
  ConfirmModal,
  showModal,
} from "@decky/ui";
import { injectFinishedText, notify } from "../notify";
import {
  getRecentInjects,
  searchGames,
  injectGame,
  getInjectStatus,
  SearchResult,
  RecentInject,
} from "../api";
import { addedAppIds, pendingAppIds } from "../StorePatch";

export const SearchTab: React.FC = () => {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<SearchResult[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const [recent, setRecent] = React.useState<RecentInject[]>([]);
  const [, bumpVersion] = React.useReducer((n: number) => n + 1, 0);

  const loadRecent = async () => {
    try {
      const r = await getRecentInjects();
      setRecent(r ?? []);
    } catch {}
  };

  React.useEffect(() => {
    loadRecent();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") void loadRecent();
    }, 5000);
    return () => clearInterval(t);
  }, []);

  const searchSeq = React.useRef(0);

  const runSearch = async (raw: string) => {
    const q = raw.trim();
    const isAppId = /^\d+$/.test(q);
    const minLen = isAppId ? 1 : 3;
    if (q.length < minLen) return;
    const seq = ++searchSeq.current;
    setSearching(true);
    setMsg("");
    try {
      const r = await searchGames(q, 20, isAppId);
      if (seq !== searchSeq.current) return;
      if (r?.error) {
        setMsg(r.error);
        setResults([]);
      } else {
        const res = r?.results ?? [];
        setResults(res);
        setMsg(
          res.length === 0
            ? "No results found"
            : `${res.length} result${res.length !== 1 ? "s" : ""}`,
        );
      }
    } catch (e: any) {
      if (seq !== searchSeq.current) return;
      setMsg(`Search error: ${e}`);
      setResults([]);
    } finally {
      if (seq === searchSeq.current) setSearching(false);
    }
  };

  React.useEffect(() => {
    const isAppId = /^\d+$/.test(query.trim());
    const minLen = isAppId ? 1 : 3;
    if (query.trim().length < minLen) {
      setResults([]);
      setMsg("");
      setSearching(false);
      return;
    }
    const t = setTimeout(() => void runSearch(query), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const doInject = async (appId: string, title: string, force: boolean = false) => {
    if (addedAppIds.has(appId) && !force) {
      showModal(
        <ConfirmModal
          onOK={() => void doInject(appId, title, true)}
          onCancel={() => {}}
          bOKDisabled={false}
          strTitle="Already in Library"
          strDescription={`${title} (${appId}) is already registered in your library. Would you like to re-inject and refresh its manifests?`}
          strOKButtonText="Re-inject"
          strCancelButtonText="Cancel"
        />,
        undefined,
        { bNeverPopOut: true },
      );
      return;
    }
    pendingAppIds.add(appId);
    bumpVersion();
    setMsg(`Adding ${title} to SLS...`);
    try {
      const r = await injectGame(appId);
      if ((r as any)?.already_added && !force) {
        pendingAppIds.delete(appId);
        addedAppIds.add(appId);
        bumpVersion();
        showModal(
          <ConfirmModal
            onOK={() => void doInject(appId, title, true)}
            onCancel={() => {}}
            bOKDisabled={false}
            strTitle="Already in Library"
            strDescription={`${title} (${appId}) is already registered in your library. Would you like to re-inject and refresh its manifests?`}
            strOKButtonText="Re-inject"
            strCancelButtonText="Cancel"
          />,
          undefined,
          { bNeverPopOut: true },
        );
        return;
      }
      if (r && !r.error) {
        const name = r.name ?? title;
        const toastMsg = `Added ${name} to SLS`;
        notify("Uran", toastMsg);
        setMsg(toastMsg);

        const startedAt = Date.now();
        const MAX_WAIT_MS = 300000;
        const timer = setInterval(async () => {
          try {
            const job = await getInjectStatus(appId);
            if (job?.done) {
              clearInterval(timer);
              pendingAppIds.delete(appId);
              addedAppIds.add(appId);
              bumpVersion();
              notify("Uran", injectFinishedText(name, job));
            } else if (Date.now() - startedAt > MAX_WAIT_MS) {
              clearInterval(timer);
              pendingAppIds.delete(appId);
              addedAppIds.add(appId);
              bumpVersion();
              notify("Uran", `Background work for ${name} timed out`);
            }
          } catch {
            // keep polling
          }
        }, 2000);
      } else {
        pendingAppIds.delete(appId);
        bumpVersion();
        const err = r?.error || "Unknown error";
        notify("Uran", err);
        setMsg(err);
      }
    } catch (e: any) {
      pendingAppIds.delete(appId);
      bumpVersion();
      notify("Uran", `Error: ${e}`);
      setMsg(`Error: ${e}`);
    }
  };

  const isAppIdInput = /^\d+$/.test(query.trim());

  return (
    <>
      <PanelSection title="Search Games">
        <PanelSectionRow>
          <TextField
            label="Game Name or App ID"
            value={query}
            onChange={(e: any) => setQuery(e.target.value)}
            onSubmit={() => void runSearch(query)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={
              searching || query.trim().length < (isAppIdInput ? 1 : 3)
            }
            onClick={() => void runSearch(query)}
          >
            {searching ? "Searching..." : isAppIdInput ? "Search App ID" : "Search Games"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>

      {msg && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", opacity: 0.8, padding: "8px" }}>
            {msg}
          </div>
        </PanelSectionRow>
      )}

      {results.length > 0 && (
        <PanelSection title={`Results (${results.length})`}>
          {results.map((item) => {
            const isAdded = addedAppIds.has(item.app_id);
            const isPending = pendingAppIds.has(item.app_id);
            return (
              <PanelSectionRow key={item.app_id}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    width: "100%",
                    gap: "8px",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      overflow: "hidden",
                      flex: 1,
                    }}
                  >
                    <span
                      style={{
                        fontSize: "13px",
                        fontWeight: 600,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {item.title}
                    </span>
                    <span style={{ fontSize: "11px", opacity: 0.6 }}>
                      App ID: {item.app_id}
                    </span>
                  </div>
                  <div style={{ flexShrink: 0 }}>
                    <DialogButton
                      style={{
                        height: "28px",
                        minWidth: "75px",
                        padding: "0 10px",
                        fontSize: "12px",
                      }}
                      disabled={isPending}
                      onClick={() => doInject(item.app_id, item.title)}
                    >
                      {isAdded ? "In Library" : isPending ? "Adding..." : "Add"}
                    </DialogButton>
                  </div>
                </div>
              </PanelSectionRow>
            );
          })}
        </PanelSection>
      )}

      {recent.length > 0 && (
        <PanelSection title="Recent Activity">
          {recent.slice(0, 5).map((r) => (
            <PanelSectionRow key={r.app_id}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  width: "100%",
                  fontSize: "12px",
                }}
              >
                <span
                  style={{
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: "70%",
                  }}
                >
                  {r.name || r.app_id}
                </span>
                <span
                  style={{
                    fontSize: "11px",
                    color: r.error
                      ? "#e57373"
                      : r.done
                      ? "#81c784"
                      : "#ffb74d",
                  }}
                >
                  {r.error ? "Failed" : r.done ? "Done" : "Working..."}
                </span>
              </div>
            </PanelSectionRow>
          ))}
        </PanelSection>
      )}
    </>
  );
};

