const form = document.getElementById("ask-form");
const input = document.getElementById("question");
const askBtn = document.getElementById("ask-btn");
const stepsEl = document.getElementById("steps");
const retrievedEl = document.getElementById("retrieved");
const answerEl = document.getElementById("answer");
const citationsEl = document.getElementById("citations");

let source = null;

// Steps that map to a <li> in the pipeline list. "generating" also implies the
// earlier steps are complete.
const STEP_ORDER = ["embedding", "searching", "retrieved", "generating", "done"];

function resetUI() {
  stepsEl.querySelectorAll("li").forEach((li) => {
    li.classList.remove("active", "complete");
  });
  retrievedEl.innerHTML = "";
  answerEl.textContent = "";
  citationsEl.innerHTML = "";
}

function markStep(step) {
  const idx = STEP_ORDER.indexOf(step);
  if (idx === -1) return;
  STEP_ORDER.forEach((s, i) => {
    const li = stepsEl.querySelector(`li[data-step="${s}"]`);
    if (!li) return;
    if (i < idx) {
      li.classList.add("complete");
      li.classList.remove("active");
    } else if (i === idx) {
      li.classList.add("active");
      li.classList.remove("complete");
    }
  });
  if (step === "done") {
    stepsEl.querySelectorAll("li").forEach((li) => {
      li.classList.add("complete");
      li.classList.remove("active");
    });
  }
}

function renderRetrieved(docs) {
  retrievedEl.innerHTML = "";
  docs.forEach((d) => {
    const li = document.createElement("li");
    li.className = "card";
    const meta = [d.journal, d.year].filter(Boolean).join(" · ");
    li.innerHTML = `
      <a href="${d.url}" target="_blank" rel="noopener">${escapeHtml(d.title)}</a>
      <div class="card-meta">${escapeHtml(meta)}
        <span class="score">similarity ${d.score}</span></div>`;
    retrievedEl.appendChild(li);
  });
}

const seenCitations = new Set();
function addCitation(c) {
  // Dedupe identical cited spans from the same source.
  const key = `${c.pmid}::${c.cited_text}`;
  if (seenCitations.has(key)) return;
  seenCitations.add(key);
  const li = document.createElement("li");
  li.className = "card";
  li.innerHTML = `
    <a href="${c.url}" target="_blank" rel="noopener">${escapeHtml(c.title)}</a>
    <blockquote>${escapeHtml(c.cited_text)}</blockquote>`;
  citationsEl.appendChild(li);
}

function escapeHtml(s) {
  return (s || "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function setBusy(busy) {
  askBtn.disabled = busy;
  askBtn.textContent = busy ? "Working…" : "Ask";
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (!q) return;

  if (source) source.close();
  resetUI();
  seenCitations.clear();
  setBusy(true);

  source = new EventSource(`/api/query?q=${encodeURIComponent(q)}`);

  source.addEventListener("embedding", () => markStep("embedding"));
  source.addEventListener("searching", () => markStep("searching"));
  source.addEventListener("retrieved", (ev) => {
    markStep("retrieved");
    renderRetrieved(JSON.parse(ev.data).docs);
  });
  source.addEventListener("generating", () => markStep("generating"));
  source.addEventListener("token", (ev) => {
    answerEl.textContent += JSON.parse(ev.data).text;
  });
  source.addEventListener("citation", (ev) => addCitation(JSON.parse(ev.data)));
  source.addEventListener("done", () => {
    markStep("done");
    setBusy(false);
    source.close();
  });
  source.addEventListener("error", (ev) => {
    // Distinguish an app-level error frame (has data) from a transport drop.
    let msg = "Connection error.";
    try { if (ev.data) msg = JSON.parse(ev.data).message; } catch (_) {}
    answerEl.innerHTML += `<div class="err">${escapeHtml(msg)}</div>`;
    setBusy(false);
    if (source) source.close();
  });
});
