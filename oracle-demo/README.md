# Airdrop Eligibility Oracle - demo

Public demo for the Airdrop Eligibility Oracle on GenLayer Studionet
(chain 61999). Built for the zkVerify Agent Games Wildcard entry.
Vite + genlayer-js, same pattern as the SafeLink demo.

## What it does

Ask whether a wallet is eligible for an airdrop, and for how much.
Validators fetch the project's own eligibility source and agree
exactly before any verdict is written. ELIGIBLE, NOT ELIGIBLE, or
UNCHECKED (source could not be fetched, nothing written).

Demo wallets (TAC, verified live 14-15 Nov 2026):
- Eligible: `0x00000000002b00d647a4c78670134888afbc6b5c` - expect
  ELIGIBLE, amount `14784700000000000` wei.
- Absent: `0x0000000000000000000000000000000000000001` - expect
  NOT ELIGIBLE.

Hyperliquid HYPE Genesis is in the picker as a v2 candidate. Its
genesis list is about 5 MB per validator fetch, still under test.
It may return unchecked. TAC carries v1.

## Before deploy: set the contract address

The contract is not deployed yet. After the Studio deploy, paste
the Studionet address in exactly one place:

```js
// src/config.js
export const CONTRACT_ADDRESS = "0x...";
```

Also fill `REPO_URL` in the same file once the GitHub repo exists.
Then rebuild and redeploy. Until the address is set the page shows
"Contract not deployed yet" and makes no contract calls.

## Deploy on Vercel (Syarif)

1. Push this folder to the GitHub repo (root directory `oracle-demo`).
2. Vercel: import the repo.
3. Root Directory: `oracle-demo`.
4. Framework: Vite.
5. Install: `npm ci`.
6. Build: `npm run build`.
7. Output: `dist`.
8. No env vars needed.

## Develop

```sh
npm ci
npm run dev
npm run build
```

## Honest note

This oracle does not use zkVerify. What can be checked is the TAC
Merkle root on-chain and the exact validator agreement behind each
verdict. The Wildcard submission says exactly that.
