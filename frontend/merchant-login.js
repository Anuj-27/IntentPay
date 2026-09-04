const loginForm = document.querySelector("#loginForm");
const merchantId = document.querySelector("#merchantId");
const merchantPassword = document.querySelector("#merchantPassword");
const loginSubmit = document.querySelector("#loginSubmit");
const loginError = document.querySelector("#loginError");

const registerForm = document.querySelector("#registerForm");
const registerDisplayName = document.querySelector("#registerDisplayName");
const registerMerchantId = document.querySelector("#registerMerchantId");
const registerPassword = document.querySelector("#registerPassword");
const registerSubmit = document.querySelector("#registerSubmit");
const registerError = document.querySelector("#registerError");

const modeToggle = document.querySelector("#modeToggle");
const demoHint = document.querySelector("#demoHint");
const cardTitle = document.querySelector("#cardTitle");
const cardLede = document.querySelector("#cardLede");

const forgotForm = document.querySelector("#forgotForm");
const forgotMerchantId = document.querySelector("#forgotMerchantId");
const forgotSubmit = document.querySelector("#forgotSubmit");
const forgotError = document.querySelector("#forgotError");
const forgotToggleWrap = document.querySelector("#forgotToggleWrap");
const forgotToggle = document.querySelector("#forgotToggle");
const forgotBackWrap = document.querySelector("#forgotBackWrap");
const forgotBack = document.querySelector("#forgotBack");

const resetForm = document.querySelector("#resetForm");
const resetHint = document.querySelector("#resetHint");
const resetToken = document.querySelector("#resetToken");
const resetNewPassword = document.querySelector("#resetNewPassword");
const resetSubmit = document.querySelector("#resetSubmit");
const resetError = document.querySelector("#resetError");
const resetSuccess = document.querySelector("#resetSuccess");

let mode = "login";

function setMode(nextMode) {
  mode = nextMode;
  const isRegister = mode === "register";
  const isForgot = mode === "forgot";

  loginForm.hidden = isRegister || isForgot;
  registerForm.hidden = !isRegister;
  forgotForm.hidden = !isForgot;
  resetForm.hidden = true;
  demoHint.hidden = isRegister || isForgot;
  modeToggle.hidden = isForgot;
  forgotToggleWrap.hidden = isForgot || isRegister;
  forgotBackWrap.hidden = !isForgot;

  modeToggle.textContent = isRegister
    ? "Already have an account? Log in →"
    : "New merchant? Create an account →";
  cardTitle.textContent = isRegister
    ? "Create a merchant account"
    : isForgot
      ? "Reset your password"
      : "Merchant login";
  cardLede.textContent = isRegister
    ? "Pick a store name and a merchant ID. You will start with an empty catalog you can fill in from the dashboard."
    : isForgot
      ? "Enter your merchant ID. Test Mode has no email set up, so your one-time reset token is shown right here instead."
      : "Manage your live catalog — add products, edit prices, and deactivate listings. Changes apply immediately to the buyer-facing site.";
}

modeToggle.addEventListener("click", () => setMode(mode === "login" ? "register" : "login"));
forgotToggle.addEventListener("click", () => setMode("forgot"));
forgotBack.addEventListener("click", () => setMode("login"));

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  loginSubmit.disabled = true;
  loginSubmit.textContent = "Logging in…";

  try {
    const response = await fetch("/merchant/session/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant_id: merchantId.value.trim(),
        password: merchantPassword.value,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail?.message || "Login failed. Check your merchant ID and password.");
    }
    window.location.href = "/merchant/dashboard";
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
    loginSubmit.disabled = false;
    loginSubmit.textContent = "Log in";
  }
});

registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  registerError.hidden = true;
  registerSubmit.disabled = true;
  registerSubmit.textContent = "Creating account…";

  try {
    const response = await fetch("/merchant/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        merchant_id: registerMerchantId.value.trim(),
        display_name: registerDisplayName.value.trim(),
        password: registerPassword.value,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = payload.detail;
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg).join(" ")
        : detail?.message || "Registration failed.";
      throw new Error(message);
    }
    window.location.href = "/merchant/dashboard";
  } catch (error) {
    registerError.textContent = error.message;
    registerError.hidden = false;
    registerSubmit.disabled = false;
    registerSubmit.textContent = "Create account";
  }
});

forgotForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  forgotError.hidden = true;
  forgotSubmit.disabled = true;
  forgotSubmit.textContent = "Requesting…";

  try {
    const response = await fetch("/merchant/password/forgot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ merchant_id: forgotMerchantId.value.trim() }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail?.message || "Could not start a password reset.");
    }

    resetHint.textContent = payload.reset_token
      ? payload.message
      : `${payload.message} Double-check the merchant ID and try again if you don't see a token below.`;
    resetToken.value = payload.reset_token || "";
    resetError.hidden = true;
    resetSuccess.hidden = true;
    resetForm.hidden = false;
    resetNewPassword.focus();
  } catch (error) {
    forgotError.textContent = error.message;
    forgotError.hidden = false;
  } finally {
    forgotSubmit.disabled = false;
    forgotSubmit.textContent = "Send reset token";
  }
});

resetForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetError.hidden = true;
  resetSuccess.hidden = true;
  resetSubmit.disabled = true;
  resetSubmit.textContent = "Resetting…";

  try {
    const response = await fetch("/merchant/password/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reset_token: resetToken.value.trim(),
        new_password: resetNewPassword.value,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(
        payload.detail?.message || "That reset token is invalid, already used, or expired.",
      );
    }

    resetSuccess.textContent = "Password reset. You can log in with your new password now.";
    resetSuccess.hidden = false;
    resetForm.reset();
    setTimeout(() => setMode("login"), 1600);
  } catch (error) {
    resetError.textContent = error.message;
    resetError.hidden = false;
  } finally {
    resetSubmit.disabled = false;
    resetSubmit.textContent = "Reset password";
  }
});
