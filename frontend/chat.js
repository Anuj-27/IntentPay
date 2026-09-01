const chatForm = document.querySelector("#chatForm");
const chatInput = document.querySelector("#chatInput");
const messagesElement = document.querySelector("#messages");
const quickPrompts = document.querySelector("#quickPrompts");
const dropTarget = document.querySelector("#dropTarget");
const chatImageInput = document.querySelector("#chatImageInput");
const attachmentPreview = document.querySelector("#attachmentPreview");
const attachmentImage = document.querySelector("#attachmentImage");
const attachmentName = document.querySelector("#attachmentName");
const removeAttachment = document.querySelector("#removeAttachment");
const sendButton = document.querySelector("#sendButton");
const briefCategory = document.querySelector("#briefCategory");
const briefBudget = document.querySelector("#briefBudget");
const briefQuantity = document.querySelector("#briefQuantity");
const briefPreferences = document.querySelector("#briefPreferences");
const briefStatus = document.querySelector("#briefStatus");

const messages = [
  {
    role: "assistant",
    content: "Hi — I’m your IntentPay product assistant. Tell me what you need, your preferences, and (when ready) a maximum budget. You can also drop a product image for visual search.",
  },
];
let selectedImage = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function rupees(value) {
  if (value === null || value === undefined) return "Budget needed";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function renderMessages() {
  messagesElement.innerHTML = messages.map((message) => `
    <div class="message ${message.role}">
      <span class="message-avatar">${message.role === "assistant" ? "✦" : "You"}</span>
      <div class="message-body">
        <div class="message-bubble">${escapeHtml(message.content)}</div>
        <div class="message-meta">${message.role === "assistant" ? "IntentPay assistant" : "You"}</div>
        ${message.suggestions ? renderSuggestions(message.suggestions) : ""}
        ${message.visual_candidate ? `<div class="visual-note">Image read via ${escapeHtml(message.visual_candidate.extraction_method.replaceAll("_", " "))} · ${Math.round(message.visual_candidate.confidence * 100)}% confidence</div>` : ""}
      </div>
    </div>`).join("");
  messagesElement.scrollTop = messagesElement.scrollHeight;
}

function renderSuggestions(suggestions) {
  if (!suggestions?.length) return "";
  return `<div class="suggestion-grid">${suggestions.map((suggestion) => {
    const product = suggestion.product;
    const hint = `${product.brand} ${product.name}`;
    const budgetLabel = suggestion.within_budget === null
      ? "Budget needed"
      : suggestion.within_budget ? "Within budget" : "Above budget";
    const href = `/?hint=${encodeURIComponent(hint)}&budget=${encodeURIComponent(suggestion.total_amount)}`;
    return `<article class="suggestion-card">
      <h3>${escapeHtml(product.name)}</h3>
      <p>${escapeHtml(suggestion.merchant_name)} · ${escapeHtml(product.product_id)}</p>
      <div class="suggestion-price"><strong>${rupees(suggestion.total_amount)}</strong><span>${escapeHtml(budgetLabel)}</span></div>
      <div class="suggestion-reasons">${suggestion.reasons.slice(0, 3).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div>
      <button class="verify-link" type="button" data-verify-href="${escapeHtml(href)}">Open in Verify</button>
    </article>`;
  }).join("")}</div>`;
}

function addTyping() {
  const typing = document.createElement("div");
  typing.className = "message assistant typing";
  typing.innerHTML = '<span class="message-avatar">✦</span><div class="message-body"><div class="message-bubble"><b></b><b></b><b></b></div></div>';
  messagesElement.appendChild(typing);
  messagesElement.scrollTop = messagesElement.scrollHeight;
}

function removeTyping() {
  messagesElement.querySelector(".typing")?.remove();
}

function updateBrief(intent, nextAction) {
  if (!intent) return;
  briefCategory.textContent = intent.category || "Not set yet";
  briefBudget.textContent = intent.max_budget === null || intent.max_budget === undefined
    ? "Not set yet"
    : rupees(intent.max_budget);
  briefQuantity.textContent = intent.quantity || 1;
  briefPreferences.textContent = intent.preferences?.length
    ? intent.preferences.join(", ")
    : (intent.brand || "Add in chat");
  briefStatus.textContent = nextAction === "CHOOSE_PRODUCT" ? "Ready to choose" : "Updated";
}

async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(file);
  });
}

function chooseImage(file) {
  if (!file) return;
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
    messages.push({ role: "assistant", content: "Please attach a PNG, JPEG, or WebP image." });
    renderMessages();
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    messages.push({ role: "assistant", content: "That image is larger than 5 MB. Choose a smaller screenshot." });
    renderMessages();
    return;
  }
  selectedImage = file;
  attachmentImage.src = URL.createObjectURL(file);
  attachmentName.textContent = file.name;
  attachmentPreview.hidden = false;
}

function clearImage() {
  selectedImage = null;
  chatImageInput.value = "";
  attachmentPreview.hidden = true;
  attachmentImage.removeAttribute("src");
}

async function sendMessage(event) {
  event.preventDefault();
  const content = chatInput.value.trim() || (selectedImage ? "Identify this product and suggest approved options." : "");
  if (!content) return;

  messages.push({ role: "user", content });
  chatInput.value = "";
  sendButton.disabled = true;
  addTyping();

  try {
    const body = { messages: messages.slice(-20).map(({ role, content: text }) => ({ role, content: text })) };
    if (selectedImage) {
      body.image_base64 = await fileToBase64(selectedImage);
      body.media_type = selectedImage.type;
    }
    const response = await fetch("/assistant/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail || payload;
      throw new Error(detail.message || `Request failed with ${response.status}`);
    }
    messages.push({
      role: "assistant",
      content: payload.reply,
      suggestions: payload.suggestions,
      visual_candidate: payload.visual_candidate,
    });
    updateBrief(payload.intent, payload.next_action);
    clearImage();
  } catch (error) {
    messages.push({ role: "assistant", content: error.message || "The assistant could not complete that request." });
  } finally {
    removeTyping();
    sendButton.disabled = false;
    renderMessages();
  }
}

chatImageInput.addEventListener("change", () => chooseImage(chatImageInput.files[0]));
dropTarget.addEventListener("click", () => chatImageInput.click());
dropTarget.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") chatImageInput.click();
});
["dragenter", "dragover"].forEach((name) => dropTarget.addEventListener(name, (event) => {
  event.preventDefault();
  dropTarget.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => dropTarget.addEventListener(name, (event) => {
  event.preventDefault();
  dropTarget.classList.remove("dragging");
}));
dropTarget.addEventListener("drop", (event) => chooseImage(event.dataTransfer.files[0]));
removeAttachment.addEventListener("click", clearImage);
chatForm.addEventListener("submit", sendMessage);

quickPrompts.addEventListener("click", (event) => {
  const button = event.target.closest("[data-prompt]");
  if (!button) return;
  chatInput.value = button.dataset.prompt;
  chatInput.focus();
});

document.querySelectorAll(".task-card[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    chatInput.value = button.dataset.prompt;
    chatInput.focus();
  });
});

document.querySelector(".image-task")?.addEventListener("click", () => chatImageInput.click());

messagesElement.addEventListener("click", (event) => {
  const button = event.target.closest("[data-verify-href]");
  if (button) window.location.href = button.dataset.verifyHref;
});

renderMessages();
