# Airdrop Eligibility Oracle — Test Log

## 2026-11-14 ~16:40 WIB — build + full suite (research run)

- Built `contracts/oracle_logic.py` + `contracts/eligibility_oracle.py`
  (assembled from the logic file so the pure functions stay
  byte-identical), `tests/` (conftest stub with GET + POST,
  test_logic, test_contract, test_contract_sync), `pytest.ini`,
  `requirements.txt`.
- Live re-verification of the TAC demo during the build (curl to the
  pinned jsDelivr shard `00.json`): root
  `0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10`
  matches DESIGN.md; shard holds 60 claims; demo wallet
  `0x00000000002b00d647a4c78670134888afbc6b5c` → amount
  `14784700000000000`; absent wallet `0x000…0001` confirmed not in
  the shard.
- System python has no pytest (PEP 668 externally-managed env), so
  tests ran in a throwaway venv `/tmp/oracle-venv` with pytest
  installed there. Command:
  `cd airdrop-eligibility-oracle && /tmp/oracle-venv/bin/python -m pytest -q`
- First run: 35 passed, 17 failed — all failures traced to one bug in
  `normalize_project_id`: it checked characters against the hex set
  (`0123456789abcdef`), rejecting slugs with letters g–z (e.g.
  "hyperliquid-genesis", and even the test's own "tac" was fine but
  "hyperliquid-genesis" failed). Fixed to a–z / 0–9 / `-`, re-assembled
  the contract from the logic file, re-ran.
- Final run: **52 passed, 0 failed.**
- Sanity: SafeLink suite still passes in the same venv (55/55).
- `python3 -m py_compile` on both contract files: OK.
## 2026-11-15 ~07:20 WIB — GenVM direct + glsim live (research run)

### Direct GenVM suite (real engine, mocked web): 7/7 passed
- `gltest tests-direct -q` → **7 passed in 0.34s** (SafeLink venv).
  gltest direct mode has NO live web: unmocked fetches raise
  `MockNotFoundError`. TAC uses the REAL shard bytes (fixture
  `tests-direct/fixtures/tac-shard-00.json`, re-fetched live 06:48 WIB);
  HYPE uses a SMALL synthetic genesis list (documented as synthetic).
  Checks: deploy defaults, TAC real-shard eligible + validator agrees,
  TAC real-shard not-eligible + validator agrees, validator disagrees
  when the shard changes, HYPE synthetic eligible + validator agrees,
  HYPE synthetic not-eligible, fetch failure (404) writes nothing.
- NOTE on the 404 check: it passed pre-fix for the WRONG reason (see
  UserError bug below — the leader raised AttributeError instead of
  UserError; still "writes nothing"). It passes post-fix for the right
  reason (proper UserError, leader error not agreed, no write).

### REAL BUG FOUND + FIXED: `gl.UserError` does not exist in this SDK
- glsim deploy / live checks failed with
  `module 'genlayer.gl' has no attribute 'UserError'`.
- Verified against the PINNED Studio runner: downloaded genvm v0.2.5
  (runner hash `1jb45aa8…` from the contract header); its std lib is
  byte-identical to the cached v0.2.16 std. `UserError` lives ONLY in
  `genlayer.gl.vm` (vm.py line 51); `genlayer.gl.__getattr__` lazy-loads
  only nondet/eq_principle/evm/advanced/vm. So `gl.UserError` is broken
  on STUDIO too, not just glsim — every error path in the Oracle (and
  in SafeLink, which uses the same pattern) degraded to AttributeError.
- Fix (contract not yet deployed anywhere, so safe to fix now):
  `from genlayer.gl.vm import UserError` in `eligibility_oracle.py`
  (line 270) + all 20 `gl.UserError` → `UserError`; same rename in the
  `oracle_logic.py` docstring. Stub harness updated the same way
  (`tests/conftest.py` now registers fake `genlayer.gl` /
  `genlayer.gl.vm` submodules).
- After fix: stub suite **52/52 passed** (`/tmp/oracle-venv3`,
  `python -m pytest -q`), direct suite **7/7 passed**.
- SafeLink carries the SAME latent bug (`gl.UserError` throughout
  `safelink.py`) and is already deployed on Studio + IC accepted.
  NOT fixed here on purpose — changing it needs a redeploy and could
  affect the accepted IC / pending Project review. Flagged for Syarif
  to decide in the GenLayer chat. SafeLink's happy paths work; only
  its error paths degrade.

### glsim deploy flakiness — ROOT-CAUSED (two separate bugs)
1. **numpy missing from the SafeLink venv**: the SDK's
   `_populate_np_descs()` runs once per process and does
   `import numpy`; first deploy on a fresh glsim server failed with
   `No module named 'numpy'`, then the flag stuck and later deploys
   worked. FIXED: `pip install numpy` (2.5.4) in the SafeLink venv.
2. **Proxy-class cache poisoning (glsim bug, NOT our contract)**:
   `gltest.direct.loader.deploy_contract` returns a `_make_contract_proxy`
   instance; `engine.deploy()` caches `type(instance)` — the PROXY class
   (same name/module, no `__gl_allow_storage__`, no storage
   annotations) — as the contract class. First deploy on a fresh
   server succeeds; EVERY later deploy of the same code fails with
   `class is not marked for usage within storage... @allow_storage`.
   Proven in-process with SimEngine (deploy #1 SUCCESS, #2/#3 FAILED,
   cached class id ≠ loaded class id). The `@allow_storage` decorator
   added to `EligibilityOracle` during debugging is HARMLESS (stub
   52/52 + direct 7/7 still pass) but is NOT what fixed the deploy —
   the deploy works because it is the first on a fresh server.
   RULE: **one Oracle deploy per glsim server process — restart glsim
   before each deploy.** SafeLink never hit this because it was only
   ever deployed once per server.
- Also installed `httpx` (0.28.1) in the SafeLink venv — glsim's live
  web handler needs it; without it every fetch became a synthetic 502.

### glsim LIVE consensus test — TAC PASSES, HYPE blocked by sandbox
- `scripts/glsim_live_test.py` on a fresh 5-validator glsim server
  (result: `scripts/glsim_live_result.json`):
  **3/5 checks passed** — projects_registered PASS, `tac_live_eligible`
  **PASS (5.3s)**: verdict=eligible, amount=`14784700000000000`,
  root=`0x27451b…a10` — leader + all 5 validators fetched the REAL
  shard from jsDelivr and agreed; `tac_live_not_eligible` **PASS
  (4.3s)**. First true live-consensus verification of the Oracle.
- HYPE live checks FAIL (0.3s, verdict=unchecked): the sandbox egress
  proxy returns 403 for Python httpx AND for curl POST to
  `api.hyperliquid.xyz/info` (policy `hitl_domain_allow_hyperliquid_xyz`,
  `POST /info` denied in this research environment). This is a SANDBOX
  limit, not a contract or GenVM failure. The ~5 MB HYPE fetch under
  real consensus is therefore STILL UNTESTED — the HYPE v1-vs-v2
  decision stays open until a Studio deploy (no sandbox proxy there)
  or an unrestricted network. TAC carries v1 alone for now; HYPE stays
  v2 unless the Studio deploy proves otherwise.
- Workaround used for TAC: `/tmp/glsim_curl_server.py` — a glsim server
  that monkeypatches `glsim.live_io.create_web_handler` with a curl
  subprocess handler (same return format, no glsim files modified),
  because the proxy allows curl→jsDelivr (200) but 403s httpx→jsDelivr
  (httpx→api.github.com works, so the block is per-host, not per-client
  in general; and `NO_PROXY`'s bracketed IPv6 entries also crash httpx
  URL parsing — `Invalid port: ':1]'` — another reason the built-in
  handler could never work here).
- glsim server stopped after the run (was on :4000, curl-handler
  variant). Restart it fresh before any new deploy (see rule above).

### Still open after this run
- HYPE v1-vs-v2 decision (needs Studio deploy or unrestricted net).
- Studionet deploy, GitHub repo (Syarif creates), Portal submit —
  all await Syarif; IC slot resets Mon 16 Nov 2026 07:00 WIB.

## 2026-11-20 ~09:15 WIB — re-verification for zkVerify Wildcard GO (Syarif: "Gas Wildcard — deploy + demo + submit")
- Syarif's 2x rule: stub suite run TWICE with SafeLink venv pytest 9.2.0 → **52 passed, 0 failed** both runs (0.12s / 0.08s). Direct GenVM suite run TWICE → **7 passed** both runs (0.43s / 0.26s). (/tmp/oracle-venv3 from 15 Nov is gone — VM replacement wiped /tmp; SafeLink venv has pytest, use it.)
- HYPE decision STILL OPEN: glsim live HYPE failed only because the sandbox egress proxy 403s POST to api.hyperliquid.xyz (policy, not contract). The Studio deploy (no sandbox proxy) is the decider: if Studio consensus returns eligible 1819.26, HYPE stays v1; if unchecked, HYPE drops to v2 and TAC carries v1 alone.
- GitHub repo: connector create_repository attempted 20 Nov 09:15 WIB → **403 "Resource not accessible by integration"** (same as SafeLink 13 Nov). Muse GitHub App cannot create repos. BLOCKED on Syarif: create empty PUBLIC repo `Airdrop-Eligibility-Oracle-On-GenLayer` on github.com/new (no README) + add it to the Muse GitHub App installation, then Muse pushes files.
- IC slot note: Oracle waits for GenLayer Portal reset Mon 23 Nov 07:00 WIB (Token Safety + Pool used this week's slots). Wildcard work must not disturb that queue.

## 2026-11-20 ~09:10–09:21 WIB — STUDIONET DEPLOY + LIVE RUNS (Wildcard GO)
- Studio (studio.genlayer.com): no runner-picker UI; runner comes from the contract header pin. Pinned py-genlayer v0.2.5 (1jb45aa8…) ACCEPTED, deploy succeeded — v0.2.5 still live on stable Studio. No re-pin, no file edits.
- DEPLOYED: contract **0x502e8d85631b94b97F41A6Ed4De1450Ed8FdacC3**, Studionet 61999, deploy tx **0x6033bc2d849d289f3fa69544c9ee6863d5197e419a9c17edb2a143925f4fd4d9** FINALIZED, GenVM SUCCESS, consensus Accepted, created 09:10:37 WIB. Deployer/admin Studio local account 0x01ED7Ae5A842895C7E05a3CE5587d8DC67a6102F (same as SafeLink), funded 10 test GEN from Studio faucet. VERIFIED independently by Muse from the Studio explorer (address page shows 6 txs, creator + deploy tx match).
- add_project TAC tx 0xee267cab… FINALIZED; add_project hyperliquid-genesis tx 0x84e2b833… FINALIZED.
- TAC LIVE (both FINALIZED, both matched): eligible wallet → verdict eligible, amount 14784700000000000, root 0x27451b…a10, status 200 (tx 0x48374fdc…); absent wallet → not_eligible, amount "" (tx 0x72e45a4a…). Explorer confirms both SUCCESS / Accepted.
- **HYPE DECISION: DROPS TO v2.** check_eligibility HYPE tx 0x83e68995… FINALIZED but GenVM ERROR / consensus Undetermined (3x "Majority disagreement, rotating the leader", then "Failed to reach consensus"), no verdict written, get_eligibility = unchecked. The ~5 MB Hyperliquid fetch did not converge under real Studio consensus. Per the pre-set rule this decides it — no retry (tx finalized; retry allowance was only for a tx that failed to finalize). TAC carries v1 alone. HYPE stays registered in the contract (for v2 work) and labelled "v2 candidate" in the demo.
- Demo config filled with the contract address 20 Nov (oracle-demo/src/config.js). Still open: GitHub repo (Syarif), Vercel demo deploy (Syarif), Wildcard register + submit (Syarif, before 22 Nov 06:59 WIB), Portal IC submit Mon 23 Nov 07:00 WIB.
