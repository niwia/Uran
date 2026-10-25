import { ConfirmModal, showModal } from "@decky/ui";
import QRCode from "qrcode";
import React, { useEffect, useState } from "react";
import { keyServerStatus, startKeyServer, stopKeyServer } from "../api";

export interface QrKeyModalProps {
  closeModal?: () => void;
  onSuccess?: () => void;
  title?: string;
  description?: string;
}

export const QrKeyBody: React.FC<{
  onSuccess?: () => void;
  closeModal?: () => void;
}> = ({ onSuccess, closeModal }) => {
  const [qrSvg, setQrSvg] = useState<string | null>(null);
  const [error, setError] = useState<string>("");
  const [status, setStatus] = useState<string>("starting");
  const [expiresIn, setExpiresIn] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    (async () => {
      try {
        const r = await startKeyServer();
        if (!alive) return;
        if (!r?.ok) {
          setError(r?.error || "Could not start local key server.");
          return;
        }
        const url = r.urls?.[0];
        if (!url) {
          setError("No local network IP detected. Please connect to Wi-Fi.");
          return;
        }
        const svg = await QRCode.toString(url, {
          type: "svg",
          errorCorrectionLevel: "M",
          margin: 1,
          width: 220,
          color: { dark: "#000000", light: "#ffffff" },
        });
        if (!alive) return;
        setQrSvg(svg);
        setStatus(r.status || "waiting");
        setExpiresIn(r.expires_in ?? null);

        pollTimer = setInterval(async () => {
          try {
            const s = await keyServerStatus();
            if (!alive || !s) return;
            setStatus(s.status || "waiting");
            setExpiresIn(s.expires_in ?? null);
            if (!s.running || s.status === "accepted") {
              if (pollTimer) clearInterval(pollTimer);
              if (s.status === "accepted") {
                setTimeout(() => {
                  if (alive) {
                    onSuccess?.();
                    closeModal?.();
                  }
                }, 1000);
              }
            }
          } catch {
            // keep polling
          }
        }, 1000);
      } catch (err: any) {
        if (alive) setError(err?.message || "Failed to start key server.");
      }
    })();

    return () => {
      alive = false;
      if (pollTimer) clearInterval(pollTimer);
      void stopKeyServer().catch(() => {});
    };
  }, [onSuccess, closeModal]);

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "12px 0" }}>
      <div style={{ marginBottom: "12px", fontSize: "13px", color: "#d0d7de", textAlign: "center" }}>
        Scan this QR code with your phone camera to paste your Hubcap API key.
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          background: "#ffffff",
          padding: "10px",
          borderRadius: "10px",
          lineHeight: 0,
          minHeight: "220px",
          minWidth: "220px",
        }}
      >
        {qrSvg ? (
          <div dangerouslySetInnerHTML={{ __html: qrSvg }} />
        ) : error ? (
          <div style={{ color: "#e57373", fontSize: "12px", lineHeight: "1.4", padding: "12px", textAlign: "center" }}>
            {error}
          </div>
        ) : (
          <div style={{ color: "#333333", fontSize: "12px", lineHeight: "1.4" }}>
            Generating QR code...
          </div>
        )}
      </div>

      <div
        style={{
          marginTop: "12px",
          fontSize: "12px",
          textAlign: "center",
          color: status === "accepted" ? "#7ee2a8" : "#9aa4b2",
        }}
      >
        {status === "accepted"
          ? "Key received — completing operation..."
          : `Scan with your phone${expiresIn ? ` · closes in ${Math.max(0, expiresIn)}s` : ""}`}
      </div>
    </div>
  );
};

export const showQrKeyModal = (onSuccess?: () => void, title = "Hubcap API Key Required"): void => {
  let modalInstance: ReturnType<typeof showModal>;
  modalInstance = showModal(
    <ConfirmModal
      strTitle={title}
      strOKButtonText="Close"
      bOKDisabled={false}
      onOK={() => modalInstance.Close()}
      onCancel={() => modalInstance.Close()}
    >
      <QrKeyBody
        onSuccess={() => {
          onSuccess?.();
          modalInstance.Close();
        }}
        closeModal={() => modalInstance.Close()}
      />
    </ConfirmModal>,
    undefined,
    { bNeverPopOut: true },
  );
};
