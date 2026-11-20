"""Pure, deterministic Airdrop Eligibility Oracle logic.

Stdlib only — no GenLayer imports — so this module is unit-testable with
plain pytest and no GenVM. The contract file
``contracts/eligibility_oracle.py`` contains byte-identical copies of
these functions (checked by ``tests/test_contract_sync.py``); the
contract is self-contained because a single-file GenLayer contract
cannot import a sibling module on-chain.

Design (see DESIGN.md for the full story):

* The verdict is a DETERMINISTIC lookup over a project's own published
  eligibility source, not an LLM opinion. No LLM is called anywhere in
  v1. Validators re-fetch the source and compare the derived signals
  exactly.
* Only the signal fields listed in ``COMPARED_SIGNAL_KEYS`` are part of
  consensus. ``content_len`` / ``body_sample`` are audit observations
  (sources change between fetches); they are recorded, never compared.
* A verdict is written ONLY on exact agreement. A fetch failure, a
  non-200 status, an unparseable body, or a gated source (login /
  signature wall) writes nothing — the same safe-failure as SafeLink.
  The anti-scam rule holds by construction: eligibility can only come
  from the project's own registered source URL, never from an arbitrary
  claim page, because the contract renders the URL from the
  admin-curated checker config.
* Amounts are kept as the exact raw string from the source (wei string
  for TAC, decimal string for HYPE). No float math on-chain; formatting
  is the frontend's job.
"""

import json

MAX_TEMPLATE_LEN = 2048
BODY_SAMPLE_LEN = 200

CHECKER_JSON_MAP = "json_map"
CHECKER_JSON_LIST_POST = "json_list_post"
CHECKER_TYPES = (CHECKER_JSON_MAP, CHECKER_JSON_LIST_POST)

VERDICT_ELIGIBLE = "eligible"
VERDICT_NOT_ELIGIBLE = "not_eligible"
VERDICT_UNCHECKED = "unchecked"

# Signal fields the validator must agree on exactly. Everything else in
# the signals dict is observation only.
COMPARED_SIGNAL_KEYS = (
    "project_id",
    "wallet",
    "eligible",
    "amount_str",
    "source_url",
    "status_code",
    "checker_type",
    "source_root",
    "parse_ok",
)

_HEX = "0123456789abcdef"


def normalize_wallet(raw_wallet):
    """Normalize a wallet address into its canonical registry key.

    Lower-case ``0x`` + 40 hex chars. Raises ValueError on anything
    else. The contract converts this to UserError.
    """
    if not isinstance(raw_wallet, str):
        raise ValueError("wallet must be a string")
    wallet = raw_wallet.strip().lower()
    if not wallet.startswith("0x"):
        raise ValueError("wallet must start with 0x")
    if len(wallet) != 42:
        raise ValueError("wallet must be 0x + 40 hex chars")
    for ch in wallet[2:]:
        if ch not in _HEX:
            raise ValueError("wallet contains a non-hex character")
    return wallet


def normalize_project_id(raw_project_id):
    """Normalize a project slug: lower-case, [a-z0-9-] only, 1-64 chars.

    Raises ValueError on anything else.
    """
    if not isinstance(raw_project_id, str):
        raise ValueError("project_id must be a string")
    project_id = raw_project_id.strip().lower()
    if not project_id:
        raise ValueError("empty project_id")
    if len(project_id) > 64:
        raise ValueError("project_id too long")
    if project_id.startswith("-") or project_id.endswith("-"):
        raise ValueError("project_id must not start or end with -")
    for ch in project_id:
        if not (
            ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch == "-"
        ):
            raise ValueError("project_id allows only a-z, 0-9 and -")
    return project_id


def render_source_url(template, wallet):
    """Render a checker source URL from its template.

    ``{address}`` is replaced with the lower-case wallet address,
    ``{shard}`` with its first byte (two hex chars, no ``0x``) — the
    TAC sharding scheme. Raises ValueError on a non-http(s) template
    or a template longer than MAX_TEMPLATE_LEN.
    """
    if not isinstance(template, str):
        raise ValueError("source_url template must be a string")
    if len(template) > MAX_TEMPLATE_LEN:
        raise ValueError("source_url template too long")
    url = template.replace("{address}", wallet).replace(
        "{shard}", wallet[2:4]
    )
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("source_url must be http(s)")
    if "{address}" in url or "{shard}" in url:
        raise ValueError("source_url has an unreplaced placeholder")
    return url


def _lookup_json_map(data, wallet):
    """Look a wallet up in a JSON-map source (e.g. TAC proof shards).

    Accepts ``{root, claims: {address: {index, amount, proof}}}`` or a
    flat ``{address: amount}`` / ``{address: {amount}}`` map. Returns
    ``(found, amount_str, source_root)``.
    """
    root = ""
    claims = data
    if isinstance(data, dict):
        root = data.get("root", "") or ""
        if isinstance(data.get("claims"), dict):
            claims = data["claims"]
    if not isinstance(claims, dict):
        return False, "", str(root)
    entry = claims.get(wallet)
    if entry is None:
        return False, "", str(root)
    if isinstance(entry, dict):
        amount = entry.get("amount", "")
    else:
        amount = entry
    return True, str(amount), str(root)


def _lookup_json_list_post(data, wallet):
    """Look a wallet up in a JSON-list source (e.g. Hyperliquid genesis).

    Accepts a bare list of ``[address, amount]`` pairs, or a dict
    holding such a list under ``genesis.userBalances``,
    ``userBalances`` or ``balances``. Returns
    ``(found, amount_str, source_root)`` (root is always "" here).
    """
    pairs = None
    if isinstance(data, list):
        pairs = data
    elif isinstance(data, dict):
        if isinstance(data.get("genesis"), dict) and isinstance(
            data["genesis"].get("userBalances"), list
        ):
            pairs = data["genesis"]["userBalances"]
        elif isinstance(data.get("userBalances"), list):
            pairs = data["userBalances"]
        elif isinstance(data.get("balances"), list):
            pairs = data["balances"]
    if not isinstance(pairs, list):
        return False, "", ""
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        address, amount = pair
        if isinstance(address, str) and address.lower() == wallet:
            return True, str(amount), ""
    return False, "", ""


def lookup_eligibility(data, wallet, checker_type):
    """Look a wallet up in a parsed eligibility source.

    ``data`` is the already-parsed JSON body. Returns
    ``(found, amount_str, source_root)``. Raises ValueError on an
    unknown checker type.
    """
    if checker_type == CHECKER_JSON_MAP:
        return _lookup_json_map(data, wallet)
    if checker_type == CHECKER_JSON_LIST_POST:
        return _lookup_json_list_post(data, wallet)
    raise ValueError("unknown checker_type: " + str(checker_type))


def derive_signals(project_id, wallet, checker_type, source_url, status_code, body):
    """Derive the check signals for one fetched eligibility source.

    ``project_id`` / ``wallet`` must already be normalized, ``body``
    is the decoded source text. Runs identically on leader and
    validator; the validator compares exactly the
    COMPARED_SIGNAL_KEYS fields of the result. A non-200 status or an
    unparseable body yields ``parse_ok`` False and no eligibility —
    the contract treats that as a failed fetch and writes nothing.
    """
    signals = {
        "project_id": project_id,
        "wallet": wallet,
        "eligible": False,
        "amount_str": "",
        "source_url": source_url,
        "status_code": status_code,
        "checker_type": checker_type,
        "source_root": "",
        "parse_ok": False,
        # Observation only — recorded for audit, never compared.
        "content_len": len(body),
        "body_sample": body[:BODY_SAMPLE_LEN],
    }
    if status_code != 200:
        return signals
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return signals
    try:
        found, amount_str, source_root = lookup_eligibility(
            data, wallet, checker_type
        )
    except ValueError:
        return signals
    signals["parse_ok"] = True
    signals["eligible"] = found
    signals["amount_str"] = amount_str
    signals["source_root"] = source_root
    return signals


def verdict_from_signals(signals):
    """Deterministic verdict rule. Pure function of the signals dict.

    eligible: the wallet was found in the project's own source.
    not_eligible: the source fetched and parsed fine, the wallet is
        not in it.
    unchecked: the source could not be fetched or parsed — no verdict
        is written for this case.
    """
    if not signals["parse_ok"]:
        return VERDICT_UNCHECKED
    if signals["eligible"]:
        return VERDICT_ELIGIBLE
    return VERDICT_NOT_ELIGIBLE
