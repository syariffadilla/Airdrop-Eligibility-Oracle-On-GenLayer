"""Pure-logic tests: no GenLayer stub needed, plain pytest."""

import pytest

from oracle_logic import (
    derive_signals,
    lookup_eligibility,
    normalize_project_id,
    normalize_wallet,
    render_source_url,
    verdict_from_signals,
)

TAC_ROOT = "0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10"
TAC_ELIGIBLE = "0x00000000002b00d647a4c78670134888afbc6b5c"
TAC_AMOUNT = "14784700000000000"
TAC_ABSENT = "0x0000000000000000000000000000000000000001"
HYPE_ELIGIBLE = "0x000000000077cdff30a1b5d7c12f3587f921e519"

TAC_SHARD = (
    '{"root": "%s", "claims": {"%s": {"index": 0, "amount": "%s", "proof": []}}}'
    % (TAC_ROOT, TAC_ELIGIBLE, TAC_AMOUNT)
)
HYPE_GENESIS = (
    '{"genesis": {"userBalances": [["%s", "1819.26"]]}}' % HYPE_ELIGIBLE
)


# -- normalize_wallet ---------------------------------------------------


def test_normalize_wallet_lowercases_and_accepts():
    assert (
        normalize_wallet("0x00000000002B00D647A4C78670134888AFBC6B5C")
        == TAC_ELIGIBLE
    )


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "0x123",
        "00000000002b00d647a4c78670134888afbc6b5c",
        "0x" + "zz" * 20,
        "0x" + "ab" * 19,
        "0x" + "ab" * 21,
        123,
    ],
)
def test_normalize_wallet_rejects(bad):
    with pytest.raises(ValueError):
        normalize_wallet(bad)


# -- normalize_project_id -----------------------------------------------


def test_normalize_project_id():
    assert normalize_project_id(" TAC ") == "tac"
    assert normalize_project_id("hyperliquid-genesis") == "hyperliquid-genesis"


@pytest.mark.parametrize(
    "bad", ["", "   ", "has space", "has_underscore", "-lead", "trail-", "a" * 65]
)
def test_normalize_project_id_rejects(bad):
    with pytest.raises(ValueError):
        normalize_project_id(bad)


# -- render_source_url ----------------------------------------------------


def test_render_source_url_shard_and_address():
    template = "https://example.com/proofs/{shard}.json"
    assert (
        render_source_url(template, TAC_ELIGIBLE)
        == "https://example.com/proofs/00.json"
    )
    template = "https://example.com/check/{address}"
    assert render_source_url(template, TAC_ELIGIBLE) == (
        "https://example.com/check/" + TAC_ELIGIBLE
    )


def test_render_source_url_rejects_non_http():
    with pytest.raises(ValueError):
        render_source_url("ftp://example.com/{address}", TAC_ELIGIBLE)


# -- lookup_eligibility ---------------------------------------------------


def test_lookup_json_map_hit_and_root():
    import json

    found, amount, root = lookup_eligibility(
        json.loads(TAC_SHARD), TAC_ELIGIBLE, "json_map"
    )
    assert found is True
    assert amount == TAC_AMOUNT
    assert root == TAC_ROOT


def test_lookup_json_map_miss_keeps_root():
    import json

    found, amount, root = lookup_eligibility(
        json.loads(TAC_SHARD), TAC_ABSENT, "json_map"
    )
    assert found is False
    assert amount == ""
    assert root == TAC_ROOT


def test_lookup_json_map_flat_map():
    found, amount, root = lookup_eligibility(
        {TAC_ELIGIBLE: "42"}, TAC_ELIGIBLE, "json_map"
    )
    assert (found, amount, root) == (True, "42", "")


def test_lookup_json_list_post_hit_and_miss():
    import json

    found, amount, root = lookup_eligibility(
        json.loads(HYPE_GENESIS), HYPE_ELIGIBLE, "json_list_post"
    )
    assert (found, amount, root) == (True, "1819.26", "")
    found, amount, _ = lookup_eligibility(
        json.loads(HYPE_GENESIS), TAC_ABSENT, "json_list_post"
    )
    assert (found, amount) == (False, "")


def test_lookup_unknown_checker_type_rejects():
    with pytest.raises(ValueError):
        lookup_eligibility({}, TAC_ELIGIBLE, "api_get")


# -- derive_signals / verdict ---------------------------------------------


def _signals(**overrides):
    base = {
        "project_id": "tac",
        "wallet": TAC_ELIGIBLE,
        "eligible": False,
        "amount_str": "",
        "source_url": "https://example.com/00.json",
        "status_code": 200,
        "checker_type": "json_map",
        "source_root": "",
        "parse_ok": True,
    }
    base.update(overrides)
    return base


def test_verdict_eligible_not_eligible_unchecked():
    assert verdict_from_signals(_signals(eligible=True)) == "eligible"
    assert (
        verdict_from_signals(_signals(eligible=False)) == "not_eligible"
    )
    assert (
        verdict_from_signals(_signals(parse_ok=False)) == "unchecked"
    )


def test_derive_tac_hit_is_eligible():
    signals = derive_signals(
        "tac",
        TAC_ELIGIBLE,
        "json_map",
        "https://example.com/00.json",
        200,
        TAC_SHARD,
    )
    assert signals["parse_ok"] is True
    assert signals["eligible"] is True
    assert signals["amount_str"] == TAC_AMOUNT
    assert signals["source_root"] == TAC_ROOT
    assert verdict_from_signals(signals) == "eligible"


def test_derive_tac_miss_is_not_eligible():
    signals = derive_signals(
        "tac",
        TAC_ABSENT,
        "json_map",
        "https://example.com/00.json",
        200,
        TAC_SHARD,
    )
    assert signals["parse_ok"] is True
    assert signals["eligible"] is False
    assert verdict_from_signals(signals) == "not_eligible"


def test_derive_hype_hit():
    signals = derive_signals(
        "hyperliquid-genesis",
        HYPE_ELIGIBLE,
        "json_list_post",
        "https://api.hyperliquid.xyz/info",
        200,
        HYPE_GENESIS,
    )
    assert signals["eligible"] is True
    assert signals["amount_str"] == "1819.26"
    assert verdict_from_signals(signals) == "eligible"


def test_derive_non_200_is_unchecked():
    signals = derive_signals(
        "tac", TAC_ELIGIBLE, "json_map", "https://example.com/00.json", 404, ""
    )
    assert signals["parse_ok"] is False
    assert verdict_from_signals(signals) == "unchecked"


def test_derive_malformed_json_is_unchecked():
    signals = derive_signals(
        "tac",
        TAC_ELIGIBLE,
        "json_map",
        "https://example.com/00.json",
        200,
        "{not json",
    )
    assert signals["parse_ok"] is False
    assert verdict_from_signals(signals) == "unchecked"


def test_derive_unknown_checker_is_unchecked():
    signals = derive_signals(
        "tac",
        TAC_ELIGIBLE,
        "api_get",
        "https://example.com/00.json",
        200,
        TAC_SHARD,
    )
    assert signals["parse_ok"] is False
    assert verdict_from_signals(signals) == "unchecked"
