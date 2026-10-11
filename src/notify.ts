/**
 * notify.ts — Single entry point for user-facing notifications in Uran.
 *
 * The `notification_mode` setting picks the channel:
 *   auto    -> Steam toasts in Gaming Mode, notify-send in Desktop Mode
 *   steam   -> Decky toast inside the Steam UI
 *   desktop -> notify-send via the backend
 *   none    -> dropped
 */
import { callable, toaster } from "@decky/api";

export type NotificationMode = "auto" | "steam" | "desktop" | "none";
export type NotificationChannel = "steam" | "desktop" | "none";

export const NOTIFICATION_MODE_OPTIONS: {
  data: NotificationMode;
  label: string;
}[] = [
  { data: "auto", label: "Automatic" },
  { data: "steam", label: "Steam toasts" },
  { data: "desktop", label: "Desktop (notify-send)" },
  { data: "none", label: "None" },
];

const DEFAULT_MODE: NotificationMode = "auto";

const sendDesktopNotification = callable<
  [title: string, body: string],
  { ok?: boolean; error?: string }
>("send_notification");

const fetchNotificationChannel = callable<
  [gaming_ui: boolean | null],
  {
    ok?: boolean;
    channel?: string;
    gaming_mode?: boolean;
    notify_send?: boolean;
    error?: string;
  }
>("get_notification_channel");

let mode: NotificationMode = DEFAULT_MODE;
let channel: NotificationChannel = "steam";
let notifySendAvailable = true;

/**
 * Steam's own "gamepad UI is the active window" flag: true in Gaming Mode / Big Picture, false in desktop.
 */
function steamGamepadUI(): boolean | null {
  try {
    const store = (window as any).SteamUIStore;
    const fn = store?.IsGamepadUIWindowActive;
    if (typeof fn === "function") return !!fn.call(store);
  } catch {}
  return null;
}

function resolveAuto(): NotificationChannel {
  const flag = steamGamepadUI();
  if (flag === null) return channel;
  if (flag) return "steam";
  return notifySendAvailable ? "desktop" : "steam";
}

export function setNotificationMode(value: unknown): void {
  mode =
    value === "auto" ||
    value === "steam" ||
    value === "desktop" ||
    value === "none"
      ? value
      : DEFAULT_MODE;
}

export function getNotificationMode(): NotificationMode {
  return mode;
}

export function getNotificationChannel(): NotificationChannel {
  return mode === "auto" ? resolveAuto() : channel;
}

/** Ask the backend which channel the current mode resolves to. */
export async function refreshNotificationChannel(): Promise<NotificationChannel> {
  try {
    const r = await fetchNotificationChannel(steamGamepadUI());
    notifySendAvailable = r?.notify_send !== false;
    channel =
      r?.channel === "steam" || r?.channel === "desktop" || r?.channel === "none"
        ? r.channel
        : "steam";
  } catch {
    channel = "steam";
  }
  return getNotificationChannel();
}

function toast(title: string, body: string): void {
  toaster.toast({ title, body, duration: 5000 });
}

export function notify(title: string, body: string): void {
  const effective = getNotificationChannel();
  if (effective === "none") return;
  if (effective !== "desktop") {
    toast(title, body);
    return;
  }
  sendDesktopNotification(title, body)
    .then((r) => {
      if (r && r.ok === false) toast(title, body);
    })
    .catch(() => toast(title, body));
}

/** Notification body for a finished background inject job. */
export function injectFinishedText(
  name: string,
  job?: {
    error?: string;
    keys_missing?: string[];
    depot_keys?: string[];
    manifests?: string[];
    manifest_error?: string;
  } | null,
): string {
  if (job?.error) {
    return `Injection error for ${name}: ${job.error}`;
  }
  if (job?.manifest_error) {
    return `Injected ${name} (Manifest notice: ${job.manifest_error})`;
  }
  if (job?.keys_missing && job.keys_missing.length > 0) {
    return `Injected ${name} (${job.keys_missing.length} unkeyed depot(s))`;
  }
  return `Successfully injected ${name} into SLSsteam`;
}
