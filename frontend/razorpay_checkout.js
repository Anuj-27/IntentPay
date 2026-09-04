// Browser-only bridge for Razorpay Standard Checkout in Test Mode.
//
// The server remains the source of truth: it creates the order only after the
// Trust Gate returns ALLOW, and this module sends Checkout's response back to
// the server for signature verification. It never handles or stores secrets.
(function () {
  const CHECKOUT_SCRIPT_URL = "https://checkout.razorpay.com/v1/checkout.js";
  let checkoutScriptPromise = null;

  function errorFromPayload(payload, fallback) {
    const detail = payload?.detail ?? payload;
    const message = typeof detail === "string" ? detail : detail?.message;
    const error = new Error(message || fallback);
    error.reasonCode = typeof detail === "object" ? detail?.reason_code : undefined;
    return error;
  }

  async function readJson(response) {
    return response.json().catch(() => ({}));
  }

  function loadCheckoutScript() {
    if (window.Razorpay) return Promise.resolve();
    if (checkoutScriptPromise) return checkoutScriptPromise;

    checkoutScriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = CHECKOUT_SCRIPT_URL;
      script.async = true;
      script.onload = () => {
        if (window.Razorpay) {
          resolve();
        } else {
          reject(new Error("Razorpay Checkout loaded without its client API."));
        }
      };
      script.onerror = () => reject(new Error("Razorpay Checkout could not be loaded."));
      document.head.appendChild(script);
    });

    return checkoutScriptPromise;
  }

  async function createOrder(request) {
    const response = await fetch("/payments/razorpay-test/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    const payload = await readJson(response);
    if (!response.ok) {
      throw errorFromPayload(payload, `Razorpay order request failed (${response.status}).`);
    }

    const checkoutOptions = payload.checkout_options;
    const localPaymentId = payload.payment_result?.payment?.payment_id;
    if (!checkoutOptions || !localPaymentId) {
      throw errorFromPayload(
        payload,
        "The server did not return a usable Razorpay Test Mode order.",
      );
    }

    return { payload, checkoutOptions, localPaymentId };
  }

  async function verifyCheckout(localPaymentId, checkoutResponse) {
    const response = await fetch(
      `/payments/${encodeURIComponent(localPaymentId)}/razorpay-test/verify-checkout`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(checkoutResponse),
      },
    );
    const payload = await readJson(response);
    if (!response.ok) {
      throw errorFromPayload(payload, `Checkout verification failed (${response.status}).`);
    }
    if (!payload.verified) {
      throw errorFromPayload(payload, "Razorpay Checkout signature verification failed.");
    }
    return payload;
  }

  async function reconcile(localPaymentId) {
    if (!localPaymentId) throw new Error("The local payment ID is missing.");
    const response = await fetch(
      `/payments/${encodeURIComponent(localPaymentId)}/razorpay-test/reconcile`,
      { method: "POST" },
    );
    const payload = await readJson(response);
    if (!response.ok) {
      throw errorFromPayload(payload, `Payment status lookup failed (${response.status}).`);
    }
    return payload;
  }

  async function open(options) {
    const {
      request,
      onStatus = () => {},
      onComplete = () => {},
      onError = () => {},
      onDismiss = () => {},
    } = options || {};

    if (!request || typeof request !== "object") {
      onError(new Error("The bounded purchase request is missing."));
      return;
    }

    let order;
    try {
      onStatus("Creating a verified Razorpay Test Mode order…");
      order = await createOrder(request);
      onStatus("Opening Razorpay Checkout…");
      await loadCheckoutScript();
    } catch (error) {
      onError(error);
      return;
    }

    let callbackHandled = false;
    const checkoutOptions = {
      key: order.checkoutOptions.key,
      amount: order.checkoutOptions.amount,
      currency: order.checkoutOptions.currency,
      order_id: order.checkoutOptions.order_id,
      name: order.checkoutOptions.name || "IntentPay Demo",
      description: order.checkoutOptions.description,
      theme: { color: "#0f6b45" },
      handler: async (checkoutResponse) => {
        if (callbackHandled) return;
        callbackHandled = true;
        try {
          onStatus("Verifying the Checkout signature on the server…");
          const verification = await verifyCheckout(
            order.localPaymentId,
            checkoutResponse,
          );
          onComplete({
            order: order.payload,
            checkoutResponse,
            verification,
            localPaymentId: order.localPaymentId,
          });
        } catch (error) {
          onError(error, { phase: "verification", order });
        }
      },
      modal: {
        ondismiss: () => {
          if (!callbackHandled) onDismiss({ order: order.payload });
        },
      },
    };

    try {
      const checkout = new window.Razorpay(checkoutOptions);
      checkout.on("payment.failed", (failure) => {
        if (callbackHandled) return;
        callbackHandled = true;
        const description = failure?.error?.description || "The Test Mode payment failed.";
        onError(new Error(description), { phase: "payment", order, failure });
      });
      checkout.open();
    } catch (error) {
      onError(error, { phase: "checkout", order });
    }
  }

  window.IntentPayRazorpay = { open, reconcile };
})();
