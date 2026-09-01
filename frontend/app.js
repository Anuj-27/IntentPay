const form = document.querySelector("#analysisForm");
const imageInput = document.querySelector("#imageInput");
const dropZone = document.querySelector("#dropZone");
const imagePreview = document.querySelector("#imagePreview");
const fileName = document.querySelector("#fileName");
const productHint = document.querySelector("#productHint");
const maxBudget = document.querySelector("#maxBudget");
const quantity = document.querySelector("#quantity");
const analyzeButton = document.querySelector("#analyzeButton");
const resultPanel = document.querySelector(".result-panel");
const resultContent = document.querySelector("#resultContent");
const resultStatus = document.querySelector("#resultStatus");
const privacyStatus = document.querySelector("#privacyStatus");
const modeBadge = document.querySelector("#modeBadge");
const categoryCount = document.querySelector("#categoryCount");

let selectedFile = null;
let currentAnalysis = null;
let razorpayConfigured = false;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatRupees(value) {
  if (value === null || value === undefined) return "Not detected";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload;
    const error = new Error(detail.message || `Request failed with ${response.status}`);
    error.reasonCode = detail.reason_code || "REQUEST_FAILED";
    throw error;
  }
  return payload;
}

function setStep(name) {
  const order = ["analyze", "verify", "authorize"];
  const activeIndex = order.indexOf(name);
  document.querySelectorAll(".flow-step").forEach((step) => {
    const stepIndex = order.indexOf(step.dataset.step);
    step.classList.toggle("active", stepIndex === activeIndex);
    step.classList.toggle("complete", stepIndex < activeIndex);
  });
}

function setResultStatus(label, type = "neutral") {
  resultStatus.textContent = label;
  resultStatus.className = `result-status ${type}`;
}

function setLoading(message) {
  resultPanel.setAttribute("aria-busy", "true");
  resultContent.className = "loading-state";
  resultContent.innerHTML = `<div><span></span>${escapeHtml(message)}</div>`;
}

function setError(error) {
  resultPanel.setAttribute("aria-busy", "false");
  setResultStatus("Error", "block");
  resultContent.className = "";
  resultContent.innerHTML = `
    <div class="error-card">
      <h3>${escapeHtml(error.reasonCode || "REQUEST_FAILED")}</h3>
      <p>${escapeHtml(error.message)}</p>
    </div>`;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(new Error("The screenshot could not be read."));
    reader.readAsDataURL(file);
  });
}

function chooseFile(file) {
  if (!file) return;
  const allowedTypes = ["image/png", "image/jpeg", "image/webp"];
  if (!allowedTypes.includes(file.type)) {
    setError(new Error("Choose a PNG, JPEG, or WebP screenshot."));
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    setError(new Error("The screenshot must be 5 MB or smaller."));
    return;
  }

  selectedFile = file;
  imagePreview.src = URL.createObjectURL(file);
  dropZone.classList.add("has-image");
  fileName.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
}

imageInput.addEventListener("change", () => chooseFile(imageInput.files[0]));

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  chooseFile(event.dataTransfer.files[0]);
});

function renderAnalysis(analysis) {
  currentAnalysis = analysis;
  resultPanel.setAttribute("aria-busy", "false");
  const isReady = analysis.status === "READY_FOR_CONFIRMATION";
  setResultStatus(isReady ? "Verified" : "Needs input", isReady ? "allow" : "reask");
  setStep(isReady ? "verify" : "analyze");

  const candidate = analysis.candidate;
  const match = analysis.selected_match;
  const evidence = match?.evidence || [];
  const matchMarkup = match ? `
    <div class="product-card">
      <div class="product-topline">
        <div>
          <h3>${escapeHtml(match.product.name)}</h3>
          <p>${escapeHtml(match.merchant_name)} · ${escapeHtml(match.product.product_id)}</p>
        </div>
        <span class="price">${formatRupees(match.product.price)}</span>
      </div>
      <div class="evidence-grid">
        <div><span>Model</span><strong>${escapeHtml(match.product.model || "—")}</strong></div>
        <div><span>Variant</span><strong>${escapeHtml(match.product.variant || "—")}</strong></div>
        <div><span>Match</span><strong>${escapeHtml(match.match_score)}%</strong></div>
      </div>
      <ul class="match-evidence">
        ${evidence.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ul>
    </div>` : "";

  const confirmMarkup = isReady && match ? `
    <div class="confirm-box">
      <label class="confirmation-check">
        <input type="checkbox" id="confirmationCheck">
        <span>I confirm this exact product, quantity ${escapeHtml(analysis.quantity)}, and a maximum total of ${formatRupees(analysis.max_budget)}.</span>
      </label>
      <button class="secondary-button" id="confirmButton" type="button" disabled>Confirm bounded intent</button>
    </div>` : "";

  resultContent.className = "";
  resultContent.innerHTML = `
    <div class="reason-card">
      <strong>${escapeHtml(analysis.reason_code)}</strong>
      <p>${escapeHtml(analysis.message)}</p>
    </div>
    <div class="evidence-grid" style="margin-bottom: 14px">
      <div><span>Candidate</span><strong>${escapeHtml(candidate.product_name)}</strong></div>
      <div><span>Confidence</span><strong>${Math.round(candidate.confidence * 100)}%</strong></div>
      <div><span>Method</span><strong>${escapeHtml(candidate.extraction_method.replaceAll("_", " "))}</strong></div>
    </div>
    ${matchMarkup}
    ${confirmMarkup}`;

  if (isReady && match) {
    const checkbox = document.querySelector("#confirmationCheck");
    const button = document.querySelector("#confirmButton");
    checkbox.addEventListener("change", () => {
      button.disabled = !checkbox.checked;
    });
    button.addEventListener("click", confirmIntent);
  }
}

async function confirmIntent() {
  const match = currentAnalysis.selected_match;
  setLoading("Persisting confirmation and running deterministic gates…");
  try {
    const confirmation = await api("/visual-intents/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant_id: match.merchant_id,
        product_id: match.product.product_id,
        max_budget: currentAnalysis.max_budget,
        quantity: currentAnalysis.quantity,
        confirmed: true,
      }),
    });
    renderConfirmation(confirmation);
  } catch (error) {
    setError(error);
  }
}

function renderConfirmation(confirmation) {
  resultPanel.setAttribute("aria-busy", "false");
  setStep("authorize");
  const finalDecision = confirmation.evaluation.final_decision;
  const purchase = confirmation.razorpay_test_request?.purchase;
  const allowed = finalDecision.decision === "ALLOW";
  setResultStatus(finalDecision.decision, allowed ? "allow" : "block");

  resultContent.className = "";
  resultContent.innerHTML = `
    <div class="reason-card">
      <strong>${escapeHtml(confirmation.reason_code)}</strong>
      <p>The exact selection is persisted. Recommendation is still separate from payment execution.</p>
    </div>
    <div class="product-card">
      <div class="product-topline">
        <div>
          <h3>${escapeHtml(confirmation.product.name)}</h3>
          <p>${escapeHtml(confirmation.product.product_id)}</p>
        </div>
        <span class="price">${formatRupees(purchase?.total_amount)}</span>
      </div>
      <div class="meta-row"><span>Intent ID</span><strong>${escapeHtml(confirmation.intent_id)}</strong></div>
      <div class="meta-row"><span>Selection confirmed</span><strong>Yes</strong></div>
      <div class="meta-row"><span>Payment executed</span><strong>No</strong></div>
    </div>
    <div class="gate-grid">
      <div class="gate-card passed">
        <h3>Buyer Agent</h3>
        <span class="decision-pill">${escapeHtml(confirmation.evaluation.buyer_agent.decision)}</span>
        <p>${escapeHtml(confirmation.evaluation.buyer_agent.reason_code)}</p>
      </div>
      <div class="gate-card passed">
        <h3>Trust Gate</h3>
        <span class="decision-pill">${escapeHtml(finalDecision.decision)}</span>
        <p>${escapeHtml(finalDecision.reason_code)}</p>
      </div>
    </div>
    <div class="razorpay-box">
      <h3>Razorpay Test boundary</h3>
      <p>${razorpayConfigured
        ? "Test Mode is configured. Create the provider order only when you are ready to open Checkout."
        : "The verified request is ready, but Test Mode credentials are not configured. No provider call will be made."}</p>
      <button id="razorpayButton" type="button" ${razorpayConfigured && confirmation.razorpay_test_request ? "" : "disabled"}>
        ${razorpayConfigured ? "Create Razorpay test order" : "Test credentials required"}
      </button>
    </div>`;

  const razorpayButton = document.querySelector("#razorpayButton");
  if (razorpayConfigured && confirmation.razorpay_test_request) {
    razorpayButton.addEventListener("click", async () => {
      razorpayButton.disabled = true;
      razorpayButton.textContent = "Creating test order…";
      try {
        const order = await api("/payments/razorpay-test/orders", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(confirmation.razorpay_test_request),
        });
        razorpayButton.textContent = order.payment_created
          ? `Test order ${order.provider_order.id} created`
          : order.reason_code;
      } catch (error) {
        razorpayButton.textContent = error.reasonCode || "Order failed";
      }
    });
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedFile) {
    setError(new Error("Choose a product screenshot first."));
    return;
  }

  analyzeButton.disabled = true;
  setLoading("Reading visible text and checking approved catalogs…");
  try {
    const imageBase64 = await fileToBase64(selectedFile);
    const request = {
      image_base64: imageBase64,
      media_type: selectedFile.type,
      user_message: productHint.value.trim() || "I want to buy this product",
      quantity: Number(quantity.value),
    };
    if (maxBudget.value) request.max_budget = Number(maxBudget.value);

    const analysis = await api("/visual-intents/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    renderAnalysis(analysis);
  } catch (error) {
    setError(error);
  } finally {
    analyzeButton.disabled = false;
  }
});

async function initialize() {
  try {
    const [configuration, categories, razorpay] = await Promise.all([
      api("/visual-intents/configuration"),
      api("/categories"),
      api("/payments/razorpay-test/configuration"),
    ]);
    modeBadge.textContent = configuration.mode.replaceAll("_", " ");
    privacyStatus.classList.toggle("ready", configuration.local_ocr_available);
    privacyStatus.lastChild.textContent = configuration.sends_images_to_external_provider
      ? " External visual provider"
      : " Private local analysis";
    categoryCount.textContent = categories.count;
    razorpayConfigured = razorpay.configured;
  } catch (error) {
    privacyStatus.lastChild.textContent = " API unavailable";
  }
}

initialize();
