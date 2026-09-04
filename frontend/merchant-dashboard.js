const dashboardTitle = document.querySelector("#dashboardTitle");
const dashboardSubtitle = document.querySelector("#dashboardSubtitle");
const dashboardSummary = document.querySelector("#dashboardSummary");
const summaryTotal = document.querySelector("#summaryTotal");
const summaryActive = document.querySelector("#summaryActive");
const summaryCustom = document.querySelector("#summaryCustom");
const catalogTableBody = document.querySelector("#catalogTableBody");
const addProductButton = document.querySelector("#addProductButton");
const logoutLink = document.querySelector("#logoutLink");
const approvalList = document.querySelector("#approvalList");
const approvalRefreshButton = document.querySelector("#approvalRefreshButton");

const productModal = document.querySelector("#productModal");
const modalTitle = document.querySelector("#modalTitle");
const productForm = document.querySelector("#productForm");
const modalCancel = document.querySelector("#modalCancel");
const modalSave = document.querySelector("#modalSave");
const modalError = document.querySelector("#modalError");

const fieldProductId = document.querySelector("#fieldProductId");
const fieldName = document.querySelector("#fieldName");
const fieldCategory = document.querySelector("#fieldCategory");
const fieldBrand = document.querySelector("#fieldBrand");
const fieldPrice = document.querySelector("#fieldPrice");
const fieldRating = document.querySelector("#fieldRating");
const fieldColor = document.querySelector("#fieldColor");
const fieldModel = document.querySelector("#fieldModel");
const fieldFeatures = document.querySelector("#fieldFeatures");
const fieldInStock = document.querySelector("#fieldInStock");
const imageRowsContainer = document.querySelector("#imageRows");
const addImageButton = document.querySelector("#addImageButton");
const uploadImageButton = document.querySelector("#uploadImageButton");
const imageUploadInput = document.querySelector("#imageUploadInput");

let editingProductId = null;
let imageRows = [];
const MAX_IMAGE_ROWS = 10;
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
const ACCEPTED_UPLOAD_TYPES = ["image/png", "image/jpeg", "image/webp"];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function rupees(value) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(value);
}

function formatApprovalDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload;
    const error = new Error(detail.message || `Request failed with ${response.status}`);
    error.reasonCode = detail.reason_code;
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function loadCategories() {
  try {
    const data = await api("/categories");
    fieldCategory.innerHTML = data.categories
      .map((category) => `<option value="${escapeHtml(category.category_id)}">${escapeHtml(category.display_name)}</option>`)
      .join("");
  } catch {
    fieldCategory.innerHTML = '<option value="headphones">Headphones</option>';
  }
}

function renderCatalog(entries) {
  if (!entries.length) {
    catalogTableBody.innerHTML = '<tr><td colspan="6" class="dashboard-empty">No products yet. Add your first one.</td></tr>';
    return;
  }

  catalogTableBody.innerHTML = entries.map((entry) => {
    const product = entry.product;
    return `<tr class="${entry.is_active ? "" : "is-inactive"}" data-product-id="${escapeHtml(product.product_id)}">
      <td class="product-name-cell"><strong>${escapeHtml(product.name)}</strong><small>${escapeHtml(product.product_id)}</small></td>
      <td>${escapeHtml(product.category)}</td>
      <td>${rupees(product.price)}</td>
      <td>${product.in_stock ? "In stock" : "Out of stock"}</td>
      <td>${entry.is_active ? "" : '<span class="badge inactive">Deactivated</span>'} ${entry.is_custom ? '<span class="badge custom">Added by you</span>' : ""}</td>
      <td><div class="row-actions">
        <button type="button" data-action="edit">Edit</button>
        <button type="button" data-action="toggle" class="${entry.is_active ? "danger" : ""}">${entry.is_active ? "Deactivate" : "Activate"}</button>
      </div></td>
    </tr>`;
  }).join("");
}

async function refreshCatalog() {
  catalogTableBody.innerHTML = '<tr><td colspan="6" class="dashboard-loading">Loading your catalog…</td></tr>';
  const data = await api("/merchant/catalog");
  dashboardSummary.hidden = false;
  summaryTotal.textContent = data.count;
  summaryActive.textContent = data.products.filter((entry) => entry.is_active).length;
  summaryCustom.textContent = data.products.filter((entry) => entry.is_custom).length;
  renderCatalog(data.products);
  return data;
}

function renderApprovals(approvals) {
  if (!approvals.length) {
    approvalList.innerHTML = '<p class="dashboard-empty">No pending merchant approvals. The Trust Gate is clear.</p>';
    return;
  }

  approvalList.innerHTML = approvals.map((approval) => `
    <article class="approval-card" data-approval-id="${escapeHtml(approval.approval_id)}">
      <div class="approval-card-main">
        <div>
          <span class="approval-status">${escapeHtml(approval.status)}</span>
          <h3>${escapeHtml(approval.product_id)}</h3>
          <p>${rupees(approval.amount)} · Intent ${escapeHtml(approval.intent_id)}</p>
        </div>
        <div class="approval-meta">
          <span>Requested ${escapeHtml(formatApprovalDate(approval.created_at))}</span>
          <span>Expires ${escapeHtml(formatApprovalDate(approval.expires_at))}</span>
        </div>
      </div>
      <p class="approval-reason">${escapeHtml(approval.requested_message)}</p>
      <div class="approval-actions">
        <button type="button" data-approval-action="approve">Approve purchase</button>
        <button type="button" class="reject" data-approval-action="reject">Reject</button>
      </div>
    </article>
  `).join("");
}

async function refreshApprovals() {
  approvalList.innerHTML = '<p class="dashboard-loading">Loading approvals…</p>';
  const data = await api("/merchant/approvals");
  renderApprovals(data.approvals || []);
  return data;
}

async function reviewApproval(button, decision) {
  const card = button.closest(".approval-card");
  if (!card) return;
  const approvalId = card.dataset.approvalId;
  let reason = decision === "REJECT"
    ? window.prompt("Why is this purchase being rejected?")
    : window.prompt("Optional approval note:", "Reviewed and approved.");
  if (decision === "REJECT" && !reason?.trim()) return;
  reason = reason?.trim() || null;

  card.querySelectorAll("button").forEach((item) => { item.disabled = true; });
  try {
    const result = await api(`/merchant/approvals/${encodeURIComponent(approvalId)}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, reason }),
    });
    const finalDecision = result.evaluation?.final_decision?.decision || "REVIEWED";
    const message = finalDecision === "ALLOW"
      ? "Approved. The Trust Gate now allows payment for this exact purchase."
      : "Rejected. The Trust Gate blocked this purchase.";
    window.alert(message);
    await refreshApprovals();
  } catch (error) {
    window.alert(error.message);
    card.querySelectorAll("button").forEach((item) => { item.disabled = false; });
  }
}

function renderImageRows() {
  if (!imageRows.length) imageRows = [{ url: "", is_primary: true, fileName: null }];
  imageRowsContainer.innerHTML = imageRows
    .map((row, index) => {
      const middle = row.fileName
        ? `<div class="image-row-preview"><img src="${escapeHtml(row.url)}" alt="" loading="lazy"><span>${escapeHtml(row.fileName)}</span></div>`
        : `<input type="url" class="image-row-url" placeholder="https://example.com/product-photo.jpg" maxlength="2048" value="${escapeHtml(row.url)}">`;
      return `<div class="image-row" data-index="${index}">
        <button type="button" class="image-row-primary${row.is_primary ? " is-primary" : ""}" title="${row.is_primary ? "Primary image" : "Set as primary image"}" aria-label="Set as primary image">${row.is_primary ? "★" : "☆"}</button>
        ${middle}
        <button type="button" class="image-row-remove" aria-label="Remove this image">×</button>
      </div>`;
    })
    .join("");
  addImageButton.disabled = imageRows.length >= MAX_IMAGE_ROWS;
  uploadImageButton.disabled = imageRows.length >= MAX_IMAGE_ROWS;
}

function setImageRowsFromProduct(product) {
  const sourceImages = Array.isArray(product?.images) && product.images.length
    ? product.images
    : product?.image_url
      ? [{ url: product.image_url, is_primary: true }]
      : [];
  imageRows = sourceImages.map((image) => ({
    url: image.url,
    is_primary: Boolean(image.is_primary),
    fileName: image.url?.startsWith("data:") ? "Uploaded image" : null,
  }));
  if (imageRows.length && !imageRows.some((row) => row.is_primary)) imageRows[0].is_primary = true;
  renderImageRows();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

uploadImageButton.addEventListener("click", () => imageUploadInput.click());

imageUploadInput.addEventListener("change", async () => {
  const files = Array.from(imageUploadInput.files || []);
  imageUploadInput.value = "";
  modalError.hidden = true;

  for (const file of files) {
    if (imageRows.length >= MAX_IMAGE_ROWS) {
      modalError.textContent = `You can add up to ${MAX_IMAGE_ROWS} images per product.`;
      modalError.hidden = false;
      break;
    }
    if (!ACCEPTED_UPLOAD_TYPES.includes(file.type)) {
      modalError.textContent = `${file.name} isn't a PNG, JPEG, or WebP image.`;
      modalError.hidden = false;
      continue;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      modalError.textContent = `${file.name} is larger than 5 MB. Choose a smaller photo.`;
      modalError.hidden = false;
      continue;
    }

    try {
      const dataUrl = await fileToDataUrl(file);
      // The default blank row (no url, no fileName) is a placeholder --
      // replace it with the first real upload instead of leaving an
      // empty row behind it.
      imageRows = imageRows.filter((row) => row.url || row.fileName);
      imageRows.push({ url: dataUrl, is_primary: false, fileName: file.name });
    } catch (error) {
      modalError.textContent = error.message;
      modalError.hidden = false;
    }
  }

  if (imageRows.length && !imageRows.some((row) => row.is_primary)) imageRows[0].is_primary = true;
  renderImageRows();
});

imageRowsContainer.addEventListener("click", (event) => {
  const row = event.target.closest(".image-row");
  if (!row) return;
  const index = Number(row.dataset.index);

  if (event.target.closest(".image-row-primary")) {
    imageRows.forEach((entry, i) => { entry.is_primary = i === index; });
    renderImageRows();
  } else if (event.target.closest(".image-row-remove")) {
    imageRows.splice(index, 1);
    if (imageRows.length && !imageRows.some((entry) => entry.is_primary)) imageRows[0].is_primary = true;
    renderImageRows();
  }
});

imageRowsContainer.addEventListener("input", (event) => {
  const row = event.target.closest(".image-row");
  if (!row || !event.target.classList.contains("image-row-url")) return;
  imageRows[Number(row.dataset.index)].url = event.target.value;
});

addImageButton.addEventListener("click", () => {
  if (imageRows.length >= MAX_IMAGE_ROWS) return;
  imageRows.push({ url: "", is_primary: false });
  renderImageRows();
});

function openModal(mode, entry) {
  editingProductId = mode === "edit" ? entry.product.product_id : null;
  modalTitle.textContent = mode === "edit" ? "Edit product" : "Add product";
  modalError.hidden = true;

  const product = entry?.product;
  fieldProductId.value = product?.product_id || "";
  fieldProductId.disabled = mode === "edit";
  fieldName.value = product?.name || "";
  fieldCategory.value = product?.category || fieldCategory.options[0]?.value || "";
  fieldBrand.value = product?.brand || "";
  fieldPrice.value = product?.price ?? "";
  fieldRating.value = product?.rating ?? 4.0;
  fieldColor.value = product?.color || "";
  fieldModel.value = product?.model || "";
  fieldFeatures.value = (product?.features || []).join(", ");
  setImageRowsFromProduct(product);
  fieldInStock.checked = product?.in_stock ?? true;

  productModal.hidden = false;
  fieldProductId.disabled ? fieldName.focus() : fieldProductId.focus();
}

function closeModal() {
  productModal.hidden = true;
  productForm.reset();
}

function buildProductPayload() {
  const seenUrls = new Set();
  const images = imageRows
    .map((row) => ({ url: row.url.trim(), is_primary: Boolean(row.is_primary) }))
    .filter((row) => {
      if (!row.url || seenUrls.has(row.url)) return false;
      seenUrls.add(row.url);
      return true;
    });
  if (images.length && !images.some((image) => image.is_primary)) images[0].is_primary = true;

  return {
    product_id: fieldProductId.value.trim(),
    name: fieldName.value.trim(),
    category: fieldCategory.value,
    brand: fieldBrand.value.trim(),
    price: Number(fieldPrice.value),
    rating: Number(fieldRating.value),
    color: fieldColor.value.trim() || null,
    model: fieldModel.value.trim() || null,
    features: fieldFeatures.value.split(",").map((f) => f.trim()).filter(Boolean),
    images,
    image_url: images.find((image) => image.is_primary)?.url || null,
    in_stock: fieldInStock.checked,
  };
}

productForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  modalSave.disabled = true;
  modalSave.textContent = "Saving…";
  try {
    const payload = buildProductPayload();
    if (editingProductId) {
      await api(`/merchant/catalog/products/${encodeURIComponent(editingProductId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await api("/merchant/catalog/products", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    closeModal();
    await refreshCatalog();
  } catch (error) {
    modalError.textContent = error.message;
    modalError.hidden = false;
  } finally {
    modalSave.disabled = false;
    modalSave.textContent = "Save product";
  }
});

addProductButton.addEventListener("click", () => openModal("create"));
modalCancel.addEventListener("click", closeModal);
productModal.addEventListener("click", (event) => {
  if (event.target === productModal) closeModal();
});

catalogTableBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const productId = row.dataset.productId;

  if (button.dataset.action === "edit") {
    const data = await api("/merchant/catalog");
    const entry = data.products.find((e) => e.product.product_id === productId);
    if (entry) openModal("edit", entry);
    return;
  }

  if (button.dataset.action === "toggle") {
    const isDeactivating = !row.classList.contains("is-inactive");
    button.disabled = true;
    try {
      await api(`/merchant/catalog/products/${encodeURIComponent(productId)}/${isDeactivating ? "deactivate" : "activate"}`, {
        method: "POST",
      });
      await refreshCatalog();
    } catch (error) {
      button.disabled = false;
    }
  }
});

approvalList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-approval-action]");
  if (!button) return;
  await reviewApproval(button, button.dataset.approvalAction === "approve" ? "APPROVE" : "REJECT");
});

approvalRefreshButton.addEventListener("click", async () => {
  approvalRefreshButton.disabled = true;
  try {
    await refreshApprovals();
  } catch (error) {
    approvalList.innerHTML = `<p class="dashboard-empty">${escapeHtml(error.message)}</p>`;
  } finally {
    approvalRefreshButton.disabled = false;
  }
});

logoutLink.addEventListener("click", async (event) => {
  event.preventDefault();
  await fetch("/merchant/session/logout", { method: "POST" });
  window.location.href = "/merchant";
});

async function initialize() {
  try {
    const session = await api("/merchant/session");
    dashboardTitle.textContent = `${session.display_name}'s catalog`;
    dashboardSubtitle.textContent = `Logged in as ${session.merchant_id}. Changes here apply to the live buyer-facing catalog immediately.`;
  } catch (error) {
    if (error.status === 401) {
      window.location.href = "/merchant";
      return;
    }
  }

  await loadCategories();
  try {
    await refreshCatalog();
  } catch (error) {
    catalogTableBody.innerHTML = `<tr><td colspan="6" class="dashboard-empty">${escapeHtml(error.message)}</td></tr>`;
  }
  try {
    await refreshApprovals();
  } catch (error) {
    approvalList.innerHTML = `<p class="dashboard-empty">${escapeHtml(error.message)}</p>`;
  }
}

initialize();
