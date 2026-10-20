# Rule: Hubcap Key Authority & Unkeyed Depot Safety

In the Uran / ASSella ecosystem:
1. **Hubcap as Sole Key Authority**: Hubcap is the authoritative source for game depot decryption keys and manifest data.
2. **Never Inject Unkeyed Depots**: SteamCMD, Steam Store, and local VDF caches provide metadata (names, DLC AppIDs, platform attribution), but a depot ID must NEVER be mounted into SLSsteam's `AdditionalDepots` or `DecryptionKeys` unless a verified AES key is provided by Hubcap (or it is an unencrypted/shared redistributable).
3. **Download Failure Prevention**: Injecting a depot that lacks a decryption key triggers Steam's `DepotWithoutKey` download error, which breaks game installation and updates.
4. **DLC AppIDs vs. Depots**: Pure-license DLCs can be noted in `AdditionalApps`, but any DLC-attributed depot must be backed by a verified key before mounting.
