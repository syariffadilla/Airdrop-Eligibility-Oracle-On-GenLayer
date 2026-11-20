"""Test harness: a minimal fake ``genlayer`` module.

Adapted from SafeLink's tests/conftest.py (same stub semantics), with
one addition: ``gl.nondet.web.post`` for the json_list_post checker
(Hyperliquid genesis demo). The real GenLayer SDK / GenVM runner is
NOT installed here, so the contract is loaded with this stub. The stub
emulates the documented semantics just enough to exercise the contract
end to end off-chain:

* ``@gl.public.view`` / ``@gl.public.write`` are identity decorators.
* ``gl.message.sender_address`` is a settable attribute (the caller).
* ``gl.nondet.web.get(url)`` / ``post(url, body=...)`` serve canned
  responses from ``WEB_RESPONSES`` / ``POST_RESPONSES`` and record
  every call in ``WEB_CALLS`` / ``POST_CALLS``.
* ``gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`` calls the leader,
  wraps the result in ``gl.vm.Return``, calls the validator, and returns
  the leader's value only if the validator agrees. Disagreement (or a
  leader error the validator does not agree with) raises RuntimeError —
  the stub's emulation of "transaction undetermined, no state change".
* ``TreeMap`` / ``DynArray`` are dict / list subclasses; ``u64`` etc.
  are plain ``int``; ``Address`` is ``str``.

These are DIRECT-mode tests: they prove the contract's logic, state
machine and validator agreement — they do NOT prove the contract passes
GenVM lint or Studio consensus. That step is still open; see README.md.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "contracts"
sys.path.insert(0, str(CONTRACTS_DIR))

import oracle_logic  # noqa: E402  (pure logic, no GenLayer import)

# ---------------------------------------------------------------- fake gl

WEB_RESPONSES = {}
POST_RESPONSES = {}
WEB_CALLS = []
POST_CALLS = []


class _FakeResponse:
    def __init__(self, status, body):
        # Mirrors the real SDK Response dataclass: fields are `status`
        # (not `status_code`) and `body` (bytes).
        self.status = status
        self.body = body.encode("utf-8") if isinstance(body, str) else body


def _serve(store, calls, key):
    calls.append(key)
    if key not in store:
        return _FakeResponse(404, "not found")
    value = store[key]
    if isinstance(value, list):
        # Consumed in order: lets tests change the source between the
        # leader's fetch and the validator's re-fetch.
        status_code, body = value.pop(0)
    else:
        status_code, body = value
    return _FakeResponse(status_code, body)


class _FakeWeb:
    @staticmethod
    def get(url):
        return _serve(WEB_RESPONSES, WEB_CALLS, url)

    @staticmethod
    def post(url, body=None, headers=None):
        return _serve(POST_RESPONSES, POST_CALLS, url)


class _UserError(Exception):
    pass


class _VMError(Exception):
    pass


class _Return:
    def __init__(self, calldata):
        self.calldata = calldata


class _LeaderError:
    """Non-Return result: the leader raised instead of returning."""

    def __init__(self, error):
        self.error = error


def _run_nondet_unsafe(leader_fn, validator_fn):
    try:
        value = leader_fn()
    except Exception as exc:  # leader raised (e.g. gl.UserError on 404)
        agreed = validator_fn(_LeaderError(exc))
        if agreed:
            raise exc
        raise RuntimeError("consensus failed: leader error not agreed")
    if validator_fn(_Return(value)):
        return value
    raise RuntimeError("consensus failed: validator disagreed")


def _make_fake_genlayer():
    fake = types.ModuleType("genlayer")

    class _TreeMap(dict):
        def __class_getitem__(cls, item):
            return cls

    class _DynArray(list):
        def __class_getitem__(cls, item):
            return cls

    def _storage_default(annotation):
        if annotation is _TreeMap:
            return {}
        if annotation is _DynArray:
            return []
        if annotation is int:
            return 0
        if annotation is bool:
            return False
        if annotation is str:
            return ""
        return None

    class _ContractBase:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)
            orig_init = cls.__init__

            def wrapped_init(self, *args, **kwargs):
                for name, ann in cls.__annotations__.items():
                    setattr(self, name, _storage_default(ann))
                orig_init(self, *args, **kwargs)

            cls.__init__ = wrapped_init

    class _Public:
        @staticmethod
        def view(fn):
            return fn

        @staticmethod
        def write(fn):
            return fn

    class _Message:
        sender_address = "0x00000000000000000000000000000000000000A1"

    fake.public = _Public()
    fake.message = _Message()
    fake.UserError = _UserError
    fake.VMError = _VMError
    fake.allow_storage = lambda cls: cls
    fake.Contract = _ContractBase
    fake.Address = str
    fake.TreeMap = _TreeMap
    fake.DynArray = _DynArray
    fake.u64 = int
    fake.u256 = int
    fake.u32 = int
    fake.i32 = int
    fake.i64 = int
    fake.vm = types.SimpleNamespace(
        Return=_Return,
        Result=_Return,
        UserError=_UserError,
        VMError=_VMError,
        run_nondet_unsafe=_run_nondet_unsafe,
    )
    fake.nondet = types.SimpleNamespace(web=_FakeWeb())
    fake.gl = fake
    fake.__all__ = [
        "gl",
        "allow_storage",
        "Contract",
        "public",
        "message",
        "UserError",
        "VMError",
        "Address",
        "TreeMap",
        "DynArray",
        "u64",
        "u256",
        "u32",
        "i32",
        "i64",
        "vm",
        "nondet",
    ]
    return fake


def load_contract():
    """Load contracts/eligibility_oracle.py with the fake genlayer module."""
    fake = _make_fake_genlayer()
    # The contract imports UserError from the REAL SDK location
    # (genlayer.gl.vm) — the fake must expose that submodule path too.
    # NOTE (15 Nov 2026): real SDK v0.2.5/v0.2.16 has NO gl.UserError;
    # it lives in genlayer.gl.vm. The fake mirrors that.
    gl_mod = types.ModuleType("genlayer.gl")
    vm_mod = types.ModuleType("genlayer.gl.vm")
    vm_mod.UserError = _UserError
    vm_mod.VMError = _VMError
    vm_mod.Return = _Return
    vm_mod.run_nondet_unsafe = _run_nondet_unsafe
    gl_mod.vm = vm_mod
    fake.__path__ = []  # make the fake importable as a package
    sys.modules["genlayer"] = fake
    sys.modules["genlayer.gl"] = gl_mod
    sys.modules["genlayer.gl.vm"] = vm_mod
    spec = importlib.util.spec_from_file_location(
        "oracle_contract", CONTRACTS_DIR / "eligibility_oracle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


def reset_web():
    WEB_RESPONSES.clear()
    POST_RESPONSES.clear()
    WEB_CALLS.clear()
    POST_CALLS.clear()


def set_sender(fake, address):
    fake.message.sender_address = address


ADMIN = "0x00000000000000000000000000000000000000A1"
OTHER = "0x00000000000000000000000000000000000000B2"

# Live-verified demo data (14 Nov 2026, TAC shard 00.json fetched live):
# root 0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10,
# demo ELIGIBLE wallet -> 14784700000000000 wei; shard holds 60 claims.
TAC_ROOT = "0x27451b320d5aa9631f7a3fd8adcfa537db8d792dd49aad9ab0951af0c2986a10"
TAC_ELIGIBLE = "0x00000000002b00d647a4c78670134888afbc6b5c"
TAC_AMOUNT = "14784700000000000"
TAC_ABSENT = "0x0000000000000000000000000000000000000001"
TAC_SHARD_URL = (
    "https://cdn.jsdelivr.net/gh/z0r0z/tacit@1b2eedde8490801c9ef4406020530059162e6d47"
    "/dapp/airdrop/v1/proofs/00.json"
)


def tac_shard_json():
    return json.dumps(
        {
            "root": TAC_ROOT,
            "claims": {
                TAC_ELIGIBLE: {
                    "index": 0,
                    "amount": TAC_AMOUNT,
                    "proof": ["0x" + "ab" * 32],
                }
            },
        }
    )


HYPE_ELIGIBLE = "0x000000000077cdff30a1b5d7c12f3587f921e519"
HYPE_AMOUNT = "1819.26"


def hype_genesis_json():
    return json.dumps(
        {
            "genesis": {
                "userBalances": [[HYPE_ELIGIBLE, HYPE_AMOUNT]],
            }
        }
    )
