# Airdrop Eligibility Oracle — GenLayer Intelligent Contract (v1)

Status: **DEPLOYED 20 Nov 2026 to stable Studionet 61999: 0x502e8d85631b94b97F41A6Ed4De1450Ed8FdacC3** (deploy tx 0x6033bc2d… FINALIZED, GenVM SUCCESS, consensus Accepted). 52/52 stub tests + 7/7 direct GenVM tests, each run 2x (20 Nov). TAC live-verified on Studionet (eligible + not-eligible). **HYPE DROPS TO v2** (Studio live run UNDETERMINED after 3 leader rotations — the ~5 MB fetch did not converge under real consensus). TAC carries v1 alone. Next: GitHub repo (Syarif creates), Portal IC submission when the slot resets **Mon 23 Nov 2026 07:00 WIB**, zkVerify Wildcard submit before 22 Nov 06:59 WIB.

Design: `DESIGN.md` (implementation design) and
`~/workspace/genlayer/ic-airdrop-eligibility-oracle.md` (concept draft).
Picked by Syarif 14 Nov 2026 (idea C; duplicate check CLEAR).

## What it does

"Is wallet W eligible for airdrop P, and for how much?" One contract,
any airdrop with a public eligibility source. Validators fetch the
project's own eligibility source and answer ELIGIBLE / NOT_ELIGIBLE /
UNKNOWN — before anyone spends gas claiming. No LLM in v1:
deterministic lookup + JSON parse only, exact-agreement consensus
(the SafeLink pattern).

Anti-scam rule: only the project's official registered source counts.
A fake claim page on another domain can never produce ELIGIBLE.

## Files

- `contracts/oracle_logic.py` — pure stdlib logic, unit-tested.
- `contracts/eligibility_oracle.py` — the deployable single-file
  contract (pure functions byte-identical to oracle_logic.py; runner
  pinned to stable Studionet py-genlayer v0.2.5, same as SafeLink).
- `tests/test_logic.py` — 25 pure-logic tests.
- `tests/test_contract.py` — 24 contract tests with the fake-genlayer
  stub (TAC + HYPE demos, caching, disputes, disagreement = no write).
- `tests/test_contract_sync.py` — sync guard + runner pin + no-LLM guard.
- `tests/conftest.py` — fake genlayer stub (GET + POST).

## Demo projects (live-verified 14 Nov 2026)

1. **TAC (tacit.finance) — `json_map`, PRIMARY.** Shard URL pinned to
   jsDelivr commit; re-verified live during the build (14 Nov ~16:39
   WIB): root `0x27451b32…a10`, shard `00.json` holds 60 claims, demo
   ELIGIBLE `0x00000000002b00d647a4c78670134888afbc6b5c` →
   `14784700000000000` wei. Claim contract
   `0x4b4cb98D0C836c2783Ac46f0078b904dab533AE8`, deadline 2026-12-20.
2. **Hyperliquid HYPE genesis — `json_list_post`, SECONDARY.** POST to
   `https://api.hyperliquid.xyz/info`, demo ELIGIBLE
   `0x000000000077cdff30a1b5d7c12f3587f921e519` → `"1819.26"` HYPE.
   RISK: ~5 MB response per validator fetch — must be tested in GenVM
   direct runs; if too heavy, HYPE drops to v2 and TAC carries v1.

## Test result (14 Nov 2026, venv pytest)

52 passed. One real bug caught by the tests and fixed during the
build: `normalize_project_id` initially only allowed hex letters
(a–f), so slugs like "hyperliquid-genesis" were rejected; now a–z,
0–9, `-`. SafeLink's suite still passes (55/55) with the same venv.

Run: `python -m pytest -q` (venv with pytest; system python has no
pytest — see TEST_LOG.md).

## Still to do (needs Syarif)

1. **GenVM direct tests** — DONE 15 Nov (7/7, real engine, mocked web) + glsim live TAC pass.
2. **Deploy on Studionet** — DONE 20 Nov: 0x502e8d85631b94b97F41A6Ed4De1450Ed8FdacC3, TAC live-verified, HYPE UNDETERMINED → v2.
3. **GitHub repo** (contract + README + tests), mirroring SafeLink — Syarif creates (Muse cannot create repos, 403 twice).
4. **Portal IC submission Mon 23 Nov 07:00 WIB** — Syarif submits,
   same two-step cadence as SafeLink (he approves the final form text).
5. **zkVerify Wildcard submit before 22 Nov 06:59 WIB** — Syarif registers + submits (draft: ~/workspace/airdrop-system/zkverify-wildcard-submit-draft.md).

Bonus fit: this same oracle is the recommended Wildcard entry (idea A)
for zkVerify Agent Games (deadline 21 Nov) — reuse, don't rebuild.
