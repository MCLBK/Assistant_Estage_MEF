const API_BASE = window.ESTAGE_API_BASE || "https://assistant-estage-mef.onrender.com";

const threadEl = document.getElementById("chat-messages");
const formEl = document.getElementById("chat-form");
const inputEl = document.getElementById("chat-input");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function addAssistantMessage(bodyHtml) {
  const el = document.createElement("div");
  el.className = "msg msg-a";
  el.innerHTML = bodyHtml;
  threadEl.appendChild(el);
  threadEl.scrollTop = threadEl.scrollHeight;
}

function addUserMessage(text) {
  const el = document.createElement("div");
  el.className = "msg msg-u";
  el.innerHTML = `<p>${escapeHtml(text)}</p>`;
  threadEl.appendChild(el);
  threadEl.scrollTop = threadEl.scrollHeight;
}

function renderRecommendations(structures) {
  if (!structures || structures.length === 0) return "";
  const rows = structures.map(s => `
    <div class="reco-row">
      <div class="reco-head">
        <span class="reco-name">${escapeHtml(s.nom_court)} — ${escapeHtml(s.nom)}</span>
        <span class="reco-score">${s.score}%</span>
      </div>
      ${s.services_cibles && s.services_cibles.length ? `<div class="reco-detail">Service à viser : ${escapeHtml(s.services_cibles.join(", "))}</div>` : ""}
      ${s.raisons && s.raisons.length ? `<div class="reco-detail">Correspondance : ${escapeHtml(s.raisons.join(", "))}</div>` : ""}
      ${s.demo_data ? `<span class="reco-flag">Donnée de démonstration</span>` : ""}
    </div>
  `).join("");
  return `<div class="reco">${rows}</div>`;
}

async function sendMessage(text) {
  addUserMessage(text);

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const data = await res.json();

    const paragraphs = escapeHtml(data.reponse)
      .split("\n")
      .filter(l => l.trim().length > 0)
      .map(l => `<p>${l}</p>`)
      .join("");

    addAssistantMessage(paragraphs + renderRecommendations(data.structures_citees));
  } catch (err) {
    addAssistantMessage(
      `<p>Le backend ne répond pas. Vérifiez qu'il est bien lancé (voir README) sur ${escapeHtml(API_BASE)}.</p>`
    );
  }
}

formEl.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = "";
  sendMessage(text);
});

document.querySelectorAll(".toc-item").forEach(btn => {
  btn.addEventListener("click", () => sendMessage(btn.dataset.prompt));
});

document.getElementById("btn-new-chat").addEventListener("click", () => {
  threadEl.innerHTML = "";
  addAssistantMessage("<p>Nouvelle conversation. Comment puis-je vous accompagner dans votre recherche de stage au MEF ?</p>");
});
