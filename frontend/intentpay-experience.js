// IntentPay Experience — hover/focus explanation swap, central-core stage
// highlight, and (when a real Trust Gate decision exists) reflecting that
// real backend state. Presentation only: this file never calls a payment
// endpoint and never decides anything — it only reads results that the
// IntentPay AI assistant (assistant.js) already got back from the backend.
(function () {
  const section = document.querySelector(".ipx-section");
  if (!section) return;

  const core = section.querySelector("#ipxCore");
  const statePill = section.querySelector("#ipxStatePill");
  const explain = section.querySelector("#ipxExplain");
  const cards = section.querySelectorAll(".ipx-card");

  const DEFAULT_EXPLAIN = explain ? explain.textContent : "";
  const HIGHLIGHT_BY_CARD = {
    "ipx-card-buy": "buy",
    "ipx-card-grow": "grow",
    "ipx-card-guard": "guard",
    "ipx-card-prove": "prove",
  };

  let activeCard = null;

  function setActive(card) {
    activeCard = card;
    if (!explain || !core) return;
    if (card) {
      explain.textContent = card.dataset.explain || DEFAULT_EXPLAIN;
      const highlightKey = Object.keys(HIGHLIGHT_BY_CARD).find((cls) => card.classList.contains(cls));
      core.dataset.highlight = highlightKey ? HIGHLIGHT_BY_CARD[highlightKey] : "";
    } else {
      explain.textContent = DEFAULT_EXPLAIN;
      delete core.dataset.highlight;
    }
  }

  const cardList = Array.from(cards);

  cards.forEach((card) => {
    card.addEventListener("mouseenter", () => setActive(card));
    card.addEventListener("focus", () => setActive(card));
    card.addEventListener("mouseleave", () => {
      if (activeCard !== card) return;
      // A card still holding keyboard focus stays the active explanation
      // even after the mouse leaves it.
      const focused = document.activeElement;
      setActive(cardList.includes(focused) ? focused : null);
    });
    card.addEventListener("blur", () => {
      if (activeCard === card) setActive(null);
    });
  });

  // ---- Real Trust Gate state, when one exists ------------------------
  // assistant.js dispatches this the moment it renders an ACTUAL backend
  // decision (ALLOW / REASK / BLOCK / ESCALATE) from /visual-intents/
  // confirm or /intents/{id}/orchestrate. Nothing here invents a state:
  // until that event fires once, the pill stays on the neutral default
  // already in the HTML ("Trust Gate").
  const STATE_LABEL = {
    ALLOW: "Payment authorized",
    REASK: "User confirmation required",
    BLOCK: "Action blocked",
    ESCALATE: "Merchant approval required",
  };

  window.addEventListener("intentpay:trust-gate", (event) => {
    if (!statePill) return;
    const decision = event.detail && event.detail.decision;
    const label = STATE_LABEL[decision];
    if (!label) return;
    statePill.textContent = label;
    statePill.dataset.state = decision;
  });
})();
