// Airdrop Eligibility Oracle - browser app.
// Reads work without a wallet. The check write needs an injected wallet
// (MetaMask / Rabby) switched to GenLayer Studionet, chain 61999.
// Testnet only: test GEN, no real value.
import { CONTRACT_ADDRESS, EXPLORER, REPO_URL } from "./config.js";
import {
  api, readClient, walletClient,
  txUrl, addressUrl, balanceOf,
} from "./lib/oracle.js";

const $ = (id) => document.getElementById(id);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const shortAddr = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : "");
const nowTime = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const groupDigits = (s) => String(s ?? "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
const groupedAmount = (s) => (/^\d+$/.test(String(s ?? "")) ? groupDigits(s) : String(s ?? ""));
let elapsedTimer = null;
function startElapsed() {
  const t0 = Date.now();
  stopElapsed();
  elapsedTimer = setInterval(() => {
    const el = document.getElementById("elapsedTime");
    if (el) {
      const s = Math.floor((Date.now() - t0) / 1000);
      el.textContent = `Elapsed ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    }
  }, 1000);
}
function stopElapsed() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
}

// Demo wallets, verified live 14-15 Nov 2026 (TAC shard 00.json).
const TAC_ELIGIBLE = "0x00000000002b00d647a4c78670134888afbc6b5c";
const TAC_ABSENT = "0x0000000000000000000000000000000000000001";
const TAC_AMOUNT = "14784700000000000";

// Projects the deploy registers. The picker refreshes from
// list_projects once the contract is set; this list is the fallback
// shown before deploy so the page still explains itself.
const KNOWN_PROJECTS = [
  { project_id: "tac", display_name: "TAC", token_symbol: "TAC", checker_type: "json_map", claim_url: "https://tacit.finance/airdrop", status: "active" },
  { project_id: "hyperliquid-genesis", display_name: "Hyperliquid HYPE Genesis", token_symbol: "HYPE", checker_type: "json_list_post", claim_url: "https://app.hyperliquid.xyz/", status: "active", v2: true },
];

const DEPLOYED = Boolean(CONTRACT_ADDRESS);
const rc = DEPLOYED ? readClient() : null;
let wallet = null; // { client, address } once connected
let entriesCache = [];

const VERDICT_CLASS = { eligible: "eligible", not_eligible: "not-eligible", unchecked: "unchecked" };
const VERDICT_LABEL = { eligible: "ELIGIBLE", not_eligible: "NOT ELIGIBLE", unchecked: "UNCHECKED" };
const badge = (v) => `<span class="badge ${VERDICT_CLASS[v] || "unchecked"}">${esc(VERDICT_LABEL[v] || "UNCHECKED")}</span>`;
const boolWord = (b) => (b ? "yes" : "no");

// ------------------------------------------------------------------ data

async function loadStats() {
  if (!DEPLOYED) return;
  try {
    const s = await api.stats(rc, CONTRACT_ADDRESS);
    for (const [k, v] of Object.entries(s)) {
      const el = document.querySelector(`[data-stat="${k}"]`);
      if (el) { el.textContent = String(v); el.classList.remove("loading"); }
    }
    $("statsNote").textContent =
      `TTL ${s.ttl_checks} checks · admin ${shortAddr(s.admin)} (deployer account; admin actions are not in this app) · updated ${nowTime()}`;
  } catch (e) {
    document.querySelectorAll(".stat-num.loading").forEach((el) => el.classList.remove("loading"));
    $("statsNote").textContent = `Could not read stats: ${e.message || e}. The Studio RPC is sometimes slow - try Refresh.`;
  }
}

function renderProjects(list) {
  const sel = $("projectSelect");
  sel.innerHTML = list
    .map((p) => {
      const tag = p.project_id === "hyperliquid-genesis" ? " - v2 candidate, under test, may be unchecked" : "";
      return `<option value="${esc(p.project_id)}">${esc(p.display_name)} (${esc(p.token_symbol)})${tag}</option>`;
    })
    .join("");
  const hype = list.find((p) => p.project_id === "hyperliquid-genesis");
  $("hypeNote").textContent = hype
    ? "Hyperliquid HYPE Genesis is a v2 candidate. The genesis list is about 5 MB per validator fetch, still under test. It may return unchecked. TAC carries v1."
    : "";
}

async function loadProjects() {
  renderProjects(KNOWN_PROJECTS);
  if (!DEPLOYED) return;
  try {
    const list = await api.projects(rc, CONTRACT_ADDRESS);
    if (list.projects && list.projects.length) {
      renderProjects(list.projects.map((p) => ({ ...p, v2: p.project_id === "hyperliquid-genesis" })));
    }
  } catch (e) {
    $("statsNote").textContent = `Could not read projects: ${e.message || e}. Showing the planned list.`;
  }
}

async function loadEntries() {
  const note = $("entriesNote");
  if (!DEPLOYED) return;
  try {
    const list = await api.entries(rc, CONTRACT_ADDRESS, 0, 10);
    entriesCache = list.entries || [];
    renderEntries();
    note.textContent = `${list.total} entr${list.total === 1 ? "y" : "ies"} in the oracle · updated ${nowTime()}`;
  } catch (e) {
    note.textContent = `Could not read entries: ${e.message || e}. The Studio RPC is sometimes slow - try Refresh.`;
  }
}

function renderEntries() {
  const table = $("entriesTable");
  const body = $("entriesBody");
  if (!entriesCache.length) {
    table.hidden = true;
    $("entriesNote").textContent = "No entries yet. Run the first check above.";
    return;
  }
  table.hidden = false;
  body.innerHTML = entriesCache
    .map(
      (e) => `<tr>
        <td>${badge(e.verdict)}</td>
        <td class="mono">${esc(e.project_id)}</td>
        <td><span class="addr-cell"><span class="mono">${esc(shortAddr(e.wallet))}</span><a href="${esc(addressUrl(e.wallet))}" target="_blank" rel="noopener">View</a><button class="copy-btn" type="button" data-copy="${esc(e.wallet)}">Copy</button></span></td>
        <td class="num">${esc(e.amount_str ? groupedAmount(e.amount_str) : "-")}</td>
        <td class="num">${esc(e.checked_seq)}</td>
      </tr>`,
    )
    .join("");
}

// ------------------------------------------------------------------ receipt

function renderReceipt({ entry, source, tx, consensus, votes, note }) {
  const box = $("result");
  const v = entry?.verdict || "unchecked";
  $("resultEmpty").hidden = true;
  box.className = `receipt verdict-${v}`;
  const agree = votes ? Object.values(votes).filter((x) => x === "agree").length : null;
  const total = votes ? Object.keys(votes).length : null;
  box.hidden = false;
  box.innerHTML = `
    <div class="receipt-head">
      <h3>${v === "eligible" ? "Eligible" : v === "not_eligible" ? "Not eligible" : "Unchecked"}</h3>
      ${badge(v)}
    </div>
    <dl>
      <div class="row"><dt>Project</dt><dd>${esc(entry?.project_id || "")}</dd></div>
      <div class="row"><dt>Wallet</dt><dd>${esc(entry?.wallet || "")}</dd></div>
      ${entry?.amount_str ? `<div class="row amount-hero"><dt>Amount</dt><dd>${esc(groupedAmount(entry.amount_str))} <span class="unit">wei</span></dd></div>` : ""}
      ${entry?.source_root ? `<div class="row"><dt>Source root</dt><dd>${esc(entry.source_root)}</dd></div>` : ""}
      ${entry?.source_url ? `<div class="row"><dt>Source URL</dt><dd>${esc(entry.source_url)}</dd></div>` : ""}
      <div class="row"><dt>Status code</dt><dd>${esc(entry?.status_code ?? "")}</dd></div>
      <div class="row"><dt>Checker</dt><dd>${esc(entry?.checker_type || "")}</dd></div>
      <div class="row"><dt>Fresh</dt><dd>${entry?.fresh ? `yes. Checked at sequence ${entry.checked_seq}` : "no. Stale, re-check to refresh"}</dd></div>
      ${entry?.cached ? `<div class="row"><dt>Cached</dt><dd>yes. Fresh stored entry returned, no new consensus round</dd></div>` : ""}
      <div class="row"><dt>Disputes</dt><dd>${esc(entry?.disputes ?? 0)}</dd></div>
      <div class="row"><dt>Source</dt><dd class="plain">${esc(source)}</dd></div>
      ${tx ? `<div class="row"><dt>Transaction</dt><dd><a href="${esc(txUrl(tx))}" target="_blank" rel="noopener">${esc(tx)}</a><button class="copy-btn" type="button" data-copy="${esc(tx)}">Copy</button></dd></div>` : ""}
      ${consensus ? `<div class="row"><dt>Consensus</dt><dd>${esc(consensus)}${agree !== null ? `. ${agree} of ${total} validators agreed` : ""}</dd></div>` : ""}
      ${note ? `<div class="row"><dt>Note</dt><dd class="plain">${esc(note)}</dd></div>` : ""}
    </dl>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderUnchecked({ projectId, walletAddr, tx, consensus, note }) {
  const box = $("result");
  box.hidden = false;
  $("resultEmpty").hidden = true;
  box.className = "receipt verdict-unchecked";
  box.innerHTML = `
    <div class="receipt-head"><h3>Unchecked</h3>${badge("unchecked")}</div>
    <dl>
      <div class="row"><dt>Project</dt><dd>${esc(projectId)}</dd></div>
      <div class="row"><dt>Wallet</dt><dd>${esc(walletAddr)}</dd></div>
      <div class="row"><dt>Verdict</dt><dd>unchecked. No verdict was written.</dd></div>
      ${tx ? `<div class="row"><dt>Transaction</dt><dd><a href="${esc(txUrl(tx))}" target="_blank" rel="noopener">${esc(tx)}</a><button class="copy-btn" type="button" data-copy="${esc(tx)}">Copy</button></dd></div>` : ""}
      ${consensus ? `<div class="row"><dt>Consensus</dt><dd>${esc(consensus)}</dd></div>` : ""}
      <div class="row"><dt>Note</dt><dd class="plain">${esc(
        note ||
          "Validators could not agree, or the source could not be fetched with a usable HTTP 200 response, so by design nothing was written. This is not an error in the oracle. Try Look up later, or run a check again.",
      )}</dd></div>
    </dl>`;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function setTxStatus(html) {
  const el = $("txStatus");
  if (!html) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML = html;
}

function setBusy(busy) {
  $("checkBtn").disabled = busy;
  $("lookupBtn").disabled = busy;
  $("connectBtn").disabled = busy;
}

// ------------------------------------------------------------------ actions

function validWallet(raw) {
  const w = String(raw || "").trim().toLowerCase();
  if (!/^0x[0-9a-f]{40}$/.test(w)) return null;
  return w;
}

async function doLookup(projectId, walletAddr) {
  setBusy(true);
  setTxStatus("");
  $("result").hidden = true;
  $("resultEmpty").hidden = false;
  try {
    const entry = await api.eligibility(rc, CONTRACT_ADDRESS, projectId, walletAddr);
    if (entry.verdict === "unchecked") {
      renderUnchecked({ projectId, walletAddr, note: "No stored verdict for this wallet yet. Run a check on-chain to ask the validators." });
    } else {
      renderReceipt({
        entry,
        source: "Read-only lookup (get_eligibility). No transaction.",
      });
    }
  } catch (e) {
    renderUnchecked({ projectId, walletAddr, note: `Lookup failed: ${e.message || e}` });
  } finally {
    setBusy(false);
  }
}

async function doCheck(projectId, walletAddr) {
  if (!wallet) {
    setTxStatus(`<span class="stage">Wallet needed.</span> Connect a wallet on Studionet first - the check is an on-chain write.`);
    return;
  }
  setBusy(true);
  $("txStatus").classList.add("loading");
  setTxStatus(`<span class="stage">Preparing check…</span><div class="progress"><span></span></div>`);
  $("result").hidden = true;
  $("resultEmpty").hidden = false;
  try {
    const summary = await api.checkEligibility(wallet.client, CONTRACT_ADDRESS, projectId, walletAddr, (stage, info) => {
      if (stage === "sent") {
        startElapsed();
        setTxStatus(
          `<span class="stage">Submitted. Waiting for consensus…</span> <span class="elapsed" id="elapsedTime">Elapsed 0:00</span><br/>` +
            `<span class="mono">tx <a href="${esc(txUrl(info.hash))}" target="_blank" rel="noopener">${esc(info.hash)}</a></span><br/>` +
            `<span class="fineprint">Validators are fetching the source now. This usually takes about a minute.</span>` +
            `<div class="stepper"><div class="step done"><span class="step-dot">✓</span>Submitted</div><div class="step active"><span class="step-dot"></span>Validators fetching</div><div class="step"><span class="step-dot">3</span>Finalized</div></div>` +
            `<div class="progress"><span></span></div>`,
        );
      }
    });
    if (summary.undetermined) {
      setTxStatus(
        `<span class="stage">Finalized. Undetermined.</span><br/>` +
          `<span class="mono">tx <a href="${esc(txUrl(summary.hash))}" target="_blank" rel="noopener">${esc(summary.hash)}</a></span>`,
      );
      renderUnchecked({ projectId, walletAddr, tx: summary.hash, consensus: summary.consensus });
    } else if (summary.ok) {
      const entry = summary.returned && typeof summary.returned === "object"
        ? summary.returned
        : await api.entry(rc, CONTRACT_ADDRESS, projectId, walletAddr);
      setTxStatus(
        `<span class="stage">Finalized. ${esc(summary.consensus || "accepted")}.</span><br/>` +
          `<span class="mono">tx <a href="${esc(txUrl(summary.hash))}" target="_blank" rel="noopener">${esc(summary.hash)}</a></span>`,
      );
      renderReceipt({
        entry,
        source: `On-chain check (check_eligibility)${entry.cached ? ". Fresh stored entry returned, no new consensus round" : ". New consensus round"}.`,
        tx: summary.hash,
        consensus: summary.consensus,
        votes: summary.votes,
      });
    } else {
      setTxStatus(`<span class="stage">Finalized with an error.</span>`);
      renderUnchecked({ projectId, walletAddr, tx: summary.hash, consensus: summary.consensus, note: `Execution failed: ${summary.error || "unknown error"}` });
    }
  } catch (e) {
    setTxStatus(`<span class="stage">Check failed.</span> ${esc(e.message || e)}`);
  } finally {
    stopElapsed();
    $("txStatus").classList.remove("loading");
    setBusy(false);
    await refreshAll();
  }
}

// ------------------------------------------------------------------ wallet

async function connectWallet() {
  if (!window.ethereum) {
    setTxStatus(`<span class="stage">No wallet found.</span> Install MetaMask or Rabby, then reload this page. Nothing here will ever ask for a seed phrase.`);
    return;
  }
  setBusy(true);
  try {
    wallet = await walletClient(window.ethereum);
    const bal = await balanceOf(rc, wallet.address).catch(() => null);
    $("connectBtn").textContent = `Connected · ${shortAddr(wallet.address)}`;
    $("walletStatus").innerHTML =
      `Connected as <span class="mono">${esc(wallet.address)}</span> · Studionet 61999` +
      (bal !== null ? ` · balance ${esc((Number(bal) / 1e18).toFixed(4))} GEN (test)` : "") +
      ` · <a href="${esc(addressUrl(wallet.address))}" target="_blank" rel="noopener">explorer</a>`;
    setTxStatus("");
  } catch (e) {
    setTxStatus(`<span class="stage">Could not connect.</span> ${esc(e.message || e)}`);
  } finally {
    setBusy(false);
  }
}

// ------------------------------------------------------------------ wiring

async function refreshAll() {
  await Promise.allSettled([loadStats(), loadEntries()]);
}

function guardDeployed() {
  if (DEPLOYED) return true;
  setTxStatus(`<span class="stage">Contract not deployed yet.</span> Fill in the Studionet address in src/config.js first, then redeploy.`);
  return false;
}

$("checkForm").addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (!guardDeployed()) return;
  const walletAddr = validWallet($("walletInput").value);
  if (!walletAddr) {
    setTxStatus(`<span class="stage">Invalid wallet.</span> Enter a full 0x address, 40 hex chars, e.g. ${TAC_ELIGIBLE}`);
    return;
  }
  doCheck($("projectSelect").value, walletAddr);
});

$("lookupBtn").addEventListener("click", () => {
  if (!guardDeployed()) return;
  const walletAddr = validWallet($("walletInput").value);
  if (!walletAddr) {
    setTxStatus(`<span class="stage">Invalid wallet.</span> Enter a full 0x address, 40 hex chars, e.g. ${TAC_ELIGIBLE}`);
    return;
  }
  doLookup($("projectSelect").value, walletAddr);
});

$("demoEligibleBtn").addEventListener("click", () => {
  $("projectSelect").value = "tac";
  $("walletInput").value = TAC_ELIGIBLE;
  if (!guardDeployed()) return;
  doLookup("tac", TAC_ELIGIBLE);
});

$("demoAbsentBtn").addEventListener("click", () => {
  $("projectSelect").value = "tac";
  $("walletInput").value = TAC_ABSENT;
  if (!guardDeployed()) return;
  doLookup("tac", TAC_ABSENT);
});

$("refreshBtn").addEventListener("click", refreshAll);
$("connectBtn").addEventListener("click", connectWallet);

document.addEventListener("click", async (ev) => {
  const btn = ev.target.closest("[data-copy]");
  if (!btn || !btn.dataset.copy) return;
  try {
    await navigator.clipboard.writeText(btn.dataset.copy);
    const label = btn.textContent;
    btn.textContent = "Copied";
    setTimeout(() => { btn.textContent = label; }, 1500);
  } catch (e) {
    /* clipboard unavailable; the link next to it still works */
  }
});

if (window.ethereum) {
  window.ethereum.on?.("accountsChanged", () => {
    wallet = null;
    $("connectBtn").textContent = "Connect wallet";
    $("walletStatus").textContent = "Read-only. No wallet connected.";
  });
  window.ethereum.on?.("chainChanged", () => {
    wallet = null;
    $("connectBtn").textContent = "Connect wallet";
    $("walletStatus").textContent = "Read-only. No wallet connected.";
  });
}

// ------------------------------------------------------------------ init

if (!DEPLOYED) {
  $("notDeployed").hidden = false;
  $("contractAddr").textContent = "not deployed yet";
  $("contractLink").textContent = "not deployed yet";
  $("contractLink").removeAttribute("href");
  $("statsNote").textContent = "Stats will load after the contract is deployed and its address is set in src/config.js.";
  $("entriesNote").textContent = "Entries will load after the contract is deployed.";
  $("checkBtn").disabled = true;
  $("lookupBtn").disabled = true;
  $("demoEligibleBtn").disabled = true;
  $("demoAbsentBtn").disabled = true;
} else {
  $("contractAddr").textContent = CONTRACT_ADDRESS;
  $("contractLink").href = `${EXPLORER}/address/${CONTRACT_ADDRESS}`;
  const copyBtn = $("copyContractBtn");
  if (copyBtn) copyBtn.dataset.copy = CONTRACT_ADDRESS;
  refreshAll();
}
loadProjects();
if (REPO_URL) {
  for (const el of document.querySelectorAll("[data-repo-link]")) {
    el.href = REPO_URL;
    el.hidden = false;
  }
}
