// --- Session handling: always get a backend-issued session_id ---
let sessionId = null;

async function initSession() {
  try {
    const res = await fetch("/session/new");
    const data = await res.json();
    sessionId = data.session_id;
  } catch (err) {
    console.error("Failed to get session id:", err);
  }
}
initSession();

const chatWindow = document.getElementById("chatWindow");
const userInput = document.getElementById("userInput");
const sendBtn = document.getElementById("sendBtn");

const BOT_AVATAR_SVG = `
  <svg viewBox="0 0 40 40" width="30" height="30">
    <circle cx="20" cy="20" r="20" fill="#6d28d9"/>
    <circle cx="18" cy="20" r="9" fill="#ffffff"/>
    <circle cx="22" cy="16.5" r="7.3" fill="#6d28d9"/>
    <circle cx="14.5" cy="17.5" r="1" fill="#6d28d9"/>
    <circle cx="18.5" cy="18" r="1" fill="#6d28d9"/>
    <path d="M14.2 21.3c1.2 1 3.2 1 4.4 0" stroke="#6d28d9" stroke-width="1" stroke-linecap="round" fill="none"/>
  </svg>`;

userInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendMessage(userInput.value);
  }
});

sendBtn.addEventListener("click", () => sendMessage(userInput.value));

function formatTime() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function appendMessage(role, htmlContent, withReceipt = false) {
  const wrapper = document.createElement("div");
  wrapper.className = `message ${role === "user" ? "user-message" : "bot-message"}`;

  const avatarHtml = role === "bot" ? `<div class="avatar bot-avatar">${BOT_AVATAR_SVG}</div>` : "";

  const receipt = withReceipt
    ? `<svg viewBox="0 0 16 12" width="14" height="11"><path d="M1 6l3 3L10 2M5 8l3 3L15 2" stroke="#6d28d9" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>`
    : "";

  wrapper.innerHTML = `
    ${avatarHtml}
    <div class="bubble-col">
      <div class="bubble">${htmlContent}</div>
      <div class="msg-meta">${formatTime()}${receipt}</div>
    </div>
  `;

  chatWindow.appendChild(wrapper);
  scrollToBottom();
}

function appendTypingIndicator() {
  const wrapper = document.createElement("div");
  wrapper.className = "message bot-message";
  wrapper.id = "typingIndicator";
  wrapper.innerHTML = `
    <div class="avatar bot-avatar">${BOT_AVATAR_SVG}</div>
    <div class="bubble-col">
      <div class="bubble"><div class="typing-dots"><span></span><span></span><span></span></div></div>
    </div>`;
  chatWindow.appendChild(wrapper);
  scrollToBottom();
}

function removeTypingIndicator() {
  const el = document.getElementById("typingIndicator");
  if (el) el.remove();
}

function scrollToBottom() {
  const body = document.querySelector(".widget-body");
  body.scrollTop = body.scrollHeight;
}

async function sendMessage(text) {
  text = (text || "").trim();
  if (!text) return;

  if (!sessionId) {
    await initSession();
    if (!sessionId) {
      appendMessage("bot", "Couldn't start a session. Please refresh and try again.");
      return;
    }
  }

  appendMessage("user", escapeHtml(text), true);
  userInput.value = "";
  sendBtn.disabled = true;

  appendTypingIndicator();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
    });

    const data = await res.json();
    removeTypingIndicator();

    const rendered = window.marked ? marked.parse(data.response || "") : (data.response || "");
    appendMessage("bot", rendered);
  } catch (err) {
    removeTypingIndicator();
    appendMessage("bot", "Sorry, I couldn't reach the server. Please try again.");
    console.error(err);
  } finally {
    sendBtn.disabled = false;
    userInput.focus();
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}