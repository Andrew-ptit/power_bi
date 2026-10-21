# TMDL bridge

This local helper exposes a read-only JSON catalog over Microsoft's official `TmdlSerializer`. Production Python never invokes NuGet restore and never edits TMDL text.

Build once during setup:

```powershell
dotnet restore tools/tmdl_bridge/TmdlBridge.csproj --locked-mode
dotnet build tools/tmdl_bridge/TmdlBridge.csproj -c Release --no-restore
```

At runtime `pbip_assistant.tmdl` locates the Release DLL, or accepts an explicit DLL/executable path. Missing helper, invalid TMDL and source mutation are blocking errors. The bridge intentionally suppresses source lines from parser errors because an M expression can contain a local path or credential.
