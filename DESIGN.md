# Airdrop Eligibility Oracle — Design v1 (2026-11-14)

Concept draft (HQ): `~/workspace/genlayer/ic-airdrop-eligibility-oracle.md`
— this file is the implementation design for it. Project room: GenLayer
side chat (e0e04e4b), under the Airdrop Manager (MASTER.md).

Picked by Syarif 2026-11-14 (idea C from the 13 Nov shortlist; duplicate check
14 Nov via Project Explorer, all 3 categories: CLEAR — nearest are ClaimCourt
(airdrop-claim announcements, single page) and Eligibility Judge (hackathon
entries vs rulebook), both different domains).

## The question

"Is wallet W eligible for airdrop P, and for how much?" — one contract, any
airdrop with a public eligibility source. Eligibility lives off-chain (project
APIs, published allocation lists); a normal contract cannot fetch the web.
GenLayer validators can, independently, and must agree.

## Verdicts

- **ELIGIBLE** — address found in the source, with an allocation amount
  (kept as the exact raw string from the source, e.g. wei string for TAC,
  decimal string for HYPE — no float math on-chain; formatting is the
  frontend's job).
- **NOT_ELIGIBLE** — source fetched fine, address not in it.
- **No verdict written (unchecked)** — checker unreachable, non-200, gated
  (needs a wallet signature), unparseable, or validators disagree. Same
  safe-failure as SafeLink: disagreement writes nothing.

## Checker registry (admin-curated, like SafeLink's brands/blocklist)

Each project has a checker config (admin = deployer, same Studio account as
SafeLink):

- `project_id` (lowercase slug), `display_name`, `token_symbol`
- `checker_type`: `json_map` | `json_list_post` (v1)
- `source_url` template with `{address}` / `{shard}` placeholders
- `method` (`GET` / `POST`), `body_template` (for POST)
- `claim_url` (informational, where to claim)
- `status`: active / paused

Types in v1:

- **`json_map`**: GET a JSON map file; look up the lowercase address;
  entry holds the amount. Example: TAC proof shards.
- **`json_list_post`**: POST a JSON body; the response holds an array of
  `[address, amount]` pairs; look up the address. Example: Hyperliquid
  genesis list. Requires `gl.nondet.web.post` — VERIFIED present in
  py-genlayer 0.2.16 (`web.py`: `post(url, body=..., headers=...)`;
  `Response` fields are `.status`, `.headers`, `.body` — same correction
  SafeLink already learned: `.status`, not `.status_code`).

Reserved for later (schema-ready, not shipped in v1): `api_get` with a JSON
response path (e.g. Sablier `GET /api/eligibility?address=&cid=` → `{address,
amount}` — pattern docs-verified, but no live campaign CID in hand, so no
live test yet) and `csv` (e.g. Furucombo gist).

## Consensus rule (the SafeLink pattern, no LLM in v1)

`check_eligibility(project_id, wallet)` uses
`gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`; leader fetches the
source and derives signals; every validator independently re-fetches and
re-derives. A verdict is written ONLY when validators agree exactly on all
compared fields:

`project_id`, `wallet` (normalized lowercase), `eligible` (bool),
`amount_str`, `source_url` (rendered), `status_code`, `checker_type`,
`source_root` ("" if the source has none; TAC's Merkle root — pins the
verdict to a specific snapshot version).

Deterministic lookup + JSON parse only. No LLM in v1.

## Normalization

- Wallet: lowercase, must be `0x` + 40 hex chars, else the call is rejected.
- Project id: lowercase slug.
- Amount: raw string, compared exactly.

## State / API

- `TreeMap[(project_id, wallet) → Entry]`, `entry_order`, `projects:
  TreeMap[project_id → ProjectConfig]`, counters (`checks`, `eligible`,
  `not_eligible`, `disputes`), `ttl_checks` default 1000 (freshness in
  checks, no wall-clock — same as SafeLink).
- Entry: `project_id`, `wallet`, `eligible`, `amount_str`, `source_url`,
  `source_root`, `status_code`, `check_seq`, `disputes`.
- Admin-only: `add_project`, `update_project`, `remove_project`
  (tombstone), `pause_project` / `unpause_project`, `set_ttl_checks`.
- Anyone: `check_eligibility`, `dispute`, `request_recheck`.
- Views: `get_eligibility`, `is_eligible`, `get_entry`, `list_entries`,
  `list_projects`, `get_project`, `get_stats`.

## Demo projects (live-verified 2026-11-14)

### 1. TAC (tacit.finance) — `json_map`, PRIMARY demo

- Shard URL:
  `https://cdn.jsdelivr.net/gh/z0r0z/tacit@1b2eedde8490801c9ef4406020530059162e6d47/dapp/airdrop/v1/proofs/{shard}.json`
  where `{shard}` = first byte of the address (lowercase, no `0x`).
- VERIFIED live 14 Nov: shard `00.json` returns
  `{root, claims: {address: {index, amount, proof: [14 hashes]}}}`.
  Merkle root `0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10`
  (matches the on-chain claim contract).
- Claim contract `0x4b4cb98D0C836c2783Ac46f0078b904dab533AE8`, deadline
  2026-12-20, 8,652 recipients.
- Demo ELIGIBLE: `0x00000000002b00d647a4c78670134888afbc6b5c` →
  amount `14784700000000000` (wei).
- Demo NOT_ELIGIBLE: an address in shard `00` absent from `claims` —
  builder pins one by scanning the shard before the live run.
- Why this demo is strong: small sharded files, CORS-enabled + immutable
  (jsDelivr pinned to a commit), and the allocation is verifiable against
  the on-chain Merkle root.

### 2. Hyperliquid HYPE genesis — `json_list_post`, SECONDARY demo

- POST `{"type":"tokenDetails","tokenId":"0x0d01dc56dcaaca66ad901c959b4011ec"}`
  to `https://api.hyperliquid.xyz/info`.
- VERIFIED live 14 Nov: HTTP 200, 5,203,714 bytes, `genesis.userBalances`
  holds 94,023 `[address, amount]` pairs.
- Demo ELIGIBLE: `0x000000000077cdff30a1b5d7c12f3587f921e519` → `"1819.26"` HYPE.
- Demo NOT_ELIGIBLE: any address absent from the list (builder pins one).
- RISK (must be tested in GenVM direct runs): the response is ~5 MB per
  validator fetch. If GenVM handles it poorly, HYPE drops to v2 and TAC
  carries v1 alone. A second small `json_map` project is the fallback
  demo if needed.

### 3. Sablier Merkle API — pattern only, NOT a v1 demo

- Docs-verified pattern: `GET /api/eligibility?address=<addr>&cid=<cid>` →
  `{address, amount}`. No live campaign CID in hand, so no live test yet.

### Known NOT usable (documented so the build doesn't chase them)

- AlignedLayer: full allocation endpoint requires a per-wallet ToS
  signature — validators cannot sign; the passive `/network` endpoint
  does not say eligible or not. Returns UNKNOWN by design.
- Starknet Provisions: the published recipients repo is disabled;
  per-address data is only readable on-chain via events, not a fetch.

## Tests (mirror SafeLink: 67 passed, 0 failed)

- Stub tests (mocked web): json_map hit/miss, json_list_post hit/miss,
  malformed JSON, non-200, gated/empty body, bad address format, unknown
  project, paused project, admin-only guards, TTL recheck, dispute flow,
  exact-agreement writes vs disagreement writes nothing.
- Real GenVM direct tests (SDK v0.2.16): 7/7 passed 15 Nov 2026 — but
  NOTE: gltest direct mode has NO live web (unmocked fetches raise
  `MockNotFoundError`). TAC ran on the REAL shard bytes (fixture);
  HYPE ran on a small synthetic list. Live consensus fetches are a
  glsim/Studio matter, not a direct-mode matter.
- glsim live (15 Nov 2026): TAC eligible + not-eligible PASS under real
  5-validator consensus (5.3s / 4.3s, real jsDelivr shard). HYPE live
  STILL UNTESTED — the research sandbox's egress proxy blocks POST to
  api.hyperliquid.xyz (policy, not a contract/GenVM failure). HYPE v1
  vs v2 is decided on the Studio deploy. TAC carries v1 alone for now.
- ERROR TYPE (corrected 15 Nov 2026): `gl.UserError` does NOT exist in
  the pinned SDK (v0.2.5 runner std = v0.2.16 std, verified byte-identical).
  Use `from genlayer.gl.vm import UserError`. The Oracle was fixed; SafeLink
  still uses `gl.UserError` (latent bug, error paths degrade to
  AttributeError on Studio — decision pending with Syarif).
- glsim RULE: one Oracle deploy per glsim server process (proxy-class
  cache poisoning makes the 2nd+ deploy fail — see TEST_LOG.md).
  Restart glsim before each deploy; venv now has numpy + httpx (were
  missing, both caused first-load/synthetic-502 failures).
- Target: stable Studionet chain 61999, runner pin
  `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`
  (v0.2.5) — same as SafeLink.

## Submission plan

- Build Sat 14 – Sun 15 Nov, deploy + live runs on Studionet, GitHub repo,
  Portal IC submission when slots reset Mon 16 Nov 07:00 WIB (2 IC slots
  per week; SafeLink IC used last week's slot).
- Portal evidence (like SafeLink IC): explorer contract link + GitHub repo.
  A frontend/Project phase is a separate later step, like SafeLink.

## Open questions for Syarif

1. Contract/project name "Airdrop Eligibility Oracle" — OK?
2. Demo scope TAC primary + HYPE secondary (with the 5 MB risk noted) — OK?
3. Go to build? Same cadence as SafeLink: delegated builder builds, Muse
   verifies, Syarif submits via the Portal.
