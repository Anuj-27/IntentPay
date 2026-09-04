// Shared, presentation-only enhancements for the landing page and workspace.
// Never touches purchase, intent, or payment logic — those live in assistant.js.

// Shared product-image rendering for chat, home, and catalog product cards.
// Reads only from `product.images` (falling back to legacy `image_url`) —
// never a hard-coded URL — and always degrades to an inline placeholder,
// so a broken or missing image never breaks a product card.
window.IntentPayMedia = (function () {
  const PLACEHOLDER =
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 150'%3E" +
    "%3Crect width='200' height='150' fill='%23ebefe6'/%3E" +
    "%3Ccircle cx='72' cy='54' r='14' fill='%23c7d4c8'/%3E" +
    "%3Cpath d='M40 112l38-40 26 28 18-20 38 32H40z' fill='%23c7d4c8'/%3E" +
    "%3C/svg%3E";

  function imageUrls(product) {
    if (Array.isArray(product?.images) && product.images.length) {
      return product.images
        .map((image) => (typeof image === "string" ? image : image?.url))
        .filter(Boolean);
    }
    if (product?.image_url) return [product.image_url];
    return [];
  }

  function renderMediaHtml(product, escapeHtml) {
    const urls = imageUrls(product);
    const primary = urls[0] || PLACEHOLDER;
    const safeName = escapeHtml(product?.name || "Product photo");
    const media = `<div class="product-media"><img src="${escapeHtml(primary)}" alt="${safeName}" loading="lazy" onerror="this.onerror=null;this.src='${PLACEHOLDER}';this.closest('.product-media').classList.add('is-fallback');"></div>`;

    if (urls.length <= 1) return media;

    const thumbs = urls
      .slice(0, 6)
      .map(
        (url, index) => `<button type="button" class="product-thumb${index === 0 ? " is-active" : ""}" data-thumb-url="${escapeHtml(url)}" aria-label="Show image ${index + 1}"><img src="${escapeHtml(url)}" alt="" loading="lazy" onerror="this.closest('.product-thumb').hidden=true"></button>`,
      )
      .join("");
    return `${media}<div class="product-thumbs">${thumbs}</div>`;
  }

  function bindThumbSwaps(container) {
    container.querySelectorAll(".product-thumbs").forEach((thumbRow) => {
      const media = thumbRow.previousElementSibling;
      const img = media?.querySelector("img");
      if (!img) return;
      thumbRow.querySelectorAll(".product-thumb[data-thumb-url]").forEach((button) => {
        button.addEventListener("click", () => {
          img.src = button.dataset.thumbUrl;
          media.classList.remove("is-fallback");
          thumbRow
            .querySelectorAll(".product-thumb")
            .forEach((candidate) => candidate.classList.toggle("is-active", candidate === button));
        });
      });
    });
  }

  // The one ProductCard body shared by every surface that shows a
  // product: chat suggestions/upsell, the home page's search results and
  // review/confirmation screens, and the catalog browser. Always reads
  // from the canonical `product` object returned by the backend (image,
  // name, price, brand, rating, color, features) -- never from anything
  // the LLM said, so the same product always renders identically no
  // matter which step of the flow is showing it.
  function renderProductCardBody(product, escapeHtml, options = {}) {
    const subtitle = options.subtitle ?? `${product.brand} · ${product.product_id}`;
    const chipCount = options.chipCount ?? 3;
    const specChips = chipCount ? (product.features || []).slice(0, chipCount) : [];
    return `${renderMediaHtml(product, escapeHtml)}
      <h3>${escapeHtml(product.name)}</h3>
      <p class="${options.subtitleClass || ""}">${escapeHtml(subtitle)}</p>
      <div class="product-meta-row">
        ${product.rating ? `<span class="product-rating">★ ${product.rating.toFixed(1)}</span>` : ""}
        ${product.color ? `<span class="product-color">${escapeHtml(product.color)}</span>` : ""}
      </div>
      ${specChips.length ? `<div class="product-spec-chips">${specChips.map((f) => `<span>${escapeHtml(f)}</span>`).join("")}</div>` : ""}`;
  }

  return { imageUrls, renderMediaHtml, bindThumbSwaps, renderProductCardBody, PLACEHOLDER };
})();

(function () {
  const header = document.querySelector("[data-site-nav]");
  if (header) {
    const onScroll = () => header.classList.toggle("is-scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  const toggle = document.querySelector("[data-nav-toggle]");
  const panel = document.querySelector("[data-nav-panel]");
  if (toggle && panel) {
    toggle.addEventListener("click", () => {
      const isOpen = panel.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(isOpen));
      document.body.classList.toggle("nav-open", isOpen);
    });
    panel.querySelectorAll("a").forEach((link) =>
      link.addEventListener("click", () => {
        panel.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        document.body.classList.remove("nav-open");
      }),
    );
  }

  const revealTargets = document.querySelectorAll(".reveal");
  if (revealTargets.length && "IntersectionObserver" in window) {
    // Arm the hidden-start state and immediately mark already-in-view
    // elements visible in the same synchronous pass, so nothing already
    // on screen flashes to invisible before the observer's first tick.
    document.documentElement.classList.add("reveal-armed");
    const viewportHeight = window.innerHeight;
    revealTargets.forEach((el) => {
      const rect = el.getBoundingClientRect();
      if (rect.top < viewportHeight && rect.bottom > 0) el.classList.add("is-visible");
    });

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" },
    );
    revealTargets.forEach((el) => {
      if (!el.classList.contains("is-visible")) observer.observe(el);
    });
  }

  const counters = document.querySelectorAll("[data-count-to]");
  if (counters.length && "IntersectionObserver" in window) {
    const animateCount = (el) => {
      const target = Number(el.dataset.countTo);
      const suffix = el.dataset.countSuffix || "";
      const duration = 900;
      const start = performance.now();
      const step = (now) => {
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(target * eased) + suffix;
        if (progress < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };
    const counterObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animateCount(entry.target);
            counterObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.6 },
    );
    counters.forEach((el) => counterObserver.observe(el));
  }
})();
