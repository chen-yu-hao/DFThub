# DFThub Frontend

Standalone Astro frontend for DFThub. It serves DFThub at the root `/` route, with `/dfthub` as a compatibility redirect to `/`, and does not depend on `Client/WebUI` source files.

Overview (`/`), Workspace (`/workspace/`) and Analyze (`/analyze/`) are separate static pages with shared navigation, authentication and appearance. Legacy `/#workspace` links redirect to Workspace. The preview server normalizes `/workspace` and `/analyze` to their trailing-slash routes while preserving query parameters.

Analyze compares completed runs, including forks. Trends, Input vs SCF and All changes share a focus run and always use the original CF22D parameters as the comparison baseline. Selection, focus, added datasets, scale and change filters are reflected in the URL; legacy `vs=parent` links also use CF22D. Reference mean is an unweighted average of shared reference dataset MUEs with available baseline values; it is distinct from Workspace's point-weighted category MUE. Missing values remain `—`. Input baselines require verified native-CF22D provenance. Wavefunction overlap uses an expanded view of values near one, with the same axis range in figure exports. The MUE trend chart stacks Train and optional Test panels with independent MUE scales and a shared weight axis. The Test panel is omitted when no included run has a test set. Main runs form the solid non-SCF/SCF lines. Forks are hollow markers offset to the right of their recorded parent and joined only to that parent by short dotted branches; forks are not linked across weights. Each main run has its own unconnected CF22D baseline segment. Only main-series names appear at the right edge. The Series menu controls visibility and reference datasets. A single focus band and run/weight axis span both panels; SVG/PNG exports use the same renderer.

New jobs can optionally include a test geometry archive and matching `.ref` file. The pair is stored under `input/test_set/`; its descriptors, optimized MUE and native CF22D MUE are evaluated after fitting while the training optimizer reads only `INPUT`, `INPUT_ref` and `weight.csv`. Input SCF calculations evaluate both uploaded sets and expose separate result rows. Workspace and Analyze label test values as evaluation-only; jobs without the pair follow the original path unchanged.

The React `Analyze` component supplies authenticated data and actions to an isolated renderer adapted from the supplied SVG/HTML implementation. No sample dataset generator is shipped. The file API supplies MUE, weights, lineage and Input SCF metadata without downloading process logs. Background job summaries load progressively. Active SCF states refresh every 15 seconds; manual refresh also reloads completed results. SCF submission requires confirmation, uses `mode: spe` and `spe_scope: input`, and handles each accepted or rejected run separately. Legacy Input results are kept separate from AME418 results.

All six charts support table views and SVG/PNG figure exports. PNG files carry their selected DPI in a pHYs chunk; figures use editable text, physical dimensions and a white background. Exported heatmaps follow the current filters and collapsed groups. CSV exports contain actual selected-run values and the chosen deltas, without optimization loss terms.

```bash
pnpm install
pnpm dev
pnpm build
pnpm preview
```

The static deployment output is `dist-dfthub/`. Development and preview proxy same-origin `/api_dft/*` requests to `http://127.0.0.1:2002` by default. Set `DFTHUB_API_TARGET` to use another backend during isolated testing.

In production, serve `dist-dfthub/` from a dedicated host or port, redirect `/dfthub` and `/dfthub/` to `/`, and reverse-proxy `/api_dft/*` to the DFThub backend. Vite preview is intended for verification, not as the production static server.

Serve each generated page directory's `index.html`, including direct requests to Workspace and Analyze. Do not rewrite these routes to the Overview HTML.

The active interface reproduces the supplied `DFThub-redesign.html`: source components live in `src/replica`, and its original style rules live in `src/styles/replica.css`. Jobs, runs, uploaded files and results come from the existing authenticated API. The prototype's illustrative data and calculation timers are not included. All 21 supported basis presets remain available.

Regression checks use Python Playwright and intercept all application APIs, including submissions. Start a preview on an unused port, then run:

```bash
BASE_URL=http://127.0.0.1:8289 OUTPUT_DIR=/tmp/dfthub-replica-qa python tests/verify_replica.py
BASE_URL=http://127.0.0.1:8289 OUTPUT_DIR=/tmp/dfthub-pages-qa python tests/test_pages_browser.py
node tests/test_analysis_v2.cjs
BASE_URL=http://127.0.0.1:8289 OUTPUT_DIR=/tmp/dfthub-analyze-v2-qa python tests/test_analyze_v2_browser.py
```

`tests/verify_api.py` checks the upload and resubmission payloads against the backend source using a temporary data directory, zero workers, and suppressed email. Run it with the backend's Python environment. Set `DFTHUB_API_SOURCE` if the backend source lives elsewhere.
