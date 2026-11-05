"""Code shared by ASSella, Uran (Decky plugin) and Epsilon (browser bridge).

Everything here is plain Python 3 with no third-party dependencies at import
time, no Qt, no Decky API, so each tool can vendor this folder as-is:

* sls_yaml        - comment-preserving config.yaml text edits
* manifest_lua    - Hubcap .lua bundle parsing (addappid / setManifestid)
* depot_tags      - depot / DLC name helpers
* plugin_manifest - SLSsteam plugin set and the signed plugins manifest
                    (manifest fetching is present but switched off)

Keep this folder free of tool-specific imports; a tool adapts it, never the
other way round.
"""

__version__ = "0.1.0"
