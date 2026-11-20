// Eligibility Oracle client library: thin wrapper around genlayer-js.
// Adapted from the SafeLink demo (same patterns, same chain).
// Reads work without a wallet. The check write needs an injected
// wallet (MetaMask / Rabby) switched to GenLayer Studionet, chain 61999.
// Testnet only: test GEN, no real value.
//
// Wallet note: this does NOT call genlayer-js client.connect(), which
// requires the GenLayer MetaMask Snap. ensureStudionet() adds/switches
// the network with the standard wallet_addEthereumChain /
// wallet_switchEthereumChain requests instead.
//
// The Studio explorer for Studionet is
// https://explorer-studio.genlayer.com - NOT the vercel.app URL
// shipped in genlayer-js's studionet chain definition, so wallet
// setup and explorer links use the Studio explorer explicitly.
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";

export const GEN = 10n ** 18n;
export const CHAIN = studionet;
export const EXPLORER = "https://explorer-studio.genlayer.com";

export const txUrl = (hash) => `${EXPLORER}/tx/${hash}`;
export const addressUrl = (address) => `${EXPLORER}/address/${address}`;

// ------------------------------------------------------------------ clients

export function readClient() {
  return createClient({ chain: CHAIN });
}

/** Client signing with a local private key (burner / script account). */
export function keyClient(privateKey) {
  const account = createAccount(privateKey);
  return { client: createClient({ chain: CHAIN, account }), address: account.address, account };
}

export function newBurnerKey() {
  return generatePrivateKey();
}

/** Client signing through an injected wallet (MetaMask / Rabby). */
export async function walletClient(provider) {
  const [address] = await provider.request({ method: "eth_requestAccounts" });
  await ensureStudionet(provider);
  const client = createClient({ chain: CHAIN, account: address, provider });
  return { client, address };
}

/**
 * Add/switch the wallet to GenLayer Studionet. Unlike genlayer-js connect(), this does
 * not require the GenLayer MetaMask Snap, which many wallets (or users) reject.
 */
async function ensureStudionet(provider) {
  const chainId = "0x" + CHAIN.id.toString(16);
  const current = await provider.request({ method: "eth_chainId" });
  if (current === chainId) return;
  try {
    await provider.request({ method: "wallet_switchEthereumChain", params: [{ chainId }] });
  } catch (e) {
    if (e?.code !== 4902 && !/unrecognized|not added|unknown chain/i.test(e?.message || "")) throw e;
    await provider.request({
      method: "wallet_addEthereumChain",
      params: [{
        chainId,
        chainName: CHAIN.name,
        rpcUrls: CHAIN.rpcUrls.default.http,
        nativeCurrency: CHAIN.nativeCurrency,
        blockExplorerUrls: [EXPLORER],
      }],
    });
  }
}

export async function balanceOf(client, address) {
  return client.getBalance({ address });
}

// ------------------------------------------------------------------ calls

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** View call with a few retries: the public Studio RPC occasionally drops a request
 * (seen in the browser as a CORS/"Failed to fetch" error) right after a write. */
export async function read(client, address, functionName, args = [], attempts = 4) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try {
      return await client.readContract({ address, functionName, args });
    } catch (e) {
      last = e;
      const msg = String(e?.details || e?.message || "");
      if (/execution failed/i.test(msg)) throw e; // contract-level error (e.g. bad wallet): don't retry
      await sleep(1500 * (i + 1));
    }
  }
  throw last;
}

/** Pull the useful bits out of a GenLayer receipt. */
export function summarizeReceipt(receipt) {
  const lr0 = receipt?.consensus_data?.leader_receipt;
  const lr = Array.isArray(lr0) ? lr0[0] : lr0;
  let error = null;
  let returned = null;
  const res = lr?.result;
  if (res && typeof res === "object") {
    if (res.status === "return") returned = res.payload?.readable ?? null;
    else error = res.payload?.readable ?? res.payload ?? res.status;
  } else if (typeof res === "string") {
    returned = res;
  }
  if (!error && lr?.execution_result && lr.execution_result !== "SUCCESS") {
    error = lr?.genvm_result?.stderr || lr.execution_result;
  }
  const consensus =
    receipt?.result_name ?? receipt?.resultName ?? receipt?.consensus_result ?? null;
  // An UNDETERMINED tx is not an error: validators could not agree, so the
  // contract wrote nothing. Report it as such, never as a crash.
  const undetermined =
    String(consensus).toUpperCase() === "UNDETERMINED" ||
    String(receipt?.status_name ?? receipt?.statusName ?? "").toUpperCase() === "UNDETERMINED";
  if (undetermined) {
    error = null;
    returned = null;
  }
  // check_eligibility returns the stored entry as a JSON string in the readable
  // payload; parse it so callers get the dict directly.
  if (typeof returned === "string" && returned.trim().startsWith("{")) {
    try {
      returned = JSON.parse(returned);
    } catch {
      /* keep the raw string */
    }
  }
  return {
    hash: receipt?.hash,
    status: receipt?.status_name ?? receipt?.statusName ?? String(receipt?.status),
    consensus,
    execution: lr?.execution_result ?? null,
    ok: (lr?.execution_result ?? "SUCCESS") === "SUCCESS" && !error && !undetermined,
    undetermined,
    returned,
    error,
    votes: receipt?.consensus_data?.votes ?? null,
  };
}

/**
 * Send a write transaction and wait until it is FINALIZED - the terminal state
 * for both ACCEPTED and UNDETERMINED outcomes. Waiting for ACCEPTED alone would
 * hang forever on an undetermined check (validators disagreed, nothing written).
 * onUpdate(stage, info) is called with "sent" (hash) and "finalized" (summary).
 */
export async function write(client, address, functionName, args = [], value = 0n, onUpdate = () => {}, opts = {}) {
  const hash = await client.writeContract({ address, functionName, args, value: BigInt(value) });
  onUpdate("sent", { hash });
  const receipt = await client.waitForTransactionReceipt({
    hash,
    status: TransactionStatus.FINALIZED,
    interval: opts.interval ?? 4000,
    retries: opts.retries ?? 150,
  });
  const summary = summarizeReceipt(receipt);
  summary.hash = summary.hash || hash;
  onUpdate("finalized", summary);
  return summary;
}

// ------------------------------------------------------------------ contract API

export const api = {
  stats: (c, a) => read(c, a, "get_stats"),
  projects: (c, a) => read(c, a, "list_projects"),
  eligibility: (c, a, projectId, wallet) => read(c, a, "get_eligibility", [String(projectId), String(wallet)]),
  entry: (c, a, projectId, wallet) => read(c, a, "get_entry", [String(projectId), String(wallet)]),
  isEligible: (c, a, projectId, wallet) => read(c, a, "is_eligible", [String(projectId), String(wallet)]),
  entries: (c, a, offset = 0, limit = 20) => read(c, a, "list_entries", [Number(offset), Number(limit)]),

  /** Write: runs a full consensus round (or returns the fresh cached entry). */
  checkEligibility: (c, a, projectId, wallet, cb) =>
    write(c, a, "check_eligibility", [String(projectId), String(wallet)], 0n, cb),
  /** Write: anyone may dispute a stored verdict; the next check re-runs consensus. */
  disputeEligibility: (c, a, projectId, wallet, reason, cb) =>
    write(c, a, "dispute_eligibility", [String(projectId), String(wallet), String(reason)], 0n, cb),
  /** Write: marks the entry disputed ("recheck requested") so the next check re-runs consensus. */
  requestRecheck: (c, a, projectId, wallet, cb) =>
    write(c, a, "request_recheck", [String(projectId), String(wallet)], 0n, cb),
};
