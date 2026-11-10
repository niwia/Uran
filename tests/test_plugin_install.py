"""Safety tests for the shared plugin file operations."""

import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assella_shared.ed25519 import _verify_pure
from assella_shared.plugin_install import deploy_plugin, undeploy_plugin


def run():
    # RFC 8032 test vector 1: empty message.
    public_key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    signature = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert _verify_pure(public_key, signature, b"")
    assert not _verify_pure(public_key, signature, b"tampered")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bundled = root / "bundle"
        cache = root / "cache"
        target = root / "sls" / "plugins"
        bundled.mkdir()
        payload = b"return { test = true }\n"
        (bundled / "sample.lua").write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()

        class FakeManifest:
            base_url = None
            use_network = False
            bundled_dir = bundled
            retired = {}

            def meta(self, name):
                return {"sha256": digest, "category": "companion"} if name == "sample.lua" else None

            def is_deployable(self, name):
                return name == "sample.lua"

        manifest = FakeManifest()
        result = deploy_plugin("sample.lua", [target], cache, manifest)
        assert result["ok"] and (target / "sample.lua").read_bytes() == payload

        edited = b"user edit\n"
        (target / "sample.lua").write_bytes(edited)
        deploy_plugin("sample.lua", [target], cache, manifest)
        assert (target / "sample.lua.bak").read_bytes() == edited
        assert (target / "sample.lua").read_bytes() == payload

        result = undeploy_plugin("sample.lua", [target])
        assert result["ok"] and (target / "sample.lua.removed.bak").read_bytes() == payload

        # Test download from remote source when not present in bundled dir
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading

        remote_payload = b"return { remote = true }\n"
        remote_digest = hashlib.sha256(remote_payload).hexdigest()

        class MockHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(remote_payload)))
                self.end_headers()
                self.wfile.write(remote_payload)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), MockHandler)
        port = server.server_port
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        class RemoteManifest:
            base_url = f"http://127.0.0.1:{port}"
            use_network = True
            bundled_dir = root / "empty_bundle"
            retired = {}

            def meta(self, name):
                return {"sha256": remote_digest, "category": "companion"}

            def is_deployable(self, name):
                return True

        res = deploy_plugin("remote.lua", [target], cache, RemoteManifest())
        assert res["ok"] and (target / "remote.lua").read_bytes() == remote_payload
        server.server_close()
        thread.join()

        # Test hash mismatch rejects remote and falls back to matching bundle
        bundle_fallback_payload = b"return { bundle_fallback = true }\n"
        bundle_fallback_digest = hashlib.sha256(bundle_fallback_payload).hexdigest()
        (bundled / "mismatch.lua").write_bytes(bundle_fallback_payload)

        class MismatchHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                bad_body = b"corrupted payload\n"
                self.send_response(200)
                self.send_header("Content-Length", str(len(bad_body)))
                self.end_headers()
                self.wfile.write(bad_body)

            def log_message(self, *args):
                pass

        server2 = HTTPServer(("127.0.0.1", 0), MismatchHandler)
        port2 = server2.server_port
        thread2 = threading.Thread(target=server2.handle_request)
        thread2.start()

        class MismatchManifest:
            base_url = f"http://127.0.0.1:{port2}"
            use_network = True
            bundled_dir = bundled
            retired = {}

            def meta(self, name):
                return {"sha256": bundle_fallback_digest, "category": "companion"}

            def is_deployable(self, name):
                return True

        res2 = deploy_plugin("mismatch.lua", [target], cache, MismatchManifest())
        assert res2["ok"] and (target / "mismatch.lua").read_bytes() == bundle_fallback_payload
        server2.server_close()
        thread2.join()

        # Test oversized response (> MAX_PLUGIN_BYTES) rejects remote and falls back to bundle
        from assella_shared.plugin_install import MAX_PLUGIN_BYTES

        oversized_payload = b"X" * (MAX_PLUGIN_BYTES + 100)
        (bundled / "oversized.lua").write_bytes(bundle_fallback_payload)

        class OversizedHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(oversized_payload)))
                self.end_headers()
                self.wfile.write(oversized_payload)

            def log_message(self, *args):
                pass

        server3 = HTTPServer(("127.0.0.1", 0), OversizedHandler)
        port3 = server3.server_port
        thread3 = threading.Thread(target=server3.handle_request)
        thread3.start()

        class OversizedManifest:
            base_url = f"http://127.0.0.1:{port3}"
            use_network = True
            bundled_dir = bundled
            retired = {}

            def meta(self, name):
                return {"sha256": bundle_fallback_digest, "category": "companion"}

            def is_deployable(self, name):
                return True

        res3 = deploy_plugin("oversized.lua", [target], cache, OversizedManifest())
        assert res3["ok"] and (target / "oversized.lua").read_bytes() == bundle_fallback_payload
        server3.server_close()
        thread3.join()

        # Test unreachable remote network falls back to bundle cleanly
        class UnreachableManifest:
            base_url = "http://127.0.0.1:1"  # closed/unreachable port
            use_network = True
            bundled_dir = bundled
            retired = {}

            def meta(self, name):
                return {"sha256": bundle_fallback_digest, "category": "companion"}

            def is_deployable(self, name):
                return True

        (bundled / "offline.lua").write_bytes(bundle_fallback_payload)
        res4 = deploy_plugin("offline.lua", [target], cache, UnreachableManifest())
        assert res4["ok"] and (target / "offline.lua").read_bytes() == bundle_fallback_payload
    print("all plugin install checks pass")


if __name__ == "__main__":
    run()
