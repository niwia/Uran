export const formatBytes = (n: number): string => {
  if (!n) return "";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${u[i]}`;
};

export function formatExpiry(raw?: string): string {
  if (!raw) return "—";
  try {
    const datePart = raw.split(" ")[0].split("T")[0];
    const parts = datePart.split("-");
    if (parts.length === 3) {
      const yy = parts[0].length === 4 ? parts[0].slice(2) : parts[0];
      return `${parts[2]}/${parts[1]}/${yy}`;
    }
  } catch {}
  return raw;
}
