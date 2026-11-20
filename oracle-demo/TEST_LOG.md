# Eligibility Oracle demo — Test Log

## 2026-11-20 ~09:07 WIB — build (subagent, build only)

- Scaffold copied from the SafeLink demo
  (`safelink-project/`, Vite + genlayer-js 1.1.8): `package.json`
  (renamed `eligibility-oracle-demo`), `vite.config.js`,
  `vercel.json`, `src/style.css` (editorial print system, plus
  oracle badge/select/demo-row additions), `public/favicon.svg`.
- New: `src/config.js`, `src/lib/oracle.js` (genlayer-js wrapper:
  readClient, walletClient without the MetaMask Snap, read with
  retries, write waiting for FINALIZED, receipt summary that parses
  the JSON entry payload), `src/main.js`, `index.html`, `README.md`.
- Contract methods used, read from
  `contracts/eligibility_oracle.py`: `get_stats`, `list_projects`,
  `get_eligibility`, `get_entry`, `is_eligible`, `list_entries`,
  `check_eligibility` (write). `add_project` is admin-only and is
  NOT in the demo.

### Checks run
- `npm ci` — 233 packages added in 13s. Exit 0.
- `npm run build` — pass, 2.86s. `dist/index.html` 8.10 kB,
  bundle 562.96 kB (same size class as the SafeLink demo; the
  >500 kB chunk warning is the same one SafeLink ships with).
- `vite preview` smoke test — index HTTP 200 (8,078 bytes),
  title "Airdrop Eligibility Oracle" present, "Contract not
  deployed yet" banner present, real JS bundle HTTP 200
  (562,924 bytes).
- `grep` for 0x addresses in `src/` + `index.html` — only the two
  real demo wallets: TAC eligible
  `0x00000000002b00d647a4c78670134888afbc6b5c` and TAC absent
  `0x0000000000000000000000000000000000000001`. No fake contract
  address anywhere.
- `grep` for em-dash — none left in `src/`, `index.html`, or
  `README.md`.

### Not tested (needs the deploy)
- No live contract call has been made. The app shows the
  "Contract not deployed yet" state until `CONTRACT_ADDRESS` is
  set in `src/config.js`. After the Studionet deploy, retest:
  stats load, project picker loads from `list_projects`, TAC
  eligible lookup reads ELIGIBLE with amount
  `14784700000000000`, TAC absent reads NOT ELIGIBLE, and a wallet
  check runs to FINALIZED.

### Known limits
- HYPE is labelled in the picker as a v2 candidate, under test,
  may be unchecked. It is not hidden and not claimed to work.
- `dist/` is built locally and gitignored (Vercel rebuilds it).
  It is left in place as build evidence.

## 2026-11-20 ~09:23 WIB — rebuild with deployed address (Muse verification)
- `src/config.js` filled: CONTRACT_ADDRESS = 0x502e8d85631b94b97F41A6Ed4De1450Ed8FdacC3 (Studionet deploy 09:10 WIB, tx 0x6033bc2d… FINALIZED).
- `npm run build` passes (2.88s); address confirmed present in dist/assets/index-*.js. "Contract not deployed yet" string remains only as the conditional fallback text.
- Still not live-tested against the contract; needs Vercel deploy (Syarif) + live check. Push to GitHub waits on the repo (Syarif creates it).
