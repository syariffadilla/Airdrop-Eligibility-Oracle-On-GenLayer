"""Live GenVM test on glsim: deploy the Oracle to a local 5-validator
GenLayer network and run real consensus checks against the LIVE
eligibility sources (no mocks anywhere).

Run with SafeLink's venv, while glsim is up on :4000:
    ../../genlayer-intelligent-contracts-submission/safelink/.venv/bin/glsim --port 4000 --no-browser
    ../../genlayer-intelligent-contracts-submission/safelink/.venv/bin/python scripts/glsim_live_test.py

Writes results to scripts/glsim_live_result.json (timings included).
The HYPE checks are the decision point for v1 vs v2: each consensus
round makes the leader AND every validator fetch the ~5 MB genesis
list independently.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(
    0,
    str(ROOT.parent.parent / "genlayer-intelligent-contracts-submission" / "safelink" / ".venv" / "lib" / "python3.12" / "site-packages"),
)

from genlayer_py import create_account, create_client
from genlayer_py.chains import localnet
from genlayer_py.types import TransactionStatus
from gltest.utils import extract_contract_address

CONTRACT_PATH = ROOT / "contracts" / "eligibility_oracle.py"

TAC_TEMPLATE = (
    "https://cdn.jsdelivr.net/gh/z0r0z/tacit@1b2eedde8490801c9ef4406020530059162e6d47"
    "/dapp/airdrop/v1/proofs/{shard}.json"
)
TAC_ROOT = "0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10"
TAC_ELIGIBLE = "0x00000000002b00d647a4c78670134888afbc6b5c"
TAC_AMOUNT = "14784700000000000"
TAC_ABSENT = "0x0000000000000000000000000000000000000001"

HYPE_URL = "https://api.hyperliquid.xyz/info"
HYPE_BODY = '{"type":"tokenDetails","tokenId":"0x0d01dc56dcaaca66ad901c959b4011ec"}'
HYPE_ELIGIBLE = "0x000000000077cdff30a1b5d7c12f3587f921e519"
HYPE_AMOUNT = "1819.26"
HYPE_ABSENT = "0x0000000000000000000000000000000000000001"

RESULTS = {"checks": []}


def record(name, ok, detail, seconds=None):
    RESULTS["checks"].append(
        {"name": name, "ok": bool(ok), "detail": detail, "seconds": seconds}
    )
    print(f"[{'PASS' if ok else 'FAIL'}] {name} ({seconds}s)" if seconds is not None else f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"    {detail}")


def wait(client, tx_hash, label):
    receipt = client.wait_for_transaction_receipt(
        transaction_hash=tx_hash,
        status=TransactionStatus.ACCEPTED,
        interval=2,
        retries=120,
        full_transaction=True,
    )
    print(f"    {label} receipt status: {receipt.get('status')} ({receipt.get('status_name')})")
    return receipt


def extract_address(receipt):
    for path in (
        ("tx_data_decoded", "contract_address"),
        ("data", "contract_address"),
    ):
        node = receipt.get(path[0]) or {}
        if isinstance(node, dict) and node.get(path[1]):
            return node[path[1]]
    if receipt.get("contract_address"):
        return receipt["contract_address"]
    return None


def main():
    admin = create_account()
    print(f"admin: {admin.address}")
    client = create_client(chain=localnet, account=admin)
    try:
        client.fund_account(admin.address, 10**21)
    except Exception as exc:
        # genlayer-py 0.16.3 mis-parses the sim_fundAccount reply
        # (expects a tx hash, gets {"balance": ...}) — the funding
        # itself lands server-side; continue.
        print(f"fund_account parse quirk (ignored): {exc}")
    print("funded admin")

    code = CONTRACT_PATH.read_text()
    t0 = time.time()
    tx_hash = client.deploy_contract(code=code, account=admin)
    receipt = wait(client, tx_hash, "deploy")
    address = extract_address(receipt)
    if not address:
        raise SystemExit(f"deploy receipt has no contract address: {json.dumps(receipt, default=str)[:1500]}")
    RESULTS["contract_address"] = address
    print(f"deployed at {address} in {time.time() - t0:.1f}s")

    def write(fn, *args):
        t0 = time.time()
        tx = client.write_contract(
            address=address, function_name=fn, account=admin, args=list(args)
        )
        wait(client, tx, fn)
        return time.time() - t0

    def read(fn, *args):
        return client.read_contract(
            address=address, function_name=fn, account=admin, args=list(args)
        )

    # --- register projects ---
    dt = write(
        "add_project", "tac", "TAC", "TAC", "json_map", TAC_TEMPLATE,
        "GET", "", "https://tacit.finance/airdrop",
    )
    dt2 = write(
        "add_project", "hyperliquid-genesis", "Hyperliquid HYPE Genesis",
        "HYPE", "json_list_post", HYPE_URL, "POST", HYPE_BODY,
        "https://app.hyperliquid.xyz/",
    )
    projects = read("list_projects")
    record(
        "projects_registered",
        projects.get("total") == 2,
        f"total={projects.get('total')} in {dt + dt2:.1f}s",
        round(dt + dt2, 1),
    )

    # --- TAC live: eligible ---
    dt = write("check_eligibility", "tac", TAC_ELIGIBLE)
    got = read("get_eligibility", "tac", TAC_ELIGIBLE)
    record(
        "tac_live_eligible",
        got.get("eligible") is True
        and got.get("amount_str") == TAC_AMOUNT
        and got.get("source_root") == TAC_ROOT,
        f"verdict={got.get('verdict')} amount={got.get('amount_str')} root={got.get('source_root')}",
        round(dt, 1),
    )

    # --- TAC live: not eligible ---
    dt = write("check_eligibility", "tac", TAC_ABSENT)
    got = read("get_eligibility", "tac", TAC_ABSENT)
    record(
        "tac_live_not_eligible",
        got.get("eligible") is False and got.get("verdict") == "not_eligible",
        f"verdict={got.get('verdict')} amount={got.get('amount_str')!r}",
        round(dt, 1),
    )

    # --- HYPE live: eligible (the ~5 MB decision) ---
    dt = write("check_eligibility", "hyperliquid-genesis", HYPE_ELIGIBLE)
    got = read("get_eligibility", "hyperliquid-genesis", HYPE_ELIGIBLE)
    record(
        "hype_live_eligible",
        got.get("eligible") is True and got.get("amount_str") == HYPE_AMOUNT,
        f"verdict={got.get('verdict')} amount={got.get('amount_str')}",
        round(dt, 1),
    )

    # --- HYPE live: not eligible ---
    dt = write("check_eligibility", "hyperliquid-genesis", HYPE_ABSENT)
    got = read("get_eligibility", "hyperliquid-genesis", HYPE_ABSENT)
    record(
        "hype_live_not_eligible",
        got.get("eligible") is False and got.get("verdict") == "not_eligible",
        f"verdict={got.get('verdict')} amount={got.get('amount_str')!r}",
        round(dt, 1),
    )

    stats = read("get_stats")
    RESULTS["stats"] = stats
    print(f"stats: {stats}")

    out = ROOT / "scripts" / "glsim_live_result.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2))
    print(f"results -> {out}")
    failed = [c for c in RESULTS["checks"] if not c["ok"]]
    print(f"{len(RESULTS['checks']) - len(failed)}/{len(RESULTS['checks'])} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
