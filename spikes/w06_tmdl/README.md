# W-06 TMDL serializer spike

This isolated proof of concept evaluates Microsoft's supported TOM/TMDL serializer before it is adopted by production Python code. It is not the W-06 production adapter and does not make the PBIP fixture Desktop-verified.

## Decision candidate

- Use a pinned local .NET helper process around `Microsoft.AnalysisServices.Tabular.TmdlSerializer`; keep the Python application as the orchestrator.
- Deserialize the complete TMDL folder to TOM, mutate only typed objects in a future staging copy, then serialize the complete database to a new folder.
- Compare a semantic catalog before/after and byte hashes for all files outside the staged TMDL folder. Do not patch TMDL with regex or free-form text replacement.
- First serialization canonicalizes ordering and formatting, so exact source/output byte equality is not an acceptance condition. A second deserialize/serialize pass must be byte-stable, and all supported semantic metadata must match.
- Keep this helper offline at runtime. NuGet restore is a build/setup action only; the production app must use locked package versions and a prebuilt local helper.

## Verified environment

- .NET SDK 9.0.312 can build a `net8.0` helper.
- `Microsoft.AnalysisServices` 19.117.0 exposes `TmdlSerializer.DeserializeDatabaseFromFolder` and `SerializeDatabaseToFolder`.
- The synthetic spike fixture round-trips tables, columns, measure expression/format/description, partitions, and relationship. The canonical second pass is byte-stable.
- Invalid TMDL is rejected, source bytes remain unchanged, and an existing destination is not overwritten.

## Run

Restore is intentionally explicit because it can access NuGet:

```powershell
dotnet restore spikes/w06_tmdl/TmdlSpike.csproj --locked-mode
py -m unittest discover -s spikes/w06_tmdl -p "test_*.py" -v
```

`packages.lock.json` is committed for the spike; `--locked-mode` prevents an unnoticed dependency change. Production uses the separate helper under `tools/tmdl_bridge` with its own lock file.

## Fixture issue resolved

The spike found that a measure `description:` property was rejected by version 19.117.0. The W-03 generator now emits the official `///` documentation comment syntax, and the production bridge test parses the regenerated baseline successfully.
