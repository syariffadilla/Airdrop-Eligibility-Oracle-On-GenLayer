"""Contract end-to-end tests with the fake genlayer stub (conftest.py)."""

import pytest

from conftest import (
    ADMIN,
    HYPE_AMOUNT,
    HYPE_ELIGIBLE,
    OTHER,
    POST_CALLS,
    POST_RESPONSES,
    TAC_ABSENT,
    TAC_AMOUNT,
    TAC_ELIGIBLE,
    TAC_SHARD_URL,
    WEB_CALLS,
    WEB_RESPONSES,
    hype_genesis_json,
    load_contract,
    reset_web,
    set_sender,
    tac_shard_json,
)

TAC_TEMPLATE = (
    "https://cdn.jsdelivr.net/gh/z0r0z/tacit@1b2eedde8490801c9ef4406020530059162e6d47"
    "/dapp/airdrop/v1/proofs/{shard}.json"
)
HYPE_URL = "https://api.hyperliquid.xyz/info"
HYPE_BODY = '{"type":"tokenDetails","tokenId":"0x0d01dc56dcaaca66ad901c959b4011ec"}'


@pytest.fixture
def oracle():
    reset_web()
    module, fake = load_contract()
    contract = module.EligibilityOracle()
    set_sender(fake, ADMIN)
    return contract, fake


def _add_tac(contract):
    return contract.add_project(
        "tac",
        "TAC",
        "TAC",
        "json_map",
        TAC_TEMPLATE,
        "GET",
        "",
        "https://tacit.finance/airdrop",
    )


def _add_hype(contract):
    return contract.add_project(
        "hyperliquid-genesis",
        "Hyperliquid HYPE Genesis",
        "HYPE",
        "json_list_post",
        HYPE_URL,
        "POST",
        HYPE_BODY,
        "https://app.hyperliquid.xyz/",
    )


# -- admin: projects ------------------------------------------------------


def test_add_project_and_list(oracle):
    contract, _ = oracle
    _add_tac(contract)
    projects = contract.list_projects()
    assert projects["total"] == 1
    assert projects["projects"][0]["project_id"] == "tac"
    assert projects["projects"][0]["checker_type"] == "json_map"


def test_add_project_duplicate_rejected(oracle):
    contract, fake = oracle
    _add_tac(contract)
    with pytest.raises(fake.UserError):
        _add_tac(contract)


def test_add_project_non_admin_rejected(oracle):
    contract, fake = oracle
    set_sender(fake, OTHER)
    with pytest.raises(fake.UserError):
        _add_tac(contract)


def test_add_project_bad_checker_rejected(oracle):
    contract, _ = oracle
    with pytest.raises(Exception):
        contract.add_project(
            "x", "X", "X", "api_get", "https://example.com/", "GET", "", ""
        )


def test_remove_and_readd_project(oracle):
    contract, _ = oracle
    _add_tac(contract)
    contract.remove_project("tac")
    assert contract.list_projects()["total"] == 0
    with pytest.raises(Exception):
        contract.check_eligibility("tac", TAC_ELIGIBLE)
    _add_tac(contract)
    assert contract.list_projects()["total"] == 1


def test_pause_blocks_checks(oracle):
    contract, _ = oracle
    _add_tac(contract)
    contract.pause_project("tac")
    with pytest.raises(Exception):
        contract.check_eligibility("tac", TAC_ELIGIBLE)
    contract.unpause_project("tac")
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    result = contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["eligible"] is True


# -- checking: TAC json_map -----------------------------------------------


def test_check_tac_eligible(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    result = contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["verdict"] == "eligible"
    assert result["eligible"] is True
    assert result["amount_str"] == TAC_AMOUNT
    assert result["source_root"].startswith("0x27451b32")
    assert result["cached"] is False
    assert TAC_SHARD_URL in WEB_CALLS


def test_check_tac_not_eligible(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    result = contract.check_eligibility("tac", TAC_ABSENT)
    assert result["verdict"] == "not_eligible"
    assert result["eligible"] is False
    assert result["amount_str"] == ""


def test_check_uppercase_wallet_normalized(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    result = contract.check_eligibility("TAC", TAC_ELIGIBLE.upper())
    assert result["wallet"] == TAC_ELIGIBLE
    assert result["eligible"] is True


def test_check_bad_wallet_rejected(oracle):
    contract, _ = oracle
    _add_tac(contract)
    with pytest.raises(Exception):
        contract.check_eligibility("tac", "not-a-wallet")


def test_check_unknown_project_rejected(oracle):
    contract, _ = oracle
    with pytest.raises(Exception):
        contract.check_eligibility("nope", TAC_ELIGIBLE)


def test_fresh_entry_is_cached_no_refetch(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    contract.check_eligibility("tac", TAC_ELIGIBLE)
    calls_before = len(WEB_CALLS)
    result = contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["cached"] is True
    assert len(WEB_CALLS) == calls_before


def test_dispute_forces_recheck(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    contract.check_eligibility("tac", TAC_ELIGIBLE)
    disputed = contract.dispute_eligibility("tac", TAC_ELIGIBLE, "wrong amount?")
    assert disputed["disputed"] is True
    assert disputed["disputes"] == 1
    calls_before = len(WEB_CALLS)
    result = contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert result["cached"] is False
    assert len(WEB_CALLS) > calls_before


def test_fetch_404_writes_nothing(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (404, "not found")
    with pytest.raises(Exception):
        contract.check_eligibility("tac", TAC_ELIGIBLE)
    view = contract.get_eligibility("tac", TAC_ELIGIBLE)
    assert view["verdict"] == "unchecked"
    assert contract.get_stats()["check_count"] == 0


def test_unparseable_body_writes_nothing(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, "{not json")
    with pytest.raises(Exception):
        contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert contract.get_stats()["check_count"] == 0


def test_validator_disagreement_writes_nothing(oracle):
    contract, _ = oracle
    _add_tac(contract)
    # Leader sees the eligible shard; the validator's re-fetch sees a
    # shard without the wallet — signals disagree, no write.
    WEB_RESPONSES[TAC_SHARD_URL] = [
        (200, tac_shard_json()),
        (200, '{"root": "0x00", "claims": {}}'),
    ]
    with pytest.raises(RuntimeError):
        contract.check_eligibility("tac", TAC_ELIGIBLE)
    assert contract.get_stats()["check_count"] == 0
    assert contract.get_eligibility("tac", TAC_ELIGIBLE)["verdict"] == "unchecked"


# -- checking: HYPE json_list_post ----------------------------------------


def test_check_hype_eligible_via_post(oracle):
    contract, _ = oracle
    _add_hype(contract)
    POST_RESPONSES[HYPE_URL] = (200, hype_genesis_json())
    result = contract.check_eligibility("hyperliquid-genesis", HYPE_ELIGIBLE)
    assert result["verdict"] == "eligible"
    assert result["amount_str"] == HYPE_AMOUNT
    assert HYPE_URL in POST_CALLS


def test_check_hype_not_eligible(oracle):
    contract, _ = oracle
    _add_hype(contract)
    POST_RESPONSES[HYPE_URL] = (200, hype_genesis_json())
    result = contract.check_eligibility("hyperliquid-genesis", TAC_ABSENT)
    assert result["verdict"] == "not_eligible"


# -- views / stats ----------------------------------------------------------


def test_stats_and_is_eligible(oracle):
    contract, _ = oracle
    _add_tac(contract)
    WEB_RESPONSES[TAC_SHARD_URL] = (200, tac_shard_json())
    assert contract.is_eligible("tac", TAC_ELIGIBLE) is False
    contract.check_eligibility("tac", TAC_ELIGIBLE)
    contract.check_eligibility("tac", TAC_ABSENT)
    assert contract.is_eligible("tac", TAC_ELIGIBLE) is True
    assert contract.is_eligible("tac", TAC_ABSENT) is False
    stats = contract.get_stats()
    assert stats["eligible"] == 1
    assert stats["not_eligible"] == 1
    assert stats["check_count"] == 2
    entries = contract.list_entries(0, 10)
    assert entries["total"] == 2
