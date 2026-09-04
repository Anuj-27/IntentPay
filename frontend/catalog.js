const categoryGrid = document.querySelector("#categoryGrid");
const catalogResults = document.querySelector("#catalogResults");
const resultsTitle = document.querySelector("#resultsTitle");
const resultsCount = document.querySelector("#resultsCount");
const productGrid = document.querySelector("#productGrid");

const CATEGORY_ICONS = {
  headphones: "♫",
  smartphones: "▢",
  laptops: "⌗",
  smartwatches: "◷",
  cameras: "◉",
};

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

async function loadCategories() {
  const response = await fetch("/categories");
  const data = await response.json();

  if (!data.categories?.length) {
    categoryGrid.innerHTML = '<div class="catalog-empty">No categories are configured yet.</div>';
    return;
  }

  categoryGrid.innerHTML = data.categories.map((category) => `
    <button class="category-card" type="button" data-category="${escapeHtml(category.category_id)}">
      <div class="cat-icon">${CATEGORY_ICONS[category.category_id] || "◆"}</div>
      <h3>${escapeHtml(category.display_name)}</h3>
      <p>${category.common_attributes.slice(0, 3).map(escapeHtml).join(" · ")}</p>
      <div class="merchant-count">${category.merchant_ids.length} merchant${category.merchant_ids.length === 1 ? "" : "s"}</div>
    </button>`).join("");

  categoryGrid.querySelectorAll(".category-card").forEach((card) => {
    card.addEventListener("click", () => selectCategory(card, data.categories));
  });

  const queryParams = new URLSearchParams(window.location.search);
  const requested = queryParams.get("category");
  const initialCard = requested
    ? categoryGrid.querySelector(`[data-category="${CSS.escape(requested)}"]`)
    : categoryGrid.querySelector(".category-card");
  if (initialCard) selectCategory(initialCard, data.categories);
}

async function selectCategory(card, categories) {
  categoryGrid.querySelectorAll(".category-card").forEach((c) => c.classList.toggle("is-active", c === card));
  const categoryId = card.dataset.category;
  const category = categories.find((c) => c.category_id === categoryId);

  catalogResults.hidden = false;
  resultsTitle.textContent = category?.display_name || categoryId;
  resultsCount.textContent = "Loading…";
  productGrid.innerHTML = '<div class="catalog-loading">Loading products…</div>';

  try {
    const merchantResponses = await Promise.all(
      (category?.merchant_ids || []).map((merchantId) =>
        fetch(`/products?merchant_id=${encodeURIComponent(merchantId)}&category=${encodeURIComponent(categoryId)}`)
          .then((res) => res.json())
          .catch(() => null),
      ),
    );

    const products = merchantResponses
      .filter(Boolean)
      .flatMap((res) => (res.products || []).map((product) => ({ product, merchantName: res.merchant_id })));

    resultsCount.textContent = `${products.length} product${products.length === 1 ? "" : "s"}`;

    if (!products.length) {
      productGrid.innerHTML = '<div class="catalog-empty">No active products in this category yet.</div>';
      return;
    }

    productGrid.innerHTML = products.map(({ product, merchantName }) => {
      const hint = `${product.brand} ${product.name}`;
      const href = `/?hint=${encodeURIComponent(hint)}&budget=${encodeURIComponent(product.price)}`;
      return `<article class="catalog-product-card">
        ${IntentPayMedia.renderProductCardBody(product, escapeHtml, {
          subtitle: `${merchantName} · ${product.product_id}`,
          subtitleClass: "merchant-line",
          chipCount: 0,
        })}
        <div class="price-line"><strong>${rupees(product.price)}</strong><span>${product.in_stock ? "In stock" : "Out of stock"}</span></div>
        <div class="feature-tags">${(product.features || []).slice(0, 3).map((f) => `<span>${escapeHtml(f)}</span>`).join("")}</div>
        <a class="try-link" href="${href}">Try this in the shopping tool →</a>
      </article>`;
    }).join("");
    IntentPayMedia.bindThumbSwaps(productGrid);
  } catch (error) {
    productGrid.innerHTML = '<div class="catalog-empty">Could not load products for this category.</div>';
  }
}

loadCategories();
