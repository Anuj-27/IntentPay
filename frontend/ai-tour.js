// IntentPay AI walkthrough — a narrated, skippable step carousel that
// explains what the assistant actually does, finishing on the real
// recorded session. Presentation only: describes real, already-built
// capabilities (BUY/GROW/GUARD/PROVE, the Trust Gate, the audit trail);
// invents nothing and never calls a payment/decision endpoint itself.
//
// Narration uses the browser's built-in Web Speech API (SpeechSynthesis)
// -- real, live text-to-speech, not a pre-recorded audio file. Some
// browsers block the very first utterance until the page has had a user
// gesture; that's a normal autoplay-policy limitation, not a bug, and
// this degrades silently (the on-screen text is always visible either
// way, so nothing is lost if narration doesn't fire immediately).
(function () {
  const tour = document.querySelector("#aiTour");
  if (!tour) return;

  const stage = document.querySelector("#aiTourStage");
  const dotsEl = document.querySelector("#aiTourDots");
  const prevBtn = document.querySelector("#aiTourPrev");
  const nextBtn = document.querySelector("#aiTourNext");
  const playPauseBtn = document.querySelector("#aiTourPlayPause");
  const muteBtn = document.querySelector("#aiTourMute");
  const skipBtn = document.querySelector("#aiTourSkip");

  const STEPS = [
    {
      tag: "Intro",
      accent: "intro",
      title: "Hi, I'm IntentPay AI",
      body: "I'm the conversational layer of IntentPay. Tell me what you want to buy, and I'll handle the rest — inside a deterministic trust boundary you control.",
    },
    {
      tag: "Buy · AI Buyer",
      accent: "buy",
      title: "I understand what you're looking for",
      body: "Describe what you need in plain language — category, brand, features, budget, quantity. I turn that into a structured request and search real, approved merchant catalogs.",
    },
    {
      tag: "Grow · Revenue Intelligence",
      accent: "grow",
      title: "I compare options honestly",
      body: "I rank real products by value, and I'll point out a meaningfully better option even above your budget — but I never spend more without your explicit reauthorization.",
    },
    {
      tag: "Guard · Trust Gate",
      accent: "guard",
      title: "Every purchase passes through my Trust Gate",
      body: "Before anything reaches payment, I verify the exact product, price, and your budget. A deterministic backend decides — Allow, Reask, Block, or Escalate to merchant review — never me.",
    },
    {
      tag: "Prove · Audit & Explainability",
      accent: "prove",
      title: "I can explain every decision",
      body: "Every check, every decision, every payment event is written to an audit trail — so you can always see exactly why something happened.",
    },
    {
      tag: "How to use it",
      accent: "live",
      title: "Try IntentPay AI yourself",
      body: "Every screen below is a real screenshot of the assistant running right now — not a mockup.",
      isGuide: true,
      gallery: [
        { src: "/assets/media/assistant-hero.png", caption: "1 · Open the assistant and describe what you want, in plain language." },
        { src: "/assets/media/assistant-results.png", caption: "2 · It searches real catalogs and shows your structured intent alongside the options." },
        { src: "/assets/media/assistant-trust-gate.png", caption: "3 · Choose one — the Trust Gate verifies everything before payment can happen." },
      ],
    },
  ];

  const AUTO_ADVANCE_MS = 7000;
  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const speechAvailable = "speechSynthesis" in window;

  let index = 0;
  let playing = true;
  let muted = false;
  let timer = null;
  let enterDirection = 1;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderDots() {
    dotsEl.innerHTML = STEPS.map((step, i) =>
      `<button type="button" class="ai-tour-dot${i === index ? " is-active" : ""}" role="tab" aria-selected="${i === index}" aria-label="Step ${i + 1}: ${escapeHtml(step.title)}" data-step="${i}"></button>`
    ).join("");
  }

  function renderStep() {
    const step = STEPS[index];
    const card = document.createElement("div");
    card.className = `ai-tour-card accent-${step.accent} enter-${enterDirection > 0 ? "right" : "left"}`;
    card.setAttribute("aria-live", "polite");

    if (step.isGuide) {
      card.innerHTML = `
        <span class="ai-tour-tag">${escapeHtml(step.tag)}</span>
        <h3>${escapeHtml(step.title)}</h3>
        <p>${escapeHtml(step.body)}</p>
        <div class="ai-tour-gallery">
          ${step.gallery.map((shot, i) => `
            <figure class="ai-tour-shot">
              <img src="${escapeHtml(shot.src)}" alt="${escapeHtml(shot.caption)}" loading="${i === 0 ? "eager" : "lazy"}">
              <figcaption>${escapeHtml(shot.caption)}</figcaption>
            </figure>`).join("")}
        </div>
        <a class="ai-tour-cta" href="/chat">Open IntentPay AI <span aria-hidden="true">&rarr;</span></a>`;
    } else {
      card.innerHTML = `
        <span class="ai-tour-tag">${escapeHtml(step.tag)}</span>
        <h3>${escapeHtml(step.title)}</h3>
        <p>${escapeHtml(step.body)}</p>`;
    }

    stage.innerHTML = "";
    stage.appendChild(card);
    if (prefersReducedMotion) card.classList.add("no-motion");

    renderDots();
    prevBtn.disabled = index === 0;
    nextBtn.disabled = index === STEPS.length - 1;

    narrate(step);
    resetTimer();
  }

  function narrate(step) {
    if (!speechAvailable) return;
    window.speechSynthesis.cancel();
    if (muted) return;
    const utterance = new SpeechSynthesisUtterance(`${step.title}. ${step.body}`);
    utterance.rate = 1;
    utterance.pitch = 1;
    window.speechSynthesis.speak(utterance);
  }

  function stopNarration() {
    if (speechAvailable) window.speechSynthesis.cancel();
  }

  function goTo(nextIndex) {
    if (nextIndex < 0 || nextIndex >= STEPS.length || nextIndex === index) return;
    enterDirection = nextIndex > index ? 1 : -1;
    index = nextIndex;
    renderStep();
  }

  function resetTimer() {
    window.clearTimeout(timer);
    if (!playing || index === STEPS.length - 1) return;
    timer = window.setTimeout(() => goTo(index + 1), AUTO_ADVANCE_MS);
  }

  prevBtn.addEventListener("click", () => goTo(index - 1));
  nextBtn.addEventListener("click", () => goTo(index + 1));
  skipBtn.addEventListener("click", () => goTo(STEPS.length - 1));

  dotsEl.addEventListener("click", (event) => {
    const dot = event.target.closest("[data-step]");
    if (!dot) return;
    goTo(Number(dot.dataset.step));
  });

  playPauseBtn.addEventListener("click", () => {
    playing = !playing;
    playPauseBtn.textContent = playing ? "⏸" : "▶";
    playPauseBtn.setAttribute("aria-label", playing ? "Pause auto-advance" : "Resume auto-advance");
    playPauseBtn.setAttribute("aria-pressed", String(!playing));
    if (speechAvailable) {
      if (playing) window.speechSynthesis.resume();
      else window.speechSynthesis.pause();
    }
    resetTimer();
  });

  muteBtn.addEventListener("click", () => {
    muted = !muted;
    muteBtn.textContent = muted ? "🔇" : "🔊";
    muteBtn.setAttribute("aria-label", muted ? "Unmute narration" : "Mute narration");
    muteBtn.setAttribute("aria-pressed", String(muted));
    if (muted) {
      stopNarration();
    } else {
      narrate(STEPS[index]);
    }
  });

  // Auto-advance pauses while the pointer is over the card, and narration
  // + timers stop entirely once the tour scrolls out of view so it never
  // keeps talking or ticking in a background tab.
  tour.addEventListener("mouseenter", () => window.clearTimeout(timer));
  tour.addEventListener("mouseleave", () => resetTimer());

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) {
          window.clearTimeout(timer);
          stopNarration();
        } else {
          resetTimer();
        }
      });
    }, { threshold: 0.35 });
    observer.observe(tour);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      window.clearTimeout(timer);
      stopNarration();
    } else {
      resetTimer();
    }
  });

  renderStep();
})();
