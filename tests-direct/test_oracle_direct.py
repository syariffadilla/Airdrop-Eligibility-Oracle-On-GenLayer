"""Direct-mode tests: the REAL Oracle contract executed by the GenVM
direct engine (gltest).

Run from the airdrop-eligibility-oracle/ directory with SafeLink's
venv (it already has genlayer-test 0.29.2 + the cached v0.2.16
GenVM tarball):
    ../../genlayer-intelligent-contracts-submission/safelink/.venv/bin/gltest tests-direct -q

These tests live OUTSIDE tests/ on purpose: plain `pytest` cannot run
them (they need the gltest direct fixtures), and the stub suite in
tests/ cannot run under gltest's direct plugin. See TEST_LOG.md.

Web in gltest direct mode is ALWAYS mocked (unmocked fetches raise
MockNotFoundError — there is no live fallthrough). So:
* TAC uses the REAL shard bytes, fetched live 15 Nov 2026 06:48 WIB
  and saved at tests-direct/fixtures/tac-shard-00.json (60 claims,
  root 0x27451b...6a10, demo wallet amount 14784700000000000). The
  contract parses genuine project data under the real engine.
* HYPE uses a SMALL synthetic genesis list (the real ~5 MB body
  cannot be fetched in this environment — POST to
  api.hyperliquid.xyz/info is denied by the sandbox egress policy,
  not by Hyperliquid). The synthetic list proves the json_list_post
  path + validator agreement under the real engine; the real-5 MB
  question is answered by the glsim live run (scripts/glsim_live_test.py)
  and, finally, by the Studio deploy.
"""

import json
from pathlib import Path

import pytest

# Pin the GenVM release explicitly: the loader's "latest" resolution
# currently points at v0.3.0-rc7, whose genvm-universal.tar.xz asset
# 404s (see SafeLink TEST_LOG.md). v0.2.16 is the release GrantFlow's
# direct tests pinned in Oct 2026.
SDK_VERSION = "v0.2.16"

HERE = Path(__file__).resolve().parent
CONTRACT = str(HERE.parent / "contracts" / "eligibility_oracle.py")

TAC_TEMPLATE = (
    "https://cdn.jsdelivr.net/gh/z0r0z/tacit@1b2eedde8490801c9ef4406020530059162e6d47"
    "/dapp/airdrop/v1/proofs/{shard}.json"
)
TAC_ROOT = "0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10"
TAC_ELIGIBLE = "0x00000000002b00d647a4c78670134888afbc6b5c"
TAC_AMOUNT = "14784700000000000"
TAC_ABSENT = "0x0000000000000000000000000000000000000001"
TAC_SHARD_BODY = (HERE / "fixtures" / "tac-shard-00.json").read_text()

HYPE_URL = "https://api.hyperliquid.xyz/info"
HYPE_BODY = '{"type":"tokenDetails","tokenId":"0x0d01dc56dcaaca66ad901c959b4011ec"}'
HYPE_ELIGIBLE = "0x000000000077cdff30a1b5d7c12f3587f921e519"
HYPE_AMOUNT = "1819.26"
HYPE_ABSENT = "0x0000000000000000000000000000000000000001"
HYPE_SYNTHETIC_BODY = json.dumps(
    {
        "genesis": {
            "userBalances": [
                [HYPE_ELIGIBLE, HYPE_AMOUNT],
                ["0x00000000000000000000000000000000000000aa", "42.5"],
            ]
        }
    }
)


def _deploy(direct_deploy):
    return direct_deploy(CONTRACT, sdk_version=SDK_VERSION)


def _add_tac(oracle):
    return oracle.add_project(
        "tac",
        "TAC",
        "TAC",
        "json_map",
        TAC_TEMPLATE,
        "GET",
        "",
        "https://tacit.finance/airdrop",
    )


def _add_hype(oracle):
    return oracle.add_project(
        "hyperliquid-genesis",
        "Hyperliquid HYPE Genesis",
        "HYPE",
        "json_list_post",
        HYPE_URL,
        "POST",
        HYPE_BODY,
        "https://app.hyperliquid.xyz/",
    )


def test_deploy_defaults(direct_deploy, direct_owner):
    oracle = _deploy(direct_deploy)
    stats = oracle.get_stats()
    assert stats["total_entries"] == 0
    assert stats["check_count"] == 0
    assert stats["ttl_checks"] == 1000
    assert stats["admin"].lower() == "0x" + direct_owner.hex()


def test_tac_real_shard_eligible_and_validator_agrees(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_tac(oracle)
    direct_vm.mock_web(
        r"cdn\.jsdelivr\.net",
        {"method": "GET", "status": 200, "body": TAC_SHARD_BODY},
    )
    result = oracle.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["eligible"] is True
    assert result["verdict"] == "eligible"
    assert result["amount_str"] == TAC_AMOUNT
    assert result["source_root"] == TAC_ROOT
    assert result["status_code"] == 200
    assert direct_vm.run_validator() is True
    assert oracle.get_stats()["eligible"] == 1


def test_tac_real_shard_not_eligible_and_validator_agrees(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_tac(oracle)
    direct_vm.mock_web(
        r"cdn\.jsdelivr\.net",
        {"method": "GET", "status": 200, "body": TAC_SHARD_BODY},
    )
    result = oracle.check_eligibility("tac", TAC_ABSENT)
    assert result["eligible"] is False
    assert result["verdict"] == "not_eligible"
    assert result["amount_str"] == ""
    assert result["source_root"] == TAC_ROOT
    assert direct_vm.run_validator() is True
    assert oracle.get_stats()["not_eligible"] == 1


def test_validator_disagrees_when_shard_changes(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_tac(oracle)
    direct_vm.mock_web(
        r"cdn\.jsdelivr\.net",
        {"method": "GET", "status": 200, "body": TAC_SHARD_BODY},
    )
    result = oracle.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["eligible"] is True
    # The validator re-fetches and now sees an empty shard.
    direct_vm.clear_mocks()
    direct_vm.mock_web(
        r"cdn\.jsdelivr\.net",
        {
            "method": "GET",
            "status": 200,
            "body": json.dumps({"root": TAC_ROOT, "claims": {}}),
        },
    )
    assert direct_vm.run_validator() is False


def test_hype_synthetic_list_eligible_and_validator_agrees(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_hype(oracle)
    direct_vm.mock_web(
        r"api\.hyperliquid\.xyz",
        {"method": "POST", "status": 200, "body": HYPE_SYNTHETIC_BODY},
    )
    result = oracle.check_eligibility("hyperliquid-genesis", HYPE_ELIGIBLE)
    assert result["eligible"] is True
    assert result["verdict"] == "eligible"
    assert result["amount_str"] == HYPE_AMOUNT
    assert result["status_code"] == 200
    assert direct_vm.run_validator() is True
    assert oracle.get_stats()["eligible"] == 1


def test_hype_synthetic_list_not_eligible(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_hype(oracle)
    direct_vm.mock_web(
        r"api\.hyperliquid\.xyz",
        {"method": "POST", "status": 200, "body": HYPE_SYNTHETIC_BODY},
    )
    result = oracle.check_eligibility("hyperliquid-genesis", HYPE_ABSENT)
    assert result["eligible"] is False
    assert result["verdict"] == "not_eligible"
    assert direct_vm.run_validator() is True


def test_fetch_failure_writes_nothing(direct_deploy, direct_vm):
    oracle = _deploy(direct_deploy)
    _add_tac(oracle)
    direct_vm.mock_web(
        r"cdn\.jsdelivr\.net",
        {"method": "GET", "status": 404, "body": "not found"},
    )
    with pytest.raises(Exception):
        oracle.check_eligibility("tac", TAC_ELIGIBLE)
    assert oracle.get_stats()["total_entries"] == 0
    assert oracle.get_stats()["check_count"] == 0
