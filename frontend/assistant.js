// IntentPay AI Assistant — the conversational interface to the complete
// IntentPay commerce orchestration system.
//
// Presentation only. Every real decision (intent extraction, catalog
// search, Trust Gate, payment) is made by the backend; this module calls
// the same endpoints the previous form-based UI used (`/assistant/chat`,
// `/visual-intents/confirm`, `/intents/{id}/merchant-approval`,
// `/intents/{id}/orchestrate`, the Razorpay Test Mode module, `/audit/{id}`)
// and only adds the conversational choreography around real responses.
//
// Mountable so the exact same engine powers both the full-screen `/chat`
// page and the floating widget on `/` -- one implementation, so the two
// surfaces can never drift on how they interpret a Trust Gate decision.
window.IntentPayAssistant = (function () {
  const THINKING_STAGES = [
    "Understanding your request…",
    "Checking your preferences…",
    "Searching the merchant catalog…",
    "Comparing eligible products…",
  ];

  const CHECK_ROWS = [
    { key: "intent", label: "Intent verified", codes: ["PRODUCT_SELECTION_NOT_CONFIRMED", "PRODUCT_SELECTION_MISMATCH", "QUANTITY_MISMATCH"] },
    { key: "product", label: "Product verified", codes: ["PRODUCT_NOT_FOUND", "CATEGORY_MISMATCH", "BRAND_MISMATCH", "COLOR_MISMATCH"] },
    { key: "price", label: "Price verified", codes: ["UNIT_PRICE_MISMATCH", "TOTAL_AMOUNT_MISMATCH"] },
    { key: "budget", label: "Budget verified", codes: ["BUDGET_EXCEEDED"] },
    { key: "stock", label: "Stock verified", codes: ["OUT_OF_STOCK"] },
    { key: "policy", label: "Merchant policy verified", codes: [] },
  ];

  const DECISION_COPY = {
    ALLOW: { label: "ALLOW", note: "Safe to proceed" },
    REASK: { label: "REASK", note: "Action required" },
    BLOCK: { label: "BLOCK", note: "Blocked" },
    ESCALATE: { label: "ESCALATE", note: "Human approval required" },
  };

  const WORKFLOW_STAGES = [
    { key: "intent", label: "Intent" },
    { key: "search", label: "Search" },
    { key: "verify", label: "Verify" },
    { key: "trust", label: "Trust Gate" },
    { key: "payment", label: "Payment" },
    { key: "audit", label: "Audit" },
  ];

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function rupees(value) {
    if (value === null || value === undefined) return "No limit set";
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
  }

  function titleCase(value) {
    if (!value) return value;
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  async function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error("The image could not be read."));
      reader.readAsDataURL(file);
    });
  }

  function fullscreenTemplate() {
    return `
      <div class="ip-landing" id="ipLanding">
        <div class="ip-intro ip-intro-1">
          <div class="ip-wordmark">INTENTPAY</div>
          <div class="ip-pipeline" aria-hidden="true">
            <span>Understand</span><b>→</b><span>Decide</span><b>→</b><span>Trust</span><b>→</b><span>Act</span><b>→</b><span>Prove</span>
          </div>
        </div>
        <h1 class="ip-hero ip-intro ip-intro-2">What are you looking for?</h1>
        <p class="ip-hero-sub ip-intro ip-intro-3">Tell IntentPay what you need. We&rsquo;ll understand your intent, find the right options, and keep every financial action within your authorization.</p>
      </div>
      <div class="ip-workflow-rail" data-workflow-rail hidden></div>
      <section class="ip-conversation" data-conversation aria-live="polite"></section>
      <div class="ip-composer-wrap ip-intro ip-intro-4" data-composer-wrap>
        ${composerMarkup()}
        <div class="ip-examples" data-examples>
          <button type="button" data-prompt="I need headphones with ANC under ₹5000">ANC headphones under ₹5,000</button>
          <button type="button" data-prompt="Compare laptops under ₹65000 with 16GB RAM">Laptops under ₹65k</button>
          <button type="button" data-prompt="Find a smartwatch with GPS under ₹30000">Smartwatch with GPS</button>
        </div>
      </div>`;
  }

  function widgetTemplate() {
    return `
      <div class="ip-widget-header">
        <span class="ip-avatar-lg">✦</span>
        <div class="ip-widget-heading"><strong>IntentPay</strong><small><i class="ip-online-dot"></i>Online</small></div>
        <button type="button" class="ip-widget-close" data-widget-close aria-label="Close assistant">×</button>
      </div>
      <div class="ip-workflow-rail" data-workflow-rail hidden></div>
      <section class="ip-conversation" data-conversation aria-live="polite"></section>
      <div class="ip-composer-wrap" data-composer-wrap>
        ${composerMarkup()}
      </div>`;
  }

  function composerMarkup() {
    return `
      <form class="ip-composer" data-form aria-label="Ask IntentPay AI">
        <div class="ip-composer-glass" data-composer-glass>
          <div class="attachment-preview" data-attachment-preview hidden>
            <img data-attachment-image alt="Attached product image preview">
            <div><strong data-attachment-name></strong><small>Image attached for visual search</small></div>
            <button type="button" data-remove-attachment aria-label="Remove attached image">×</button>
          </div>
          <div class="ip-composer-row">
            <button type="button" class="ip-attach-btn" data-attach-button aria-label="Attach a product image" title="Attach a product image">
              <span aria-hidden="true">＋</span>
            </button>
            <textarea data-chat-input rows="1" maxlength="2000" placeholder="I want the best Sony headphones under ₹5,000 with ANC." aria-label="Message IntentPay AI"></textarea>
            <input type="file" data-image-input accept="image/png,image/jpeg,image/webp" hidden>
            <button class="ip-send-btn" data-send-button type="submit" aria-label="Send message">
              <span aria-hidden="true">↗</span>
            </button>
          </div>
          <div class="ip-composer-foot">
            <span class="ip-composer-note"><span aria-hidden="true">⌁</span> Nothing is purchased from chat &mdash; every action is checked by the Trust Gate</span>
          </div>
        </div>
      </form>`;
  }

  function mount(rootEl, options = {}) {
    const variant = options.variant === "widget" ? "widget" : "fullscreen";
    rootEl.classList.add("ip-mount", `ip-variant-${variant}`);
    rootEl.innerHTML = variant === "widget" ? widgetTemplate() : fullscreenTemplate();

    const ipLanding = rootEl.querySelector("#ipLanding");
    const ipConversation = rootEl.querySelector("[data-conversation]");
    const workflowRail = rootEl.querySelector("[data-workflow-rail]");
    const chatForm = rootEl.querySelector("[data-form]");
    const chatInput = rootEl.querySelector("[data-chat-input]");
    const sendButton = rootEl.querySelector("[data-send-button]");
    const composerGlass = rootEl.querySelector("[data-composer-glass]");
    const attachButton = rootEl.querySelector("[data-attach-button]");
    const chatImageInput = rootEl.querySelector("[data-image-input]");
    const attachmentPreview = rootEl.querySelector("[data-attachment-preview]");
    const attachmentImage = rootEl.querySelector("[data-attachment-image]");
    const attachmentName = rootEl.querySelector("[data-attachment-name]");
    const removeAttachment = rootEl.querySelector("[data-remove-attachment]");
    const examples = rootEl.querySelector("[data-examples]");
    const closeButton = rootEl.querySelector("[data-widget-close]");

    let messages = [];
    let selectedImage = null;
    let latestIntent = null;
    let stageActivated = variant === "widget"; // the widget has no separate landing state to collapse
    const workflow = { intent: false, search: false, verify: false, trust: false, payment: false, audit: false };

    // ---------------------------------------------------------- utils --

    function scrollConversation() {
      ipConversation.scrollTop = ipConversation.scrollHeight;
    }

    function activateStage() {
      if (stageActivated) return;
      stageActivated = true;
      if (ipLanding) ipLanding.classList.add("is-collapsed");
    }

    function setWorkflowStage(key) {
      if (workflow[key]) return;
      workflow[key] = true;
      renderWorkflowRail();
    }

    function renderWorkflowRail() {
      const anyActive = Object.values(workflow).some(Boolean);
      workflowRail.hidden = !anyActive;
      if (!anyActive) return;
      workflowRail.innerHTML = WORKFLOW_STAGES.map((stage, index) => {
        const done = workflow[stage.key];
        const isLast = index === WORKFLOW_STAGES.length - 1;
        const isCurrent = done && (isLast || !workflow[WORKFLOW_STAGES[index + 1].key]);
        const state = done ? (isCurrent ? "current" : "done") : "pending";
        return `<div class="ip-workflow-step ${state}"><span class="ip-workflow-dot"></span><span class="ip-workflow-label">${escapeHtml(stage.label)}</span></div>`;
      }).join("");
    }

    // -------------------------------------------------------- image upload --

    function chooseImage(file) {
      if (!file) return;
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        appendErrorTurn("Please attach a PNG, JPEG, or WebP image.");
        return;
      }
      if (file.size > 5 * 1024 * 1024) {
        appendErrorTurn("That image is larger than 5 MB. Choose a smaller screenshot.");
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

    attachButton.addEventListener("click", () => chatImageInput.click());
    chatImageInput.addEventListener("change", () => chooseImage(chatImageInput.files[0]));
    removeAttachment.addEventListener("click", clearImage);
    ["dragenter", "dragover"].forEach((name) => composerGlass.addEventListener(name, (event) => {
      event.preventDefault();
      composerGlass.classList.add("is-dragging");
    }));
    ["dragleave", "drop"].forEach((name) => composerGlass.addEventListener(name, (event) => {
      event.preventDefault();
      composerGlass.classList.remove("is-dragging");
    }));
    composerGlass.addEventListener("drop", (event) => chooseImage(event.dataTransfer.files[0]));

    chatInput.addEventListener("input", () => {
      chatInput.style.height = "auto";
      chatInput.style.height = `${Math.min(chatInput.scrollHeight, 140)}px`;
    });

    if (examples) {
      examples.addEventListener("click", (event) => {
        const button = event.target.closest("[data-prompt]");
        if (!button) return;
        chatInput.value = button.dataset.prompt;
        chatInput.focus();
      });
    }

    if (closeButton && typeof options.onClose === "function") {
      closeButton.addEventListener("click", () => options.onClose());
    }

    // -------------------------------------------------------- conversation --

    function appendUserTurn(content) {
      const turn = document.createElement("div");
      turn.className = "ip-turn ip-turn-user";
      turn.innerHTML = `<div class="ip-bubble">${escapeHtml(content)}</div>`;
      ipConversation.appendChild(turn);
      scrollConversation();
    }

    function startThinking(hasImage) {
      const turn = document.createElement("div");
      turn.className = "ip-turn ip-turn-assistant";
      const imageNote = hasImage
        ? '<div class="ip-thinking" style="padding-top:0;font-size:0.68rem;">Reading the image with the local vision model — this can take up to a few minutes on CPU-only hardware.</div>'
        : "";
      turn.innerHTML = `<span class="ip-avatar">✦</span><div class="ip-turn-body"><div class="ip-thinking"><span class="ip-thinking-dot"></span><span class="ip-thinking-text">${THINKING_STAGES[0]}</span></div>${imageNote}</div>`;
      ipConversation.appendChild(turn);
      scrollConversation();

      let index = 0;
      const textEl = turn.querySelector(".ip-thinking-text");
      const interval = window.setInterval(() => {
        index = Math.min(index + 1, THINKING_STAGES.length - 1);
        textEl.textContent = THINKING_STAGES[index];
      }, 420);

      return () => {
        window.clearInterval(interval);
        turn.remove();
      };
    }

    function appendErrorTurn(message) {
      const turn = document.createElement("div");
      turn.className = "ip-turn ip-turn-assistant";
      turn.innerHTML = `<span class="ip-avatar">✦</span><div class="ip-turn-body"><div class="ip-error-text" style="margin-left:0;">Something went wrong while checking your request.<br><small>${escapeHtml(message || "")}</small></div><button type="button" class="ip-retry-btn" style="margin-left:0;">Try again</button></div>`;
      turn.querySelector(".ip-retry-btn").addEventListener("click", () => chatInput.focus());
      ipConversation.appendChild(turn);
      scrollConversation();
    }

    function productCardBody(product) {
      return IntentPayMedia.renderProductCardBody(product, escapeHtml);
    }

    const PRIORITY_LABEL = { CHEAPEST: "Cheapest", BEST_VALUE: "Best value", HIGHEST_RATING: "Highest rated" };

    function intentChips(intent) {
      const chips = [
        { key: "category", label: "Category", value: intent.category ? titleCase(intent.category) : "Not set yet" },
        { key: "budget", label: "Budget", value: rupees(intent.max_budget) },
        { key: "quantity", label: "Quantity", value: String(intent.quantity || 1) },
        { key: "priority", label: "Priority", value: PRIORITY_LABEL[intent.priority] || "Best value" },
      ];
      const prefBits = [intent.brand, intent.color, ...(intent.preferences || [])].filter(Boolean);
      chips.push({ key: "preference", label: "Preference", value: prefBits.length ? prefBits.join(", ") : "Best value" });
      if (intent.brand && intent.brand_preference && intent.brand_preference !== "ANY") {
        chips.push({ key: "brand_preference", label: "Brand preference", value: titleCase(intent.brand_preference.toLowerCase()) });
      }
      if (intent.color && intent.color_preference && intent.color_preference !== "ANY") {
        chips.push({ key: "color_preference", label: "Color preference", value: titleCase(intent.color_preference.toLowerCase()) });
      }
      chips.push({ key: "subscription", label: "Subscription", value: intent.subscription_allowed ? "Allowed" : "Not allowed" });
      chips.push({ key: "autonomous", label: "Autonomous selection", value: intent.autonomous_selection_allowed ? "Allowed" : "Requires my confirmation" });
      return chips;
    }

    function renderIntentRow(intent) {
      const wrap = document.createElement("div");
      wrap.className = "ip-intent";
      const chips = intentChips(intent);
      chips.forEach((chip, index) => {
        const el = document.createElement("div");
        el.className = "ip-chip ip-pop";
        el.style.animationDelay = `${index * 100}ms`;
        el.innerHTML = `<span>${escapeHtml(chip.label)}</span><strong>${escapeHtml(chip.value)}</strong>`;
        wrap.appendChild(el);
      });

      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "ip-chip ip-pop";
      editBtn.style.animationDelay = `${chips.length * 100}ms`;
      editBtn.innerHTML = `<span>&nbsp;</span><strong>Edit intent</strong>`;
      editBtn.addEventListener("click", () => renderEditPanel(intent, wrap));
      wrap.appendChild(editBtn);

      return wrap;
    }

    function renderEditPanel(intent, afterEl) {
      rootEl.querySelector(".ip-edit-panel")?.remove();
      const panel = document.createElement("div");
      panel.className = "ip-panel ip-edit-panel ip-pop";
      panel.innerHTML = `
        <p class="ip-panel-kicker">Edit intent</p>
        <h3>Adjust budget or quantity</h3>
        <p>Category, brand, priority, and permissions are best changed by simply telling IntentPay AI what you want next -- e.g. "cheapest option" or "subscription is okay".</p>
        <div class="ip-review-fields">
          <label>Maximum budget <input type="number" min="1" class="ip-edit-budget" value="${escapeHtml(intent.max_budget ?? "")}"></label>
          <label>Quantity <input type="number" min="1" max="100" class="ip-edit-quantity" value="${escapeHtml(intent.quantity || 1)}"></label>
        </div>
        <button type="button" class="ip-confirm-btn">Apply</button>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();
      panel.querySelector(".ip-confirm-btn").addEventListener("click", () => {
        const budgetValue = Number(panel.querySelector(".ip-edit-budget").value);
        const quantityValue = Number(panel.querySelector(".ip-edit-quantity").value);
        const parts = [];
        if (Number.isFinite(budgetValue) && budgetValue > 0 && budgetValue !== intent.max_budget) {
          parts.push(`under ₹${budgetValue}`);
        }
        if (Number.isFinite(quantityValue) && quantityValue > 0 && quantityValue !== (intent.quantity || 1)) {
          parts.push(`quantity ${quantityValue}`);
        }
        panel.remove();
        if (!parts.length) return;
        sendCorrection(parts.join(", "));
      });
    }

    function renderProductsRow(suggestions, upsellCandidates) {
      const grid = document.createElement("div");
      grid.className = "ip-products";
      let index = 0;

      suggestions.forEach((suggestion) => {
        const product = suggestion.product;
        const fit = suggestion.within_budget === null ? "Budget needed" : suggestion.within_budget ? "Within budget" : "Above budget";
        const card = document.createElement("article");
        card.className = "ip-product ip-pop";
        card.style.animationDelay = `${index * 130}ms`;
        index += 1;
        card.innerHTML = `${productCardBody(product)}<div class="ip-product-price"><strong>${rupees(suggestion.total_amount)}</strong><span>${escapeHtml(fit)}</span></div><div class="ip-product-reasons">${suggestion.reasons.slice(0, 3).map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div><button type="button" class="ip-select-product">Choose this option →</button>`;
        card.querySelector(".ip-select-product").addEventListener("click", () => openReview(suggestion, {}, grid));
        grid.appendChild(card);
      });

      (upsellCandidates || []).forEach((candidate) => {
        const product = candidate.product;
        const card = document.createElement("article");
        card.className = "ip-product ip-pop";
        card.style.animationDelay = `${index * 130}ms`;
        index += 1;
        card.innerHTML = `<span class="upsell-badge">+${rupees(candidate.over_budget_amount)} · ${escapeHtml(candidate.over_budget_percent)}% over</span>${productCardBody(product)}<div class="ip-product-price"><strong>${rupees(candidate.total_amount)}</strong><span>Not budget-eligible</span></div><p class="ip-decision-note" style="margin:0 0 8px;">This is above your maximum -- selecting it will ask you to reauthorize, never purchase automatically.</p><button type="button" class="ip-select-product">Request reauthorization →</button>`;
        card.querySelector(".ip-select-product").addEventListener("click", () => openReview({
          merchant_id: candidate.merchant_id,
          merchant_name: candidate.merchant_name,
          product: candidate.product,
          total_amount: candidate.total_amount,
        }, { requiresReauthorization: true }, grid));
        grid.appendChild(card);
      });

      IntentPayMedia.bindThumbSwaps(grid);
      return grid;
    }

    function renderEmptyActions(intent) {
      const wrap = document.createElement("div");
      wrap.className = "ip-empty-actions ip-pop";
      const suggestedBudget = intent.max_budget ? Math.round((intent.max_budget * 1.4) / 100) * 100 : null;
      if (suggestedBudget) {
        const raise = document.createElement("button");
        raise.type = "button";
        raise.textContent = `Try up to ${rupees(suggestedBudget)}`;
        raise.addEventListener("click", () => {
          chatInput.value = `Increase my budget to ₹${suggestedBudget}`;
          chatInput.focus();
        });
        wrap.appendChild(raise);
      }
      if (intent.category) {
        const broaden = document.createElement("button");
        broaden.type = "button";
        broaden.textContent = "Broaden the request";
        broaden.addEventListener("click", () => {
          chatInput.value = `Show me all ${intent.category} options`;
          chatInput.focus();
        });
        wrap.appendChild(broaden);
      }
      return wrap;
    }

    async function renderAssistantTurn(payload) {
      latestIntent = payload.intent;
      if (payload.intent?.category) setWorkflowStage("intent");

      const turn = document.createElement("div");
      turn.className = "ip-turn ip-turn-assistant";
      const body = document.createElement("div");
      body.className = "ip-turn-body";
      turn.innerHTML = `<span class="ip-avatar">✦</span>`;
      turn.appendChild(body);

      const replyEl = document.createElement("div");
      replyEl.className = "ip-reply-text ip-pop";
      replyEl.textContent = payload.reply;
      body.appendChild(replyEl);

      ipConversation.appendChild(turn);
      scrollConversation();

      if (payload.visual_candidate) {
        const note = document.createElement("p");
        note.className = "ip-decision-note";
        note.style.marginLeft = "36px";
        note.textContent = `Image candidate: ${payload.visual_candidate.product_name} · ${Math.round(payload.visual_candidate.confidence * 100)}% confidence`;
        ipConversation.appendChild(note);
      }

      const approvedSuggestions = (payload.suggestions || []).filter((suggestion) => suggestion.within_budget !== false);
      if (approvedSuggestions.length || payload.upsell_candidates?.length) setWorkflowStage("search");

      if (payload.intent && (payload.intent.category || payload.intent.max_budget != null)) {
        ipConversation.appendChild(renderIntentRow(payload.intent));
      }

      if (approvedSuggestions.length || payload.upsell_candidates?.length) {
        ipConversation.appendChild(renderProductsRow(approvedSuggestions, payload.upsell_candidates));
      } else if (payload.next_action === "CHOOSE_PRODUCT" || (payload.intent?.category && payload.next_action !== "PROVIDE_CATEGORY")) {
        ipConversation.appendChild(renderEmptyActions(payload.intent || {}));
      }

      scrollConversation();
    }

    // ------------------------------------------------------------- sending --

    async function runChatRequest(hasImage) {
      const stopThinking = startThinking(hasImage);
      try {
        const body = { messages: messages.slice(-20).map(({ role, content }) => ({ role, content })) };
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
        stopThinking();
        messages.push({ role: "assistant", content: payload.reply });
        await renderAssistantTurn(payload);
        clearImage();
      } catch (error) {
        stopThinking();
        appendErrorTurn(error.message || "The assistant could not complete that request.");
      } finally {
        sendButton.disabled = false;
      }
    }

    async function sendMessage(event) {
      event.preventDefault();
      const content = chatInput.value.trim() || (selectedImage ? "Identify this product and suggest approved options." : "");
      if (!content) return;

      activateStage();
      appendUserTurn(content);
      messages.push({ role: "user", content });
      chatInput.value = "";
      chatInput.style.height = "auto";
      sendButton.disabled = true;

      await runChatRequest(Boolean(selectedImage));
    }

    async function sendCorrection(content) {
      activateStage();
      appendUserTurn(content);
      messages.push({ role: "user", content });
      sendButton.disabled = true;
      await runChatRequest(false);
    }

    chatForm.addEventListener("submit", sendMessage);

    // -------------------------------------------------------- review panel --

    function openReview(suggestion, options, afterEl) {
      setWorkflowStage("verify");
      rootEl.querySelector(".ip-review-panel")?.remove();
      const product = suggestion.product;
      const requiresReauthorization = Boolean(options.requiresReauthorization);
      const defaultBudget = requiresReauthorization ? suggestion.total_amount : (latestIntent?.max_budget || suggestion.total_amount);
      const note = requiresReauthorization
        ? "This option is above your current maximum. Set a new maximum explicitly and confirm; the original budget does not authorize this product."
        : "This is the only step that can create a purchase intent. Chat and images are discovery evidence, never authorization.";

      const panel = document.createElement("div");
      panel.className = "ip-panel ip-review-panel ip-pop";
      panel.innerHTML = `
        <p class="ip-panel-kicker">${requiresReauthorization ? "Reauthorization" : "Exact selection review"}</p>
        <h3>${escapeHtml(product.name)}</h3>
        <p>${escapeHtml(note)}</p>
        <div class="ip-review-fields">
          <label>Maximum total <input type="number" min="1" class="ip-review-budget" value="${escapeHtml(defaultBudget)}"></label>
          <label>Quantity <input type="number" min="1" max="100" class="ip-review-quantity" value="${escapeHtml(latestIntent?.quantity || 1)}"></label>
        </div>
        <label class="ip-review-check"><input type="checkbox" class="ip-review-confirm-check"><span>I confirm this exact product, quantity, and maximum total.</span></label>
        <button type="button" class="ip-confirm-btn" disabled>Confirm bounded intent</button>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();

      const check = panel.querySelector(".ip-review-confirm-check");
      const confirmButton = panel.querySelector(".ip-confirm-btn");
      check.addEventListener("change", () => { confirmButton.disabled = !check.checked; });

      confirmButton.addEventListener("click", () => confirmPurchase({
        suggestion,
        product,
        merchantId: suggestion.merchant_id,
        maxBudget: Number(panel.querySelector(".ip-review-budget").value),
        quantity: Number(panel.querySelector(".ip-review-quantity").value),
        panel,
        confirmButton,
      }));
    }

    async function confirmPurchase({ suggestion, product, merchantId, maxBudget, quantity, panel, confirmButton }) {
      confirmButton.disabled = true;
      confirmButton.textContent = "Verifying the selected product…";
      try {
        const response = await fetch("/visual-intents/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ merchant_id: merchantId, product_id: product.product_id, max_budget: maxBudget, quantity, confirmed: true }),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = payload.detail || payload;
          if (detail.reason_code === "BUDGET_EXCEEDED") {
            renderReaskPanel({
              message: detail.message,
              merchantId,
              product,
              quantity,
              requestedBudget: maxBudget,
              afterEl: panel,
            });
            panel.remove();
            return;
          }
          throw new Error(detail.message || "The intent could not be confirmed.");
        }
        panel.remove();
        renderTrustGate(payload);
      } catch (error) {
        confirmButton.disabled = false;
        confirmButton.textContent = "Confirm bounded intent";
        appendErrorTurn(error.message);
      }
    }

    // ------------------------------------------------------------ REASK ----

    function renderReaskPanel({ message, merchantId, product, quantity, requestedBudget, afterEl }) {
      const panel = document.createElement("div");
      panel.className = "ip-panel ip-pop";
      panel.innerHTML = `
        <p class="ip-panel-kicker" style="color:var(--accent);">REASK</p>
        <h3>Needs your confirmation</h3>
        <p>${escapeHtml(message)}</p>
        <div class="ip-reask-actions">
          <button type="button" class="ip-reask-keep">Keep ${escapeHtml(rupees(requestedBudget))} limit</button>
          <button type="button" class="ip-reask-increase primary">Increase budget</button>
        </div>
        <div class="ip-reask-increase-panel" hidden>
          <label class="ip-reask-new-budget-label">New maximum
            <input type="number" min="1" class="ip-reask-new-budget" value="${product.price * quantity}">
          </label>
          <button type="button" class="ip-confirm-btn">Confirm at this new maximum</button>
        </div>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();

      panel.querySelector(".ip-reask-keep").addEventListener("click", () => {
        panel.querySelectorAll("button").forEach((btn) => { btn.disabled = true; });
        panel.querySelector("h3").textContent = `Staying within ${rupees(requestedBudget)}`;
        panel.querySelector("p").textContent = "Choose a different option from the results above.";
      });

      panel.querySelector(".ip-reask-increase").addEventListener("click", () => {
        panel.querySelector(".ip-reask-increase-panel").hidden = false;
      });

      panel.querySelector(".ip-reask-increase-panel .ip-confirm-btn").addEventListener("click", () => {
        const newBudget = Number(panel.querySelector(".ip-reask-new-budget").value);
        const btn = panel.querySelector(".ip-reask-increase-panel .ip-confirm-btn");
        confirmPurchase({
          suggestion: {},
          product,
          merchantId,
          maxBudget: newBudget,
          quantity,
          panel,
          confirmButton: btn,
        });
      });
    }

    // -------------------------------------------------------- Trust Gate ---

    function broadcastTrustGateState(decision) {
      if (!decision) return;
      window.dispatchEvent(new CustomEvent("intentpay:trust-gate", { detail: { decision } }));
    }

    function buildTrustChecks(evaluation) {
      // Pass/fail/pending per row only -- the specific reason (real
      // numbers, real violation text) is shown once, in the decision
      // panel that follows this checklist, not repeated per-row.
      const violations = evaluation.intent_decision?.violations || evaluation.verification?.violations || [];
      const policyStatus = evaluation.merchant_policy?.status;

      return CHECK_ROWS.map((row) => {
        if (row.key === "policy") {
          if (policyStatus === "REJECTED") return { ...row, state: "fail" };
          if (policyStatus === "REVIEW_REQUIRED") return { ...row, state: "pending" };
          return { ...row, state: "pass" };
        }
        const failed = violations.some((v) => row.codes.includes(v.code));
        return { ...row, state: failed ? "fail" : "pass" };
      });
    }

    function renderTrustGate(payload) {
      setWorkflowStage("trust");
      const evaluation = payload.evaluation;
      const decision = evaluation.final_decision;
      broadcastTrustGateState(decision.decision);

      const turn = document.createElement("div");
      turn.className = "ip-turn ip-turn-assistant";
      const body = document.createElement("div");
      body.className = "ip-turn-body";
      turn.innerHTML = `<span class="ip-avatar">✦</span>`;
      turn.appendChild(body);

      const intro = document.createElement("div");
      intro.className = "ip-reply-text ip-pop";
      intro.style.marginBottom = "10px";
      intro.textContent = "Before I proceed, I'm checking the purchase against your intent and the merchant's rules.";
      body.appendChild(intro);

      const panel = document.createElement("div");
      panel.className = "ip-trust-panel ip-pop";
      panel.style.marginLeft = "0";
      panel.style.animationDelay = "150ms";
      panel.innerHTML = `<div class="ip-trust-heading"><span>Trust Gate</span></div><div class="ip-trust-checks"></div><div class="ip-trust-decision"></div>`;
      body.appendChild(panel);
      ipConversation.appendChild(turn);
      scrollConversation();

      const checksEl = panel.querySelector(".ip-trust-checks");
      const rows = buildTrustChecks(evaluation);
      rows.forEach((row, index) => {
        const rowEl = document.createElement("div");
        rowEl.className = `ip-check ${row.state}`;
        rowEl.style.animationDelay = `${index * 150}ms`;
        const icon = row.state === "pass" ? "✓" : row.state === "fail" ? "✗" : "…";
        // The specific reason (real numbers, real violation text) is not
        // repeated here -- it appears once, in the decision panel that
        // follows the checklist. This row is only a pass/fail/pending scan.
        rowEl.innerHTML = `<span class="ip-check-icon">${icon}</span><span>${escapeHtml(row.label)}</span>`;
        checksEl.appendChild(rowEl);
      });

      const decisionEl = document.createElement("div");
      decisionEl.className = "ip-pop";
      decisionEl.style.animationDelay = `${rows.length * 150 + 150}ms`;
      const copy = DECISION_COPY[decision.decision] || { label: decision.decision, note: decision.message };
      decisionEl.innerHTML = `<span class="ip-decision-badge ${decision.decision}">${copy.label}</span><p class="ip-decision-note">${escapeHtml(copy.note)} — <strong>${escapeHtml(decision.message)}</strong></p>`;
      panel.querySelector(".ip-trust-decision").appendChild(decisionEl);
      scrollConversation();

      window.setTimeout(() => {
        if (decision.decision === "ALLOW") renderPaymentPanel(payload, panel);
        else if (decision.decision === "ESCALATE") renderApprovalPanel(payload, panel);
        else if (decision.decision === "BLOCK") renderBlockPanel(evaluation, panel);
        scrollConversation();
      }, rows.length * 150 + 350);
    }

    function renderBlockPanel(evaluation, afterEl) {
      const violations = evaluation.intent_decision?.violations || evaluation.verification?.violations || [];
      const panel = document.createElement("div");
      panel.className = "ip-panel ip-pop";
      panel.style.marginLeft = "0";
      panel.innerHTML = `
        <p class="ip-panel-kicker" style="color:var(--red);">BLOCK</p>
        <h3>This purchase can't continue</h3>
        ${violations.map((v) => `<p>${escapeHtml(v.message)}</p>`).join("") || `<p>${escapeHtml(evaluation.final_decision.message)}</p>`}
      `;
      afterEl.insertAdjacentElement("afterend", panel);
    }

    // -------------------------------------------------------------- ALLOW --

    function renderPaymentPanel(payload, afterEl) {
      const product = payload.product;
      const razorpayRequest = payload.razorpay_test_request;
      const paymentAmount = razorpayRequest?.purchase?.total_amount ?? product.price;
      if (!razorpayRequest) return;

      const panel = document.createElement("div");
      panel.className = "ip-panel ip-pop";
      panel.style.marginLeft = "0";
      panel.innerHTML = `
        <span class="ip-payment-badge">NO REAL MONEY · TEST MODE</span>
        <h3>Ready for Razorpay Test Mode</h3>
        <p>Your exact product and maximum were approved by the Trust Gate. Checkout opens only after IntentPay creates a verified order for ${escapeHtml(rupees(paymentAmount))}.</p>
        <button type="button" class="ip-pay-btn">Open Razorpay Checkout ↗</button>
        <button type="button" class="ip-reconcile-btn" hidden>Refresh payment status</button>
        <p class="ip-pay-status" aria-live="polite">Creating payment…</p>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();

      const payButton = panel.querySelector(".ip-pay-btn");
      const reconcileButton = panel.querySelector(".ip-reconcile-btn");
      const statusEl = panel.querySelector(".ip-pay-status");
      statusEl.textContent = "Test Mode only. The server verifies the Checkout signature.";
      let localPaymentId = null;

      payButton.addEventListener("click", async () => {
        setWorkflowStage("payment");
        payButton.disabled = true;
        payButton.textContent = "Preparing Checkout…";
        statusEl.className = "ip-pay-status";
        statusEl.textContent = "Creating payment…";

        if (!window.IntentPayRazorpay?.open) {
          statusEl.className = "ip-pay-status is-error";
          statusEl.textContent = "The Razorpay Checkout module is unavailable. Refresh the page and try again.";
          payButton.disabled = false;
          payButton.textContent = "Open Razorpay Checkout ↗";
          return;
        }

        await window.IntentPayRazorpay.open({
          request: razorpayRequest,
          onStatus: (message) => { statusEl.className = "ip-pay-status"; statusEl.textContent = message; },
          onComplete: ({ verification, localPaymentId: createdPaymentId }) => {
            localPaymentId = createdPaymentId;
            payButton.disabled = true;
            payButton.textContent = "Checkout signature verified";
            reconcileButton.hidden = false;
            statusEl.className = "ip-pay-status is-success";
            statusEl.textContent = verification.awaiting_captured_webhook
              ? "Payment authorized. Waiting for the signed captured webhook before fulfillment."
              : "Payment captured.";
            renderProvePanel(payload, panel, { captured: !verification.awaiting_captured_webhook });
          },
          onError: (error) => {
            payButton.disabled = false;
            payButton.textContent = "Try Razorpay Checkout again ↗";
            reconcileButton.hidden = true;
            statusEl.className = "ip-pay-status is-error";
            statusEl.textContent = error.message || "Payment failed.";
          },
          onDismiss: () => {
            payButton.disabled = false;
            payButton.textContent = "Open Razorpay Checkout ↗";
            reconcileButton.hidden = true;
            statusEl.className = "ip-pay-status";
            statusEl.textContent = "Checkout was closed. No payment was confirmed.";
          },
        });
      });

      reconcileButton.addEventListener("click", async () => {
        if (!window.IntentPayRazorpay?.reconcile) return;
        reconcileButton.disabled = true;
        statusEl.className = "ip-pay-status";
        statusEl.textContent = "Payment status unknown — reconciling…";
        try {
          const result = await window.IntentPayRazorpay.reconcile(localPaymentId);
          if (result.payment?.status === "CAPTURED") {
            statusEl.className = "ip-pay-status is-success";
            statusEl.textContent = "Razorpay reports CAPTURED. The local payment state is now reconciled.";
            rootEl.querySelectorAll(".ip-prove-checks").forEach((el) => {
              if (!el.dataset.captured) {
                el.dataset.captured = "1";
                const span = document.createElement("span");
                span.textContent = "Payment captured";
                el.appendChild(span);
              }
            });
          } else {
            statusEl.textContent = payload.message || "Payment status unknown; try again after the webhook arrives.";
          }
        } catch (error) {
          statusEl.className = "ip-pay-status is-error";
          statusEl.textContent = error.message || "The payment status could not be checked.";
        } finally {
          reconcileButton.disabled = false;
        }
      });
    }

    // ---------------------------------------------------------- ESCALATE ---

    function renderApprovalPanel(payload, afterEl) {
      const evaluation = payload.evaluation;
      const policy = evaluation.merchant_policy;
      const reasonBits = [];
      if (policy?.threshold != null && policy?.amount != null) {
        reasonBits.push(`This purchase (${rupees(policy.amount)}) exceeds the merchant's autonomous-execution limit of ${rupees(policy.threshold)}.`);
      } else if (policy?.message) {
        reasonBits.push(policy.message);
      }

      const panel = document.createElement("div");
      panel.className = "ip-panel ip-pop";
      panel.style.marginLeft = "0";
      panel.innerHTML = `
        <p class="ip-panel-kicker" style="color:var(--violet);">ESCALATE</p>
        <h3>Merchant approval required</h3>
        <p>${escapeHtml(reasonBits.join(" "))}</p>
        <div class="ip-approval-actions">
          <button type="button" class="ip-approval-request primary">Request merchant approval</button>
          <button type="button" class="ip-approval-refresh">Check review status</button>
        </div>
        <p class="ip-approval-status" aria-live="polite"></p>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();

      const requestButton = panel.querySelector(".ip-approval-request");
      const refreshButton = panel.querySelector(".ip-approval-refresh");
      const statusEl = panel.querySelector(".ip-approval-status");

      requestButton.addEventListener("click", async () => {
        requestButton.disabled = true;
        statusEl.textContent = "Submitting the exact purchase for merchant review…";
        try {
          const response = await fetch(`/intents/${encodeURIComponent(payload.intent_id)}/merchant-approval`, { method: "POST" });
          const result = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(result.detail?.message || "The merchant approval request could not be created.");
          statusEl.textContent = `PENDING MERCHANT APPROVAL · Approval ID: ${result.approval_id || "—"}. Expires ${new Date(result.expires_at).toLocaleString()}.`;
          requestButton.textContent = "Review requested";
        } catch (error) {
          statusEl.textContent = error.message;
          requestButton.disabled = false;
        }
      });

      refreshButton.addEventListener("click", async () => {
        refreshButton.disabled = true;
        statusEl.textContent = "Re-running the Trust Gate…";
        try {
          const response = await fetch(`/intents/${encodeURIComponent(payload.intent_id)}/orchestrate`, { method: "POST" });
          const result = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(result.detail?.message || "The approval status could not be checked.");
          const refreshedDecision = result.evaluation?.final_decision?.decision;
          broadcastTrustGateState(refreshedDecision);
          if (refreshedDecision === "ALLOW") {
            renderTrustGate({
              ...payload,
              evaluation: result.evaluation,
              razorpay_test_request: {
                intent_id: payload.intent_id,
                purchase: result.evaluation.buyer_agent.proposed_purchase,
                idempotency_key: `approval-${payload.intent_id}`,
              },
            });
            return;
          }
          statusEl.textContent = refreshedDecision === "BLOCK"
            ? "The merchant or a safety check blocked this purchase. No payment order was created."
            : "The merchant review is still pending.";
        } catch (error) {
          statusEl.textContent = error.message;
        } finally {
          refreshButton.disabled = false;
        }
      });
    }

    // -------------------------------------------------------------- PROVE --

    function renderProvePanel(payload, afterEl, { captured }) {
      setWorkflowStage("audit");
      const checks = ["Intent verified", "Product verified", "Price verified", "Merchant policy passed", "Trust Gate passed", "Payment processed"];
      if (captured) checks.push("Webhook verified");
      const panel = document.createElement("div");
      panel.className = "ip-panel ip-pop";
      panel.style.marginLeft = "0";
      panel.innerHTML = `
        <p class="ip-panel-kicker">Prove</p>
        <h3>Payment ${captured ? "complete" : "verified"}</h3>
        <div class="ip-prove-checks">${checks.map((c) => `<span>${escapeHtml(c)}</span>`).join("")}</div>
        <a class="ip-audit-link" href="/audit/${encodeURIComponent(payload.intent_id)}" target="_blank" rel="noreferrer">Why did IntentPay do this? View audit trail →</a>
      `;
      afterEl.insertAdjacentElement("afterend", panel);
      scrollConversation();
    }

    // ------------------------------------------------------ intro reveal --

    if (variant === "fullscreen") {
      document.documentElement.classList.add("ip-armed");
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          rootEl.querySelectorAll(".ip-intro").forEach((el) => el.classList.add("is-in"));
        });
      });
    } else {
      chatInput.focus();
    }

    return {
      focus: () => chatInput.focus(),
    };
  }

  return { mount };
})();
