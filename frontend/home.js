const homeForm = document.querySelector("#homeForm");
const homeInput = document.querySelector("#homeInput");
const homeBudget = document.querySelector("#homeBudget");
const homeQuantity = document.querySelector("#homeQuantity");
const homeSubmit = document.querySelector("#homeSubmit");
const homeResult = document.querySelector("#homeResult");
const homeDrop = document.querySelector("#homeDrop");
const homeImageInput = document.querySelector("#homeImageInput");
const homeAttachment = document.querySelector("#homeAttachment");
const homePreview = document.querySelector("#homePreview");
const homeFileName = document.querySelector("#homeFileName");
const homeRemove = document.querySelector("#homeRemove");
let selectedImage = null;
let latestIntent = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function rupees(value) {
  if (value === null || value === undefined) return "Not set";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
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
    showError("Choose a PNG, JPEG, or WebP image.");
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showError("That image is larger than 5 MB. Choose a smaller screenshot.");
    return;
  }
  selectedImage = file;
  homePreview.src = URL.createObjectURL(file);
  homeFileName.textContent = `${file.name} · optional visual context`;
  homeAttachment.hidden = false;
}

function clearImage() {
  selectedImage = null;
  homeImageInput.value = "";
  homeAttachment.hidden = true;
  homePreview.removeAttribute("src");
}

function showError(message) {
  homeResult.setAttribute("aria-busy", "false");
  homeResult.innerHTML = `<div class="home-error">${escapeHtml(message)}</div>`;
}

function renderSuggestions(payload) {
  latestIntent = payload.intent;
  const isReady = payload.suggestions?.length > 0;
  const tag = isReady ? "OPTIONS FOUND" : "NEEDS INPUT";
  const tagClass = isReady ? "" : " reask";
  const candidate = payload.visual_candidate;
  const candidateNote = candidate
    ? `<p class="candidate-note">Image candidate: <strong>${escapeHtml(candidate.product_name)}</strong> · ${Math.round(candidate.confidence * 100)}% confidence · ${escapeHtml(candidate.extraction_method.replaceAll("_", " "))}</p>`
    : "";

  homeResult.setAttribute("aria-busy", "false");
  homeResult.innerHTML = `<div class="result-card"><div class="result-header"><div><h2>${escapeHtml(payload.reply)}</h2>${candidateNote}</div><span class="result-tag${tagClass}">${tag}</span></div><div class="result-grid">${(payload.suggestions || []).map((suggestion) => {
    const product = suggestion.product;
    const fit = suggestion.within_budget === null ? "Budget needed" : suggestion.within_budget ? "Within budget" : "Above budget";
    return `<article class="home-product"><h3>${escapeHtml(product.name)}</h3><p class="merchant">${escapeHtml(suggestion.merchant_name)} · ${escapeHtml(product.product_id)}</p><div class="home-price"><strong>${rupees(suggestion.total_amount)}</strong><span>${escapeHtml(fit)}</span></div><div class="home-reasons">${suggestion.reasons.slice(0, 3).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div><button type="button" class="select-product">Review this option →</button></article>`;
  }).join("")}</div></div>`;

  homeResult.querySelectorAll(".select-product").forEach((button, index) => {
    button.addEventListener("click", () => renderReview(payload.suggestions[index]));
  });
  homeResult.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderReview(suggestion) {
  const product = suggestion.product;
  const defaultBudget = latestIntent?.max_budget || suggestion.total_amount;
  homeResult.innerHTML = `<div class="result-card"><div class="result-header"><div><p class="home-eyebrow">Exact selection review</p><h2>${escapeHtml(product.name)}</h2><p>${escapeHtml(suggestion.merchant_name)} · Current catalog price ${rupees(product.price)}</p></div><span class="result-tag">CONFIRMATION</span></div><div class="review-panel"><h3>Set the boundary before continuing</h3><p>Image and chat are discovery evidence. This explicit review is the only step that can create a purchase intent.</p><div class="review-fields"><label>Maximum total <input id="reviewBudget" type="number" min="1" value="${escapeHtml(defaultBudget)}"></label><label>Quantity <input id="reviewQuantity" type="number" min="1" max="100" value="${escapeHtml(latestIntent?.quantity || 1)}"></label></div><label class="review-check"><input id="reviewCheck" type="checkbox"><span>I confirm this exact product, quantity, and maximum total.</span></label><button class="confirm-action" id="confirmAction" type="button" disabled>Confirm bounded intent</button></div></div>`;
  const check = document.querySelector("#reviewCheck");
  const confirmButton = document.querySelector("#confirmAction");
  check.addEventListener("change", () => { confirmButton.disabled = !check.checked; });
  confirmButton.addEventListener("click", async () => {
    confirmButton.disabled = true;
    confirmButton.textContent = "Running safety gates…";
    try {
      const response = await fetch("/visual-intents/confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ merchant_id: suggestion.merchant_id, product_id: product.product_id, max_budget: Number(document.querySelector("#reviewBudget").value), quantity: Number(document.querySelector("#reviewQuantity").value), confirmed: true }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail?.message || "The intent could not be confirmed.");
      renderConfirmation(payload);
    } catch (error) {
      showError(error.message);
    }
  });
}

function renderConfirmation(payload) {
  const decision = payload.evaluation?.final_decision;
  homeResult.innerHTML = `<div class="result-card"><div class="result-header"><div><p class="home-eyebrow">Authorization result</p><h2>${escapeHtml(payload.product.name)}</h2><p>Intent ${escapeHtml(payload.intent_id)} · selection persisted</p></div><span class="result-tag">${escapeHtml(decision?.decision || "REVIEW")}</span></div><div class="decision-grid"><div class="decision-box"><strong>Buyer Agent</strong><small>${escapeHtml(payload.evaluation?.buyer_agent?.decision || "Evaluated")}</small></div><div class="decision-box"><strong>Trust Gate</strong><small>${escapeHtml(decision?.reason_code || "Evaluated")}</small></div></div><p class="candidate-note">Payment is not executed from this screen. Razorpay Test Mode remains a separate provider boundary.</p></div>`;
}

homeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = homeInput.value.trim();
  if (!message && !selectedImage) {
    showError("Describe what you want to buy. Adding an image is optional.");
    return;
  }
  homeSubmit.disabled = true;
  homeSubmit.textContent = "Finding…";
  homeResult.setAttribute("aria-busy", "true");
  homeResult.innerHTML = '<div class="home-loading">Reading your brief and checking approved catalogs…</div>';
  try {
    const body = { messages: [{ role: "user", content: message || "Identify this product and suggest approved options." }], quantity: Number(homeQuantity.value) || 1 };
    if (homeBudget.value) body.max_budget = Number(homeBudget.value);
    if (selectedImage) { body.image_base64 = await fileToBase64(selectedImage); body.media_type = selectedImage.type; }
    const response = await fetch("/assistant/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail?.message || "The assistant could not complete that request.");
    renderSuggestions(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    homeSubmit.disabled = false;
    homeSubmit.innerHTML = 'Find options <span>↗</span>';
  }
});

homeImageInput.addEventListener("change", () => chooseImage(homeImageInput.files[0]));
homeDrop.addEventListener("click", () => homeImageInput.click());
homeDrop.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") homeImageInput.click(); });
["dragenter", "dragover"].forEach((name) => homeDrop.addEventListener(name, (event) => { event.preventDefault(); homeDrop.classList.add("dragging"); }));
["dragleave", "drop"].forEach((name) => homeDrop.addEventListener(name, (event) => { event.preventDefault(); homeDrop.classList.remove("dragging"); }));
homeDrop.addEventListener("drop", (event) => chooseImage(event.dataTransfer.files[0]));
homeRemove.addEventListener("click", clearImage);
document.querySelectorAll("[data-home-prompt]").forEach((button) => button.addEventListener("click", () => { homeInput.value = button.dataset.homePrompt; homeInput.focus(); }));

const queryParams = new URLSearchParams(window.location.search);
if (queryParams.has("hint")) homeInput.value = queryParams.get("hint");
if (queryParams.has("budget")) homeBudget.value = queryParams.get("budget");
