# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Airdrop Eligibility Oracle — is wallet W eligible for airdrop P,
and for how much?

One contract, any airdrop with a public eligibility source. Any
account can ask the contract to check a wallet; the leader fetches the
project's own eligibility source, every validator independently
re-fetches it and re-derives the same signals, and a verdict is
written ONLY when they agree exactly on the compared signal fields.
Disagreement means no write (the transaction goes undetermined) — an
eligibility verdict is never written on one node's word alone, and a
wallet is never auto-marked eligible on disagreement.

The verdict is a DETERMINISTIC lookup over the project's published
allocation data (see verdict_from_signals). No LLM is called anywhere
in v1: eligibility here is checkable facts (the wallet is or is not
in the project's own list), not an LLM opinion. That is the whole
point of the primitive — the same wallet checked twice gives the same
verdict, and any reviewer can re-derive it by hand from the stored
evidence.

Anti-scam rule: eligibility can only come from the project's own
registered source URL. The contract renders the URL from the
admin-curated checker config; a claim page on any other domain can
never produce ELIGIBLE, because no other URL is ever fetched.

Target: stable Studionet, GenVM runner py-genlayer v0.2.5
(1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6) — same as
SafeLink. See SafeLink's VERSIONS.md for how that hash was verified.
Do NOT deploy this file to Studio-dev / v0.6 without re-pinning the
header.

The pure functions below (normalize_wallet, normalize_project_id,
render_source_url, _lookup_json_map, _lookup_json_list_post,
lookup_eligibility, derive_signals, verdict_from_signals) are
byte-identical copies of contracts/oracle_logic.py, which is
unit-tested with plain pytest. They are duplicated here because a
single-file GenLayer contract cannot import a sibling module on-chain.
tests/test_contract_sync.py fails the build if the copies drift.
"""

import json

from genlayer import *

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

DEFAULT_TTL_CHECKS = 1000
MAX_LIST_LIMIT = 100

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


from genlayer import allow_storage
from genlayer.gl.vm import UserError


@allow_storage
class ProjectConfig:
    """One registered airdrop checker. Stored in TreeMap[str, ProjectConfig]."""

    project_id: str
    display_name: str
    token_symbol: str
    checker_type: str
    source_url_template: str
    method: str
    body_template: str
    claim_url: str
    status: str

    def __init__(
        self,
        project_id="",
        display_name="",
        token_symbol="",
        checker_type="",
        source_url_template="",
        method="GET",
        body_template="",
        claim_url="",
        status="active",
    ):
        self.project_id = project_id
        self.display_name = display_name
        self.token_symbol = token_symbol
        self.checker_type = checker_type
        self.source_url_template = source_url_template
        self.method = method
        self.body_template = body_template
        self.claim_url = claim_url
        self.status = status


@allow_storage
class Entry:
    """One eligibility verdict. Stored as the value of TreeMap[str, Entry]."""

    project_id: str
    wallet: str
    eligible: bool
    amount_str: str
    source_url: str
    source_root: str
    status_code: u64
    checker_type: str
    checked_seq: u64
    disputes: u64
    last_dispute_reason: str
    disputed: bool

    def __init__(
        self,
        project_id="",
        wallet="",
        eligible=False,
        amount_str="",
        source_url="",
        source_root="",
        status_code=0,
        checker_type="",
        checked_seq=0,
        disputes=0,
        last_dispute_reason="",
        disputed=False,
    ):
        self.project_id = project_id
        self.wallet = wallet
        self.eligible = eligible
        self.amount_str = amount_str
        self.source_url = source_url
        self.source_root = source_root
        self.status_code = status_code
        self.checker_type = checker_type
        self.checked_seq = checked_seq
        self.disputes = disputes
        self.last_dispute_reason = last_dispute_reason
        self.disputed = disputed


@allow_storage
class EligibilityOracle(gl.Contract):
    admin: Address
    projects: TreeMap[str, ProjectConfig]
    project_order: DynArray[str]
    # DynArray has no verified remove/clear, so removal is a tombstone:
    # the id stays in the list but is filtered out of every snapshot.
    # TreeMap.get is the verified lookup used for the tombstones.
    disabled_projects: TreeMap[str, bool]
    entries: TreeMap[str, Entry]
    entry_order: DynArray[str]
    check_count: u64
    eligible_count: u64
    not_eligible_count: u64
    total_disputes: u64
    ttl_checks: u64

    def __init__(self):
        self.admin = gl.message.sender_address
        self.check_count = 0
        self.eligible_count = 0
        self.not_eligible_count = 0
        self.total_disputes = 0
        self.ttl_checks = DEFAULT_TTL_CHECKS

    # -- internal helpers (deterministic, no nondet calls) ------------

    def _require_admin(self):
        if gl.message.sender_address != self.admin:
            raise UserError("Airdrop Oracle: only admin")

    def _normalize_wallet_or_raise(self, raw_wallet: str) -> str:
        try:
            return normalize_wallet(raw_wallet)
        except ValueError as exc:
            raise UserError("Airdrop Oracle: invalid wallet: " + str(exc))

    def _normalize_project_or_raise(self, raw_project_id: str) -> str:
        try:
            return normalize_project_id(raw_project_id)
        except ValueError as exc:
            raise UserError(
                "Airdrop Oracle: invalid project_id: " + str(exc)
            )

    def _entry_key(self, project_id: str, wallet: str) -> str:
        return project_id + "|" + wallet

    def _is_fresh(self, entry: Entry) -> bool:
        if entry.disputed:
            return False
        return (self.check_count - entry.checked_seq) < self.ttl_checks

    def _increment_counter(self, eligible: bool):
        if eligible:
            self.eligible_count += 1
        else:
            self.not_eligible_count += 1

    def _decrement_counter(self, eligible: bool):
        if eligible and self.eligible_count > 0:
            self.eligible_count -= 1
        elif not eligible and self.not_eligible_count > 0:
            self.not_eligible_count -= 1

    def _project_dict(self, config: ProjectConfig) -> dict:
        return {
            "project_id": config.project_id,
            "display_name": config.display_name,
            "token_symbol": config.token_symbol,
            "checker_type": config.checker_type,
            "source_url_template": config.source_url_template,
            "method": config.method,
            "body_template": config.body_template,
            "claim_url": config.claim_url,
            "status": config.status,
            "disabled": self.disabled_projects.get(config.project_id, False),
        }

    def _entry_dict(self, entry: Entry, cached: bool = False) -> dict:
        return {
            "project_id": entry.project_id,
            "wallet": entry.wallet,
            "verdict": verdict_from_signals(
                {
                    "parse_ok": True,
                    "eligible": entry.eligible,
                }
            ),
            "eligible": entry.eligible,
            "amount_str": entry.amount_str,
            "source_url": entry.source_url,
            "source_root": entry.source_root,
            "status_code": entry.status_code,
            "checker_type": entry.checker_type,
            "fresh": self._is_fresh(entry),
            "cached": cached,
            "checked_seq": entry.checked_seq,
            "disputes": entry.disputes,
            "last_dispute_reason": entry.last_dispute_reason,
            "disputed": entry.disputed,
        }

    def _active_project(self, project_id: str):
        config = self.projects.get(project_id, None)
        if config is None:
            raise UserError("Airdrop Oracle: unknown project")
        if self.disabled_projects.get(project_id, False):
            raise UserError("Airdrop Oracle: project removed")
        if config.status != "active":
            raise UserError("Airdrop Oracle: project paused")
        return config

    def _dispute(self, key: str, reason: str) -> dict:
        entry = self.entries.get(key, None)
        if entry is None:
            raise UserError("Airdrop Oracle: unknown check")
        entry.disputed = True
        entry.disputes += 1
        entry.last_dispute_reason = reason[:200]
        self.total_disputes += 1
        self.entries[key] = entry
        return self._entry_dict(entry)

    # -- views ---------------------------------------------------------

    @gl.public.view
    def get_eligibility(self, project_id: str, wallet: str) -> dict:
        project_id = self._normalize_project_or_raise(project_id)
        wallet = self._normalize_wallet_or_raise(wallet)
        entry = self.entries.get(self._entry_key(project_id, wallet), None)
        if entry is None:
            return {
                "project_id": project_id,
                "wallet": wallet,
                "verdict": VERDICT_UNCHECKED,
                "eligible": False,
                "amount_str": "",
                "fresh": False,
                "cached": False,
            }
        return self._entry_dict(entry)

    @gl.public.view
    def get_entry(self, project_id: str, wallet: str) -> dict:
        return self.get_eligibility(project_id, wallet)

    @gl.public.view
    def is_eligible(self, project_id: str, wallet: str) -> bool:
        project_id = self._normalize_project_or_raise(project_id)
        wallet = self._normalize_wallet_or_raise(wallet)
        entry = self.entries.get(self._entry_key(project_id, wallet), None)
        if entry is None:
            return False
        return entry.eligible and self._is_fresh(entry)

    @gl.public.view
    def list_entries(self, offset: u64, limit: u64) -> dict:
        total = len(self.entry_order)
        if limit == 0 or limit > MAX_LIST_LIMIT:
            limit = MAX_LIST_LIMIT
        result = []
        if offset < total:
            i = total - offset
            count = 0
            while i > 0 and count < limit:
                i -= 1
                key = self.entry_order[i]
                entry = self.entries.get(key, None)
                if entry is not None:
                    result.append(self._entry_dict(entry))
                    count += 1
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": result,
        }

    @gl.public.view
    def list_projects(self) -> dict:
        result = []
        for project_id in self.project_order:
            if self.disabled_projects.get(project_id, False):
                continue
            config = self.projects.get(project_id, None)
            if config is not None:
                result.append(self._project_dict(config))
        return {"total": len(result), "projects": result}

    @gl.public.view
    def get_project(self, project_id: str) -> dict:
        project_id = self._normalize_project_or_raise(project_id)
        config = self.projects.get(project_id, None)
        if config is None or self.disabled_projects.get(project_id, False):
            raise UserError("Airdrop Oracle: unknown project")
        return self._project_dict(config)

    @gl.public.view
    def get_stats(self) -> dict:
        return {
            "total_entries": len(self.entry_order),
            "total_projects": len(self.project_order),
            "check_count": self.check_count,
            "eligible": self.eligible_count,
            "not_eligible": self.not_eligible_count,
            "total_disputes": self.total_disputes,
            "ttl_checks": self.ttl_checks,
            "admin": str(self.admin),
        }

    # -- writes: checking ----------------------------------------------

    @gl.public.write
    def check_eligibility(self, project_id: str, wallet: str) -> dict:
        project_id = self._normalize_project_or_raise(project_id)
        wallet = self._normalize_wallet_or_raise(wallet)
        config = self._active_project(project_id)
        key = self._entry_key(project_id, wallet)
        existing = self.entries.get(key, None)
        # Fresh, non-disputed entries are returned without a new
        # consensus round. Disputed entries always re-check.
        if existing is not None and self._is_fresh(existing):
            return self._entry_dict(existing, cached=True)

        # Snapshot consensus inputs BEFORE the nondet block. Storage is
        # never read or written inside leader_fn / validator_fn.
        checker_type = config.checker_type
        method = config.method
        body_template = config.body_template
        source_url = render_source_url(config.source_url_template, wallet)

        def leader_fn():
            if method == "POST":
                body = body_template.replace("{address}", wallet)
                response = gl.nondet.web.post(source_url, body=body)
            else:
                response = gl.nondet.web.get(source_url)
            # The real SDK (py-lib-genlayer-std v0.2.16, Response
            # dataclass) exposes the field as `response.status`, and
            # `body` may be None. Same correction SafeLink learned.
            if response.status != 200:
                raise UserError(
                    "Airdrop Oracle: fetch failed with status "
                    + str(response.status)
                )
            raw_body = response.body or b""
            if isinstance(raw_body, bytes):
                body_text = raw_body.decode("utf-8", "ignore")
            else:
                body_text = str(raw_body)
            signals = derive_signals(
                project_id,
                wallet,
                checker_type,
                source_url,
                response.status,
                body_text,
            )
            if not signals["parse_ok"]:
                raise UserError(
                    "Airdrop Oracle: eligibility source unparseable"
                )
            return signals

        def validator_fn(leaders_res):
            # Leader errors are not agreed on in v1: a failed fetch
            # disagrees and retries with another leader instead of
            # writing anything. See SafeLink's CONSENSUS.md.
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = leader_fn()
            leader = leaders_res.calldata
            for key in COMPARED_SIGNAL_KEYS:
                if mine.get(key) != leader.get(key):
                    return False
            return True

        signals = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        verdict = verdict_from_signals(signals)

        self.check_count += 1
        entry = Entry(
            project_id=project_id,
            wallet=wallet,
            eligible=signals["eligible"],
            amount_str=signals["amount_str"],
            source_url=signals["source_url"],
            source_root=signals["source_root"],
            status_code=signals["status_code"],
            checker_type=signals["checker_type"],
            checked_seq=self.check_count,
            disputes=0 if existing is None else existing.disputes,
            last_dispute_reason=(
                "" if existing is None else existing.last_dispute_reason
            ),
            disputed=False,
        )
        if existing is None:
            self.entry_order.append(key)
        else:
            self._decrement_counter(existing.eligible)
        self._increment_counter(signals["eligible"])
        self.entries[key] = entry
        return self._entry_dict(entry)

    # -- writes: disputes -----------------------------------------------

    @gl.public.write
    def dispute_eligibility(
        self, project_id: str, wallet: str, reason: str
    ) -> dict:
        project_id = self._normalize_project_or_raise(project_id)
        wallet = self._normalize_wallet_or_raise(wallet)
        return self._dispute(self._entry_key(project_id, wallet), reason)

    @gl.public.write
    def request_recheck(self, project_id: str, wallet: str) -> dict:
        project_id = self._normalize_project_or_raise(project_id)
        wallet = self._normalize_wallet_or_raise(wallet)
        return self._dispute(
            self._entry_key(project_id, wallet), "recheck requested"
        )

    # -- writes: admin ---------------------------------------------------

    def _validate_config(
        self, checker_type: str, method: str, source_url_template: str
    ):
        if checker_type not in CHECKER_TYPES:
            raise UserError("Airdrop Oracle: unknown checker_type")
        if method not in ("GET", "POST"):
            raise UserError("Airdrop Oracle: method must be GET or POST")
        if checker_type == CHECKER_JSON_LIST_POST and method != "POST":
            raise UserError(
                "Airdrop Oracle: json_list_post needs POST"
            )
        if not source_url_template.startswith(
            "http://"
        ) and not source_url_template.startswith("https://"):
            raise UserError("Airdrop Oracle: source_url must be http(s)")

    @gl.public.write
    def add_project(
        self,
        project_id: str,
        display_name: str,
        token_symbol: str,
        checker_type: str,
        source_url_template: str,
        method: str,
        body_template: str,
        claim_url: str,
    ) -> dict:
        self._require_admin()
        project_id = self._normalize_project_or_raise(project_id)
        self._validate_config(checker_type, method, source_url_template)
        existing = self.projects.get(project_id, None)
        if existing is not None and not self.disabled_projects.get(
            project_id, False
        ):
            raise UserError("Airdrop Oracle: project already exists")
        config = ProjectConfig(
            project_id=project_id,
            display_name=display_name,
            token_symbol=token_symbol,
            checker_type=checker_type,
            source_url_template=source_url_template,
            method=method,
            body_template=body_template,
            claim_url=claim_url,
            status="active",
        )
        self.projects[project_id] = config
        if existing is None:
            self.project_order.append(project_id)
        # Re-adding a previously removed project clears its tombstone.
        self.disabled_projects[project_id] = False
        return self._project_dict(config)

    @gl.public.write
    def update_project(
        self,
        project_id: str,
        display_name: str,
        token_symbol: str,
        checker_type: str,
        source_url_template: str,
        method: str,
        body_template: str,
        claim_url: str,
    ) -> dict:
        self._require_admin()
        project_id = self._normalize_project_or_raise(project_id)
        self._validate_config(checker_type, method, source_url_template)
        config = self.projects.get(project_id, None)
        if config is None or self.disabled_projects.get(project_id, False):
            raise UserError("Airdrop Oracle: unknown project")
        config.display_name = display_name
        config.token_symbol = token_symbol
        config.checker_type = checker_type
        config.source_url_template = source_url_template
        config.method = method
        config.body_template = body_template
        config.claim_url = claim_url
        self.projects[project_id] = config
        return self._project_dict(config)

    @gl.public.write
    def remove_project(self, project_id: str) -> dict:
        self._require_admin()
        project_id = self._normalize_project_or_raise(project_id)
        config = self.projects.get(project_id, None)
        if config is None:
            raise UserError("Airdrop Oracle: unknown project")
        # Tombstone, not a physical remove: DynArray has no verified
        # remove/clear/pop.
        self.disabled_projects[project_id] = True
        return self.list_projects()

    @gl.public.write
    def pause_project(self, project_id: str) -> dict:
        self._require_admin()
        project_id = self._normalize_project_or_raise(project_id)
        config = self._active_project(project_id)
        config.status = "paused"
        self.projects[project_id] = config
        return self._project_dict(config)

    @gl.public.write
    def unpause_project(self, project_id: str) -> dict:
        self._require_admin()
        project_id = self._normalize_project_or_raise(project_id)
        config = self.projects.get(project_id, None)
        if config is None or self.disabled_projects.get(project_id, False):
            raise UserError("Airdrop Oracle: unknown project")
        config.status = "active"
        self.projects[project_id] = config
        return self._project_dict(config)

    @gl.public.write
    def set_ttl_checks(self, ttl: u64) -> dict:
        self._require_admin()
        if ttl == 0:
            raise UserError("Airdrop Oracle: ttl must be > 0")
        self.ttl_checks = ttl
        return {"ttl_checks": self.ttl_checks}
