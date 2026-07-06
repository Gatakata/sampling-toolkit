const state = {
  engagements: [],
  adminEngagements: [],
  selectedEngagement: null,
  populationPreview: [],
  populationRows: [],
  sampleOutput: [],
  highValueOutput: [],
  currentRunId: null,
  lastSummary: null,
  auditLogRows: [],
  token: localStorage.getItem("authToken") || null,
  currentUser: JSON.parse(localStorage.getItem("currentUser") || "null"),
};

const url = window.location.protocol.startsWith("http")
  ? `${window.location.origin}/api`
  : "http://127.0.0.1:5000/api";
const toast = document.getElementById("toast");
const benchmarkRanges = {
  Revenue: { min: 0.5, max: 3.0, label: "0.5% to 3%" },
  "Income before tax": { min: 3.0, max: 10.0, label: "3% to 10%" },
  "Total Assets": { min: 1.0, max: 2.0, label: "1% to 2%" },
  "Gross revenue or expenditure": { min: 0.5, max: 2.0, label: "0.5% to 2%" },
};

function showToast(message, type = "success") {
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  setTimeout(() => {
    toast.className = "toast";
  }, 4000);
}

function showSuccessToast(message, duration = 4000) {
  toast.textContent = message;
  toast.className = "toast show success success-green";
  setTimeout(() => {
    toast.className = "toast";
  }, duration);
}

function getPromptResult(message, defaultValue = "") {
  try {
    return { supported: true, value: window.prompt(message, defaultValue) };
  } catch (_error) {
    return { supported: false, value: null };
  }
}

function requireTypedConfirmation(message, expected, fallbackMessage) {
  const result = getPromptResult(message);
  if (result.supported) {
    return result.value === expected;
  }
  return window.confirm(`${fallbackMessage}\n\nText prompt is not supported in this browser. Click OK to continue or Cancel to stop.`);
}

function hidePasswordWarningToast() {
  document.getElementById("passwordWarningToast")?.classList.add("hidden");
}

function showPasswordWarningToast() {
  const warningToast = document.getElementById("passwordWarningToast");
  if (!warningToast) {
    return;
  }
  warningToast.classList.remove("hidden");
}

function getInitials(value) {
  const parts = String(value || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) {
    return "?";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function getFullName(user) {
  const firstName = String(user?.first_name || "").trim();
  const surname = String(user?.surname || "").trim();
  return [firstName, surname].filter(Boolean).join(" ");
}

function getDisplayName(user) {
  return getFullName(user) || user?.username || "-";
}

function renderAvatar(element, user) {
  if (!element) {
    return;
  }
  const photo = user?.profile_picture || "";
  const initials = getInitials(getDisplayName(user));
  element.classList.toggle("has-photo", Boolean(photo));
  if (photo) {
    element.style.backgroundImage = `url("${photo}")`;
    element.textContent = "";
    return;
  }
  element.style.backgroundImage = "";
  element.textContent = initials;
}

function applyValidationErrors(prefix, errors = {}) {
  const toErrorId = field => `${prefix}${field.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase()).replace(/^[a-z]/, letter => letter.toUpperCase())}Error`;
  const baseFields = ["username", "email", "password", "first_name", "surname", "profile_picture"];
  baseFields.forEach(field => {
    const errorNode = document.getElementById(toErrorId(field));
    if (errorNode) {
      errorNode.textContent = "";
    }
  });
  Object.entries(errors || {}).forEach(([field, message]) => {
    const errorNode = document.getElementById(toErrorId(field));
    if (errorNode) {
      errorNode.textContent = message;
    }
  });
}

function formatMemberSince(value) {
  if (!value) {
    return { text: "Not recorded", muted: true };
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return { text: "Not recorded", muted: true };
  }
  return {
    text: dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }),
    muted: false,
  };
}

function closeUserMenu() {
  const menu = document.getElementById("userMenu");
  const dropdown = document.getElementById("userMenuDropdown");
  if (menu) {
    menu.classList.remove("open");
  }
  if (dropdown) {
    dropdown.classList.add("hidden");
  }
  document.getElementById("userMenuTrigger")?.setAttribute("aria-expanded", "false");
}

function toggleUserMenu(forceOpen = null) {
  const menu = document.getElementById("userMenu");
  const dropdown = document.getElementById("userMenuDropdown");
  if (!menu || !dropdown) {
    return;
  }
  const shouldOpen = forceOpen === null ? !menu.classList.contains("open") : forceOpen;
  menu.classList.toggle("open", shouldOpen);
  dropdown.classList.toggle("hidden", !shouldOpen);
  document.getElementById("userMenuTrigger")?.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function showAccountPage() {
  document.getElementById("accountPage")?.classList.remove("hidden");
  document.querySelectorAll(".tab-content").forEach(section => section.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
  closeUserMenu();
  window.scrollTo({ top: 0, behavior: "auto" });
}

function hideAccountPage() {
  document.getElementById("accountPage")?.classList.add("hidden");
}

function openPasswordModal() {
  const modal = document.getElementById("passwordModal");
  if (!modal) {
    return;
  }
  modal.classList.remove("hidden");
  document.getElementById("passwordModalError")?.classList.add("hidden");
}

function closePasswordModal() {
  document.getElementById("passwordModal")?.classList.add("hidden");
}

function updatePasswordStrength(value, fillId, labelId) {
  const fill = document.getElementById(fillId);
  const label = document.getElementById(labelId);
  if (!fill || !label) {
    return;
  }
  const password = String(value || "");
  fill.className = "password-strength-fill";
  if (!password) {
    label.textContent = "Enter a password";
    return;
  }
  let score = 0;
  if (password.length >= 10) score += 1;
  if (/[a-z]/.test(password)) score += 1;
  if (/[A-Z]/.test(password)) score += 1;
  if (/[0-9]/.test(password)) score += 1;
  if (/[^A-Za-z0-9]/.test(password)) score += 1;
  if (score <= 1) {
    fill.classList.add("level-weak");
    label.textContent = "Weak";
  } else if (score === 2) {
    fill.classList.add("level-fair");
    label.textContent = "Fair";
  } else if (score === 3 || score === 4) {
    fill.classList.add("level-good");
    label.textContent = "Good";
  } else {
    fill.classList.add("level-strong");
    label.textContent = "Strong";
  }
}

function setPasswordModalError(message) {
  const error = document.getElementById("passwordModalError");
  if (!error) {
    return;
  }
  error.textContent = message;
  error.classList.remove("hidden");
}

function clearPasswordModalError() {
  document.getElementById("passwordModalError")?.classList.add("hidden");
}

function setBenchmarkHint() {
  const benchmark = document.getElementById("materialityBenchmark").value;
  const hint = document.getElementById("benchmarkRangeHint");
  const percentInput = document.getElementById("materialityPercent");
  const range = benchmarkRanges[benchmark];
  if (!range) {
    hint.textContent = "Suggested range unavailable for selected benchmark.";
    return;
  }
  hint.textContent = `Suggested range for ${benchmark}: ${range.label}`;
  percentInput.min = String(range.min);
  percentInput.max = String(range.max);
  percentInput.step = "0.01";
}

function validateMaterialityForm() {
  const benchmark = document.getElementById("materialityBenchmark").value;
  const range = benchmarkRanges[benchmark];
  if (!range) {
    return "Invalid materiality benchmark";
  }
  const base = safeNumber(document.getElementById("materialityBase").value);
  const percent = safeNumber(document.getElementById("materialityPercent").value);
  const overall = safeNumber(document.getElementById("materiality").value);
  const perfPct = safeNumber(document.getElementById("performancePercent").value);
  const perf = safeNumber(document.getElementById("performanceMateriality").value);
  const ctPct = safeNumber(document.getElementById("clearlyTrivialPercent").value);
  const ct = safeNumber(document.getElementById("clearlyTrivialThreshold").value);

  if (base <= 0) {
    return "Benchmark figure must be greater than zero";
  }
  if (percent < range.min || percent > range.max) {
    return `Chosen benchmark % for ${benchmark} must be between ${range.min}% and ${range.max}%`;
  }
  if (overall <= 0) {
    return "Overall materiality must be greater than zero";
  }
  if (perfPct <= 0 || perfPct > 100) {
    return "Performance % must be between 0 and 100";
  }
  if (ctPct <= 0 || ctPct > 100) {
    return "Clearly Trivial % must be between 0 and 100";
  }
  if (perf <= 0) {
    return "Performance materiality must be greater than zero";
  }
  if (ct < 0) {
    return "Clearly trivial threshold cannot be negative";
  }
  if (perf > overall) {
    return "Performance materiality cannot exceed overall materiality";
  }
  if (ct > perf) {
    return "Clearly trivial threshold cannot exceed performance materiality";
  }
  return null;
}

function safeNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function clearFieldErrors(ids) {
  ids.forEach(id => {
    const field = document.getElementById(id);
    if (field) {
      field.textContent = "";
    }
  });
}

function setFieldError(id, message) {
  const field = document.getElementById(id);
  if (field) {
    field.textContent = message;
  }
}

function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((email || "").trim());
}

function validateNameField(value) {
  return /^[A-Za-z-]+$/.test((value || "").trim()) && String(value || "").trim().length <= 80;
}

function validateProfileImageFile(file) {
  if (!file) {
    return null;
  }
  if (!file.type || !file.type.startsWith("image/")) {
    return "Profile picture must be an image";
  }
  if (file.size > 2 * 1024 * 1024) {
    return "Profile picture must be 2 MB or smaller";
  }
  return null;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read profile picture"));
    reader.readAsDataURL(file);
  });
}

function validateCreateUserForm() {
  const username = document.getElementById("newUsername").value.trim();
  const firstName = document.getElementById("newFirstName").value.trim();
  const surname = document.getElementById("newSurname").value.trim();
  const email = document.getElementById("newUserEmail").value.trim();
  const password = document.getElementById("newUserPassword").value;
  const profilePicture = document.getElementById("newProfilePicture").files?.[0] || null;
  let ok = true;
  clearFieldErrors(["newUsernameError", "newFirstNameError", "newSurnameError", "newUserEmailError", "newUserPasswordError", "newProfilePictureError"]);
  if (!username) {
    setFieldError("newUsernameError", "Username is required");
    ok = false;
  }
  if (!firstName) {
    setFieldError("newFirstNameError", "First name is required");
    ok = false;
  } else if (!validateNameField(firstName)) {
    setFieldError("newFirstNameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  if (!surname) {
    setFieldError("newSurnameError", "Surname is required");
    ok = false;
  } else if (!validateNameField(surname)) {
    setFieldError("newSurnameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  if (!email) {
    setFieldError("newUserEmailError", "Email is required");
    ok = false;
  } else if (!validateEmail(email)) {
    setFieldError("newUserEmailError", "Invalid email format");
    ok = false;
  }
  if (!password || password.length < 8) {
    setFieldError("newUserPasswordError", "Minimum 8 characters");
    ok = false;
  }
  const pictureError = validateProfileImageFile(profilePicture);
  if (pictureError) {
    setFieldError("newProfilePictureError", pictureError);
    ok = false;
  }
  return ok;
}

function validateEditUserForm() {
  const username = document.getElementById("editUsername").value.trim();
  const firstName = document.getElementById("editFirstName").value.trim();
  const surname = document.getElementById("editSurname").value.trim();
  const email = document.getElementById("editUserEmail").value.trim();
  const profilePicture = document.getElementById("editProfilePicture").files?.[0] || null;
  let ok = true;
  clearFieldErrors(["editUsernameError", "editFirstNameError", "editSurnameError", "editUserEmailError", "editProfilePictureError"]);
  if (!username) {
    setFieldError("editUsernameError", "Username is required");
    ok = false;
  }
  if (!firstName) {
    setFieldError("editFirstNameError", "First name is required");
    ok = false;
  } else if (!validateNameField(firstName)) {
    setFieldError("editFirstNameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  if (!surname) {
    setFieldError("editSurnameError", "Surname is required");
    ok = false;
  } else if (!validateNameField(surname)) {
    setFieldError("editSurnameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  if (!email) {
    setFieldError("editUserEmailError", "Email is required");
    ok = false;
  } else if (!validateEmail(email)) {
    setFieldError("editUserEmailError", "Invalid email format");
    ok = false;
  }
  const pictureError = validateProfileImageFile(profilePicture);
  if (pictureError) {
    setFieldError("editProfilePictureError", pictureError);
    ok = false;
  }
  return ok;
}

function validateAccountProfileForm() {
  const firstName = document.getElementById("accountFirstName").value.trim();
  const surname = document.getElementById("accountSurname").value.trim();
  const profilePicture = document.getElementById("accountProfilePicture").files?.[0] || null;
  let ok = true;
  clearFieldErrors(["accountFirstNameError", "accountSurnameError", "accountProfilePictureError"]);
  if (!firstName) {
    setFieldError("accountFirstNameError", "First name is required");
    ok = false;
  } else if (!validateNameField(firstName)) {
    setFieldError("accountFirstNameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  if (!surname) {
    setFieldError("accountSurnameError", "Surname is required");
    ok = false;
  } else if (!validateNameField(surname)) {
    setFieldError("accountSurnameError", "Letters and hyphens only, max 80 characters");
    ok = false;
  }
  const pictureError = validateProfileImageFile(profilePicture);
  if (pictureError) {
    setFieldError("accountProfilePictureError", pictureError);
    ok = false;
  }
  return ok;
}

function validateSetPasswordForm() {
  const password = document.getElementById("setPasswordValue").value;
  const confirm = document.getElementById("confirmPasswordValue").value;
  let ok = true;
  clearFieldErrors(["setPasswordValueError", "confirmPasswordValueError"]);
  if (!password || password.length < 8) {
    setFieldError("setPasswordValueError", "Minimum 8 characters");
    ok = false;
  }
  if (password !== confirm) {
    setFieldError("confirmPasswordValueError", "Passwords do not match");
    ok = false;
  }
  return ok;
}

function formatMoney(value) {
  return safeNumber(value).toFixed(2);
}

function formatCreatedDateTime(value) {
  if (!value) {
    return { date: "-", time: "-" };
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return { date: "-", time: "-" };
  }
  const date = dt.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
  const time = dt.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return { date, time };
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) {
    return "-";
  }
  return dt.toLocaleString();
}

function setPasswordResetMode(active) {
  void active;
}

function clearAccountPasswordError() {
  const error = document.getElementById("accountPasswordError");
  if (error) {
    error.textContent = "";
    error.classList.add("hidden");
  }
}

function showAccountPasswordError(message) {
  const error = document.getElementById("accountPasswordError");
  if (!error) {
    return;
  }
  error.textContent = message;
  error.classList.remove("hidden");
}

function bindPasswordToggles() {
  document.querySelectorAll(".password-toggle").forEach(button => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-target");
      const input = document.getElementById(targetId);
      if (!input) {
        return;
      }
      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";
      button.classList.toggle("is-active", isHidden);
      button.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
    });
  });
}

function professionalRound(value) {
  const numeric = safeNumber(value);
  if (numeric <= 0) {
    return 0;
  }
  let step = 1;
  if (numeric >= 100 && numeric < 1000) {
    step = 10;
  } else if (numeric >= 1000 && numeric < 10000) {
    step = 100;
  } else if (numeric >= 10000 && numeric < 100000) {
    step = 500;
  } else if (numeric >= 100000) {
    step = 1000;
  }
  return Math.round(numeric / step) * step;
}

function deriveThresholdsFromInputs() {
  const base = safeNumber(document.getElementById("materialityBase").value);
  const percent = safeNumber(document.getElementById("materialityPercent").value);
  const performancePercent = safeNumber(document.getElementById("performancePercent").value || 75);
  const clearlyTrivialPercent = safeNumber(document.getElementById("clearlyTrivialPercent").value || 3);

  const autoOverall = professionalRound(base * (percent / 100));
  const overallField = document.getElementById("materiality");
  const overall = safeNumber(overallField.value) || autoOverall;
  const performanceMateriality = professionalRound(overall * (performancePercent / 100));
  const clearlyTrivialThreshold = professionalRound(overall * (clearlyTrivialPercent / 100));

  if (!safeNumber(overallField.value)) {
    overallField.value = String(autoOverall);
  }
  document.getElementById("performanceMateriality").value = String(performanceMateriality);
  document.getElementById("clearlyTrivialThreshold").value = String(clearlyTrivialThreshold);
  document.getElementById("calculatorMateriality").value = String(performanceMateriality);

  return {
    materiality: safeNumber(document.getElementById("materiality").value),
    performance_materiality: performanceMateriality,
    clearly_trivial_threshold: clearlyTrivialThreshold,
    performance_percent: performancePercent,
    clearly_trivial_percent: clearlyTrivialPercent,
  };
}

async function apiFetch(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }
  if (options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${url}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (response.status === 401) {
    forceLogout();
    throw new Error("Session expired. Please log in again.");
  }
  if (!response.ok) {
    const error = new Error(payload.error || "Request failed");
    if (payload.errors) {
      error.validationErrors = payload.errors;
    }
    throw error;
  }
  return payload;
}

function setSession(token, user) {
  state.token = token;
  state.currentUser = user || null;
  localStorage.setItem("authToken", token);
  localStorage.setItem("currentUser", JSON.stringify(user || null));
  document.getElementById("authPanel").classList.add("hidden");
  document.getElementById("appShell").classList.remove("hidden");
  const username = user?.username || "user";
  const displayName = getDisplayName(user);
  const roleText = user?.is_admin ? "Administrator" : "User";
  document.getElementById("sessionUsername").textContent = displayName;
  document.getElementById("sessionRole").textContent = roleText;
  renderAvatar(document.getElementById("userMenuAvatar"), user);
  renderAvatar(document.getElementById("userMenuProfileAvatar"), user);
  document.getElementById("userMenuProfileName").textContent = displayName;
  document.getElementById("userMenuProfileEmail").textContent = user?.email || "-";
  document.getElementById("userMenuProfileRole").textContent = roleText;
  document.getElementById("userMenuProfileRole").classList.toggle("admin", Boolean(user?.is_admin));
  const usersTabButton = document.getElementById("usersTabButton");
  if (usersTabButton) {
    usersTabButton.classList.toggle("hidden", !Boolean(user?.is_admin));
  }
  if (!user?.is_admin) {
    const usersSection = document.getElementById("users");
    if (usersSection && usersSection.classList.contains("active")) {
      toggleTab("dashboard");
    }
  }
  document.getElementById("userMenu")?.classList.remove("hidden");
  document.getElementById("clearPopulation")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.getElementById("sampleAdminTools")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.getElementById("deleteVoidedLogs")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.getElementById("sampleActionsHeader")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.querySelector("#engagementForm button[type='submit']")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.getElementById("loadPopulation")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  document.querySelector("#runForm button[type='submit']")?.classList.toggle("hidden", !Boolean(user?.is_admin));
  renderAccountDetails(user);
  document.body.classList.remove("login-view");
}

function forceLogout() {
  state.token = null;
  state.currentUser = null;
  localStorage.removeItem("authToken");
  localStorage.removeItem("currentUser");
  document.getElementById("authPanel").classList.remove("hidden");
  document.getElementById("appShell").classList.add("hidden");
  document.getElementById("userMenu")?.classList.add("hidden");
  closeUserMenu();
  hideAccountPage();
  closePasswordModal();
  const usersTabButton = document.getElementById("usersTabButton");
  if (usersTabButton) {
    usersTabButton.classList.add("hidden");
  }
  hidePasswordWarningToast();
  document.body.classList.add("login-view");
}

function renderAccountDetails(user = state.currentUser) {
  const username = user?.username || "-";
  const displayName = getDisplayName(user);
  const email = user?.email || "-";
  const memberSince = formatMemberSince(user?.created_at);
  const statusActive = Boolean(user?.is_active);
  const roleText = user?.is_admin ? "Administrator" : "User";
  const accountPage = document.getElementById("accountPage");
  if (accountPage) {
    const usernameNode = document.getElementById("accountPageUsername");
    const emailNode = document.getElementById("accountPageEmail");
    const roleNode = document.getElementById("accountPageRole");
    const memberNode = document.getElementById("accountPageMemberSince");
    const statusNode = document.getElementById("accountPageStatus");
    const avatarNode = document.getElementById("accountPageAvatar");
    const profileAvatarNode = document.getElementById("accountProfileAvatar");
    const nameNode = document.getElementById("accountPageName");
    const firstNameNode = document.getElementById("accountFirstName");
    const surnameNode = document.getElementById("accountSurname");
    const accountUsernameNode = document.getElementById("accountUsername");
    const accountEmailNode = document.getElementById("accountEmail");
    if (usernameNode) usernameNode.textContent = username;
    if (emailNode) emailNode.textContent = email;
    if (roleNode) {
      roleNode.textContent = roleText;
      roleNode.classList.toggle("admin", Boolean(user?.is_admin));
    }
    if (memberNode) {
      memberNode.textContent = memberSince.text;
      memberNode.classList.toggle("is-muted", memberSince.muted);
    }
    if (statusNode) {
      statusNode.innerHTML = statusActive
        ? '<span class="account-status"><span class="account-status-dot active"></span><span>Active</span></span>'
        : '<span class="account-status"><span class="account-status-dot disabled"></span><span>Disabled</span></span>';
    }
    renderAvatar(avatarNode, user);
    renderAvatar(profileAvatarNode, user);
    if (nameNode) nameNode.textContent = displayName;
    if (firstNameNode) firstNameNode.value = user?.first_name || "";
    if (surnameNode) surnameNode.value = user?.surname || "";
    if (accountUsernameNode) accountUsernameNode.value = username;
    if (accountEmailNode) accountEmailNode.value = email;
  }
  document.getElementById("accountPasswordForm")?.reset();
  clearAccountPasswordError();
  updatePasswordStrength("", "accountPasswordStrengthFill", "accountPasswordStrengthLabel");
  document.getElementById("passwordModalForm")?.reset();
  clearPasswordModalError();
  updatePasswordStrength("", "passwordModalStrengthFill", "passwordModalStrengthLabel");
}

async function loadUsers() {
  if (!state.currentUser?.is_admin) {
    return;
  }
  const rows = await apiFetch("/users");
  const tbody = document.querySelector("#usersTable tbody");
  tbody.innerHTML = "";
  rows.forEach(user => {
    const tr = document.createElement("tr");
    const isSelf = user.id === state.currentUser?.id;
    const toggleLabel = user.is_active ? "Disable" : "Enable";
    const statusClass = user.is_active ? "status-disable" : "status-enable";
    const created = formatCreatedDateTime(user.created_at);
    const fullName = getDisplayName(user);
    tr.dataset.firstName = user.first_name || "";
    tr.dataset.surname = user.surname || "";
    tr.dataset.profilePicture = user.profile_picture || "";
    if (isSelf) {
      tr.classList.add("user-self-row");
    }
    tr.innerHTML = `
      <td>${user.id}</td>
      <td>
        <div class="name-cell">
          <span class="name-text">${fullName}</span>
          <span class="username-text">@${user.username}</span>
          ${isSelf ? '<span class="you-badge">YOU</span>' : ""}
        </div>
      </td>
      <td>${user.username}</td>
      <td>${user.email}</td>
      <td>${user.is_admin ? "Administrator" : "User"}</td>
      <td>${user.is_active ? "Active" : "Inactive"}</td>
      <td>${user.must_reset_password ? "Yes" : "No"}</td>
      <td class="created-cell"><span class="created-date">${created.date}</span><span class="created-time">${created.time}</span></td>
      <td class="user-actions-cell">
        <div class="user-action-row">
          <button class="button user-action-button edit-button" data-action="edit-user" data-id="${user.id}" type="button">Edit</button>
          <button class="button user-action-button status-button ${statusClass}" data-action="toggle-status" data-id="${user.id}" ${isSelf ? "disabled" : ""} type="button">${toggleLabel}</button>
          <button class="button user-action-button password-button" data-action="reset-password" data-id="${user.id}" type="button">Set Password</button>
          <button class="button user-action-button delete-button" data-action="delete-user" data-id="${user.id}" ${isSelf ? "disabled" : ""} type="button">Delete</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function loadAdminEngagements() {
  if (!state.currentUser?.is_admin) {
    return;
  }
  const rows = await apiFetch("/admin/engagements");
  state.adminEngagements = rows;
  const tbody = document.querySelector("#engagementsAdminTable tbody");
  if (!tbody) {
    return;
  }
  tbody.innerHTML = "";
  rows.forEach(item => {
    const tr = document.createElement("tr");
    const created = formatCreatedDateTime(item.created_at);
    tr.innerHTML = `
      <td>${item.id}</td>
      <td>
        <div class="eng-name-cell">
          <span class="eng-client-name">${item.client_name || "-"}</span>
          <span class="eng-ref-text">${item.engagement_ref || "-"}</span>
        </div>
      </td>
      <td>${item.auditor_name || "-"}</td>
      <td>${item.financial_year || "-"}</td>
      <td>${item.materiality_benchmark || "-"}</td>
      <td>${formatMoney(item.materiality)}</td>
      <td>${formatMoney(item.performance_materiality)}</td>
      <td>${formatMoney(item.clearly_trivial_threshold)}</td>
      <td>${item.created_by || "-"}</td>
      <td class="eng-created-cell"><span class="created-date">${created.date}</span><span class="created-time">${created.time}</span></td>
      <td class="eng-actions-cell">
        <div class="eng-action-row">
          <button class="button secondary" data-action="edit-engagement" data-id="${item.id}" type="button">Edit</button>
          <button class="button danger" data-action="delete-engagement" data-id="${item.id}" type="button">Delete</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

function sortTable(tableId, columnIndex) {
  const table = document.getElementById(tableId);
  const tbody = table.querySelector("tbody");
  const rows = Array.from(tbody.querySelectorAll("tr"));
  const ascending = table.dataset.sortOrder !== "asc";
  rows.sort((a, b) => {
    const aText = a.children[columnIndex].textContent.trim();
    const bText = b.children[columnIndex].textContent.trim();
    return ascending ? aText.localeCompare(bText, undefined, { numeric: true }) : bText.localeCompare(aText, undefined, { numeric: true });
  });
  tbody.innerHTML = "";
  rows.forEach(row => tbody.appendChild(row));
  table.dataset.sortOrder = ascending ? "asc" : "desc";
}

function parseCsvLine(line) {
  const cells = [];
  let current = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      const next = line[i + 1];
      if (inQuotes && next === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }
    if (ch === "," && !inQuotes) {
      cells.push(current.trim());
      current = "";
      continue;
    }
    current += ch;
  }
  cells.push(current.trim());
  return cells;
}

function parseCsvText(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  if (!lines.length) {
    return [];
  }
  const firstRow = parseCsvLine(lines[0]).map(v => v.toLowerCase());
  const hasHeader = firstRow.includes("transaction_ref");
  const start = hasHeader ? 1 : 0;
  const parsed = [];
  for (let i = start; i < lines.length; i += 1) {
    const [transaction_ref, account_code, description, transaction_date, amount] = parseCsvLine(lines[i]);
    if (!transaction_ref) {
      continue;
    }
    parsed.push({
      transaction_ref,
      account_code,
      description,
      transaction_date,
      amount: safeNumber(amount),
    });
  }
  return parsed;
}

function normalizeColumnKey(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function readFirstMappedValue(row, aliases) {
  const entries = Object.entries(row || {});
  for (const [key, value] of entries) {
    const normalized = normalizeColumnKey(key);
    if (aliases.includes(normalized)) {
      return value;
    }
  }
  return "";
}

function normalizeSpreadsheetRows(rawRows) {
  return (rawRows || []).map(row => ({
    transaction_ref: String(readFirstMappedValue(row, ["transactionref", "transaction", "reference", "ref"]) || "").trim(),
    account_code: String(readFirstMappedValue(row, ["accountcode", "account", "accountnumber", "accountno"]) || "").trim(),
    description: String(readFirstMappedValue(row, ["description", "details", "narration"]) || "").trim(),
    transaction_date: String(readFirstMappedValue(row, ["transactiondate", "date", "postingdate"]) || "").trim(),
    amount: safeNumber(readFirstMappedValue(row, ["amount", "value", "transactionamount"])),
  })).filter(row => row.transaction_ref);
}

function rowsToCsvText(rows) {
  const headers = ["transaction_ref", "account_code", "description", "transaction_date", "amount"];
  const lines = [headers.join(",")];
  rows.forEach(row => {
    const cells = headers.map(key => {
      const value = row[key] ?? "";
      const text = String(value);
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
    });
    lines.push(cells.join(","));
  });
  return lines.join("\n");
}

function applyImportedRows(rows, sourceLabel = "file") {
  if (!rows.length) {
    throw new Error("No valid rows found in uploaded file");
  }
  state.populationPreview = rows;
  document.getElementById("csvInput").value = rowsToCsvText(rows);
  document.getElementById("populationFileMeta").textContent = `${rows.length} rows loaded from ${sourceLabel}`;
  renderCsvPreview(rows);
  document.getElementById("populationSize").value = String(rows.length);
  updateCalculator().catch(error => showToast(error.message, "error"));
}

function readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Unable to read file"));
    reader.readAsText(file);
  });
}

function readFileAsArrayBuffer(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("Unable to read file"));
    reader.readAsArrayBuffer(file);
  });
}

async function parsePopulationFile(file) {
  const lowerName = String(file?.name || "").toLowerCase();
  if (!file) {
    throw new Error("Select a file first");
  }
  if (lowerName.endsWith(".csv") || String(file.type || "").includes("csv")) {
    const text = await readFileAsText(file);
    return parseCsvText(text);
  }
  if (lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls")) {
    if (!window.XLSX) {
      throw new Error("Excel parsing library unavailable");
    }
    const buffer = await readFileAsArrayBuffer(file);
    const workbook = window.XLSX.read(buffer, { type: "array" });
    const firstSheet = workbook.SheetNames[0];
    if (!firstSheet) {
      return [];
    }
    const sheet = workbook.Sheets[firstSheet];
    const rawRows = window.XLSX.utils.sheet_to_json(sheet, { defval: "" });
    return normalizeSpreadsheetRows(rawRows);
  }
  throw new Error("Unsupported file type. Upload CSV or Excel (.xlsx/.xls)");
}

function renderCsvPreview(rows) {
  const tbody = document.querySelector("#csvPreview tbody");
  tbody.innerHTML = "";
  rows.slice(0, 10).forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.transaction_ref || ""}</td>
      <td>${row.account_code || ""}</td>
      <td>${row.description || ""}</td>
      <td>${row.transaction_date || ""}</td>
      <td>${formatMoney(row.amount)}</td>
    `;
    tbody.appendChild(tr);
  });
}

async function fetchEngagements() {
  state.engagements = await apiFetch("/engagements");
  const select = document.getElementById("engagementSelect");
  select.innerHTML = "<option value=''>Select engagement</option>";
  state.engagements.forEach(eng => {
    const option = document.createElement("option");
    option.value = String(eng.id);
    option.textContent = `${eng.client_name || "Unnamed"} · ${eng.engagement_ref || eng.id}`;
    select.appendChild(option);
  });
}

async function loadPopulationSummary() {
  if (!state.selectedEngagement) {
    return;
  }
  const performanceMateriality = safeNumber(document.getElementById("performanceMateriality").value);
  const clearlyTrivial = safeNumber(document.getElementById("clearlyTrivialThreshold").value);
  const summary = await apiFetch(
    `/engagements/${state.selectedEngagement}/population/summary?performance_materiality=${performanceMateriality}&clearly_trivial_threshold=${clearlyTrivial}`,
  );
  state.lastSummary = summary;
  document.getElementById("totalItems").textContent = summary.total_items;
  document.getElementById("totalValue").textContent = formatMoney(summary.total_value);
  document.getElementById("aboveMateriality").textContent = summary.items_above_performance_materiality;
  document.getElementById("remainingPopulation").textContent = summary.sampling_population_items;
  document.getElementById("belowClearlyTrivial").textContent = summary.items_below_clearly_trivial;
  document.getElementById("populationSize").value = String(summary.sampling_population_items);
  await renderAccountStats(summary.account_stats || []);
  await refreshHighValueOverview();
  await updateCalculator();
}

async function refreshHighValueOverview() {
  if (!state.selectedEngagement) {
    return;
  }
  const performanceMateriality = safeNumber(document.getElementById("performanceMateriality").value);
  const highValueRows = await apiFetch(`/engagements/${state.selectedEngagement}/high-value?performance_materiality=${performanceMateriality}`);
  document.getElementById("highValueThreshold").textContent = formatMoney(performanceMateriality);
  document.getElementById("highValuePopulationCount").textContent = String(highValueRows.length);
}

function updateIndicator() {
  const recommended = safeNumber(document.getElementById("recommendedSampleSize").value);
  const actual = safeNumber(document.getElementById("runSampleSize").value);
  const indicator = document.getElementById("sampleIndicator");
  const track = document.getElementById("sampleIndicatorTrack");
  if (track) {
    track.classList.remove("state-red", "state-amber", "state-green");
  }
  if (!recommended) {
    indicator.textContent = "No sample recommendation available";
    return;
  }
  if (actual >= recommended) {
    indicator.textContent = `Sufficient: ${actual} selected vs ${recommended} recommended`;
    if (track) {
      track.classList.add("state-green");
    }
  } else if (actual >= recommended * 0.8) {
    indicator.textContent = `Marginal: ${actual} selected vs ${recommended} recommended`;
    if (track) {
      track.classList.add("state-amber");
    }
  } else {
    indicator.textContent = `Insufficient: ${actual} selected vs ${recommended} recommended`;
    if (track) {
      track.classList.add("state-red");
    }
  }
}

async function updateCalculator() {
  const populationSize = safeNumber(document.getElementById("populationSize").value);
  const confidenceLevel = safeNumber(document.getElementById("confidenceLevel").value);
  const expectedErrorRate = safeNumber(document.getElementById("expectedErrorRate").value);
  const performanceMateriality = safeNumber(document.getElementById("calculatorMateriality").value);
  const samplingPopulationValue = safeNumber(state.lastSummary?.sampling_population_value);
  const derivedTolerableRate = samplingPopulationValue > 0 ? (performanceMateriality / samplingPopulationValue) * 100 : 0;
  document.getElementById("tolerableErrorRate").value = derivedTolerableRate.toFixed(4);
  const result = await apiFetch(
    `/sample-size/calculate?confidence_level=${confidenceLevel}&expected_error_rate=${expectedErrorRate}&performance_materiality=${performanceMateriality}&population_value=${samplingPopulationValue}&population_size=${populationSize}`,
  );
  const recommended = safeNumber(result.recommended_sample_size);
  document.getElementById("recommendedSampleSize").value = String(recommended);
  document.getElementById("runSampleSize").value = document.getElementById("runSampleSize").value || String(recommended);
  document.getElementById("samplingInterval").value = recommended > 0 ? (populationSize / recommended).toFixed(2) : "-";
  updateIndicator();
}

async function loadPopulationRows() {
  if (!state.selectedEngagement) {
    return;
  }
  const accountCode = document.getElementById("accountFilter").value;
  const includeHighValue = document.getElementById("includeHighValueFilter").value;
  const performanceMateriality = safeNumber(document.getElementById("performanceMateriality").value);
  const clearlyTrivial = safeNumber(document.getElementById("clearlyTrivialThreshold").value);
  const params = new URLSearchParams({
    include_high_value: includeHighValue,
    performance_materiality: String(performanceMateriality),
    clearly_trivial_threshold: String(clearlyTrivial),
  });
  if (accountCode) {
    params.set("account_code", accountCode);
  }
  state.populationRows = await apiFetch(`/engagements/${state.selectedEngagement}/population?${params.toString()}`);
  renderPopulationTable();
}

function renderPopulationTable() {
  const tbody = document.querySelector("#populationTable tbody");
  tbody.innerHTML = "";
  state.populationRows.forEach(item => {
    const highValueBadge = item.is_high_value
      ? '<span class="high-value-badge">High Value</span>'
      : "-";
    const actions = state.currentUser?.is_admin
      ? `
        <div class="population-row-actions">
          <button class="button secondary" data-action="edit" data-id="${item.id}" type="button">Edit</button>
          <button class="button secondary" data-action="delete" data-id="${item.id}" type="button">Delete</button>
        </div>
      `
      : "-";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.id}</td>
      <td>${item.transaction_ref || ""}</td>
      <td>${item.account_code || ""}</td>
      <td>${item.description || ""}</td>
      <td>${item.transaction_date || ""}</td>
      <td>${formatMoney(item.amount)}</td>
      <td>${highValueBadge}</td>
      <td>${actions}</td>
    `;
    tbody.appendChild(row);
  });
}

async function renderAccountStats(accountStatsFromSummary = null) {
  if (!state.selectedEngagement) {
    return;
  }
  const performanceMateriality = safeNumber(document.getElementById("performanceMateriality").value);
  const clearlyTrivial = safeNumber(document.getElementById("clearlyTrivialThreshold").value);
  const rows = accountStatsFromSummary || await apiFetch(
    `/engagements/${state.selectedEngagement}/population/accounts?performance_materiality=${performanceMateriality}&clearly_trivial_threshold=${clearlyTrivial}`,
  );
  const tbody = document.querySelector("#accountStatsTable tbody");
  tbody.innerHTML = "";
  rows.forEach(item => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${item.account_code || ""}</td>
      <td>${item.item_count}</td>
      <td>${formatMoney(item.total_value)}</td>
      <td>${item.high_value_count}</td>
    `;
    tbody.appendChild(tr);
  });
  const accountFilter = document.getElementById("accountFilter");
  const currentSelection = accountFilter.value;
  const options = ["<option value=''>All accounts</option>"];
  rows.forEach(item => {
    options.push(`<option value="${item.account_code || ""}">${item.account_code || "(blank)"}</option>`);
  });
  accountFilter.innerHTML = options.join("");
  accountFilter.value = currentSelection;
}

async function loadPopulationFromCsv() {
  if (!state.selectedEngagement) {
    showToast("Select an engagement first", "error");
    return;
  }
  const rows = parseCsvText(document.getElementById("csvInput").value);
  if (!rows.length) {
    showToast("No population rows parsed", "error");
    return;
  }
  const result = await apiFetch(`/engagements/${state.selectedEngagement}/population`, {
    method: "POST",
    body: JSON.stringify(rows),
  });
  showToast(`Loaded ${result.inserted} rows`);
  if (result.duplicates && result.duplicates.length) {
    showToast(`Duplicate refs skipped: ${result.duplicates.join(", ")}`, "error");
  }
  await loadPopulationSummary();
  await loadPopulationRows();
}

async function updateSelectedEngagement() {
  const selected = document.getElementById("engagementSelect").value;
  state.selectedEngagement = selected ? Number(selected) : null;
  if (!state.selectedEngagement) {
    return;
  }
  const engagement = await apiFetch(`/engagements/${state.selectedEngagement}`);
  document.getElementById("clientName").value = engagement.client_name || "";
  document.getElementById("engagementRef").value = engagement.engagement_ref || "";
  document.getElementById("auditorName").value = engagement.auditor_name || "";
  document.getElementById("financialYear").value = engagement.financial_year || "";
  document.getElementById("materialityBenchmark").value = engagement.materiality_benchmark || "Total Assets";
  setBenchmarkHint();
  document.getElementById("materialityBase").value = engagement.materiality_base || 0;
  document.getElementById("materialityPercent").value = engagement.materiality_percent || 0;
  document.getElementById("materiality").value = engagement.materiality || 0;
  document.getElementById("performancePercent").value = engagement.performance_percent || 75;
  document.getElementById("performanceMateriality").value = engagement.performance_materiality || 0;
  document.getElementById("clearlyTrivialPercent").value = engagement.clearly_trivial_percent || 3;
  document.getElementById("clearlyTrivialThreshold").value = engagement.clearly_trivial_threshold || 0;
  document.getElementById("calculatorMateriality").value = engagement.performance_materiality || 0;
  await loadPopulationSummary();
  await loadPopulationRows();
  await loadAuditLog();
  if (state.currentUser?.is_admin) {
    await loadRunSelector();
  }
}

async function runSample() {
  if (!state.selectedEngagement) {
    showToast("Select an engagement first", "error");
    return;
  }
  const method = document.getElementById("samplingMethod").value;
  const seedRaw = document.getElementById("randomSeed").value;
  const seed = seedRaw ? Number(seedRaw) : null;
  const tolerableErrorRateInput = document.getElementById("tolerableErrorRate");
  const tolerableErrorRateRaw = safeNumber(tolerableErrorRateInput.value);
  const tolerableErrorRate = tolerableErrorRateRaw > 0 ? tolerableErrorRateRaw : 5;
  if (tolerableErrorRateRaw <= 0) {
    tolerableErrorRateInput.value = String(tolerableErrorRate);
  }
  const manualIds = document.getElementById("manualIds").value
    .split(",")
    .map(id => Number(id.trim()))
    .filter(Boolean);

  const payload = {
    sampling_method: method,
    random_seed: Number.isFinite(seed) ? seed : null,
    manual_ids: manualIds,
    sample_size: safeNumber(document.getElementById("runSampleSize").value),
    confidence_level: safeNumber(document.getElementById("confidenceLevel").value),
    expected_error_rate: safeNumber(document.getElementById("expectedErrorRate").value),
    tolerable_error_rate: tolerableErrorRate,
    materiality: safeNumber(document.getElementById("materiality").value),
    performance_materiality: safeNumber(document.getElementById("performanceMateriality").value),
    clearly_trivial_threshold: safeNumber(document.getElementById("clearlyTrivialThreshold").value),
    notes: document.getElementById("runNotes").value,
    auditor_name: document.getElementById("auditorName").value || state.currentUser?.username || "system",
  };

  const result = await apiFetch(`/engagements/${state.selectedEngagement}/run-sample`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  showToast("Sample run created successfully");
  document.getElementById("resultSampleSize").textContent = result.run.sample_size;
  document.getElementById("resultHighValueCount").textContent = result.run.high_value_count;
  document.getElementById("resultMethod").textContent = String(result.run.sampling_method || "-").toUpperCase();
  document.getElementById("resultTimestamp").textContent = formatDateTime(result.run.run_timestamp);
  state.currentRunId = result.run.id;
  await loadSampleOutput(result.run.id);
  await loadHighValueOutput(result.run.id);
  await loadAuditLog();
  if (state.currentUser?.is_admin) {
    await loadRunSelector();
  }
}

function syncSamplingMethodFields(method) {
  const randomSeed = document.getElementById("randomSeed");
  const manualIds = document.getElementById("manualIds");
  const manualIdsGroup = document.getElementById("manualIdsGroup");
  const showManualIds = method === "judgemental";
  randomSeed.disabled = !(method === "random" || method === "systematic" || method === "mus" || method === "stratified");
  manualIds.disabled = !showManualIds;
  manualIdsGroup?.classList.toggle("hidden", !showManualIds);
}

async function loadRunSelector() {
  if (!state.currentUser?.is_admin || !state.selectedEngagement) {
    return;
  }
  const rows = await apiFetch(`/engagements/${state.selectedEngagement}/runs`);
  const select = document.getElementById("adminRunSelect");
  if (!select) {
    return;
  }
  select.innerHTML = "<option value=''>Select run</option>";
  rows.forEach(run => {
    const option = document.createElement("option");
    option.value = String(run.id);
    option.textContent = `Run ${run.id} - ${formatDateTime(run.run_timestamp)}${run.is_voided ? " (Voided)" : ""}`;
    select.appendChild(option);
  });
}

async function loadSampleOutput(runId) {
  state.sampleOutput = await apiFetch(`/runs/${runId}/output`);
  renderSampleOutput();
  refreshOutputMetrics();
}

async function loadHighValueOutput(runId) {
  state.highValueOutput = await apiFetch(`/runs/${runId}/high-value`);
  renderHighValueOutput();
}

function renderSampleOutput() {
  const tbody = document.querySelector("#sampleOutputTable tbody");
  tbody.innerHTML = "";
  state.sampleOutput.forEach(item => {
    const highValueBadge = item.is_high_value
      ? '<span class="high-value-badge">High Value</span>'
      : "-";
    const reason = item.selected_reason || "sample";
    const reasonBadge = `<span class="reason-badge reason-${reason}">${reason.replace(/_/g, " ")}</span>`;
    const stratumBadge = item.stratum ? `<span class="stratum-badge stratum-${item.stratum}">${item.stratum}</span>` : "-";
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.transaction_ref || ""}</td>
      <td>${item.account_code || ""}</td>
      <td>${item.description || ""}</td>
      <td>${item.transaction_date || ""}</td>
      <td>${formatMoney(item.amount)}</td>
      <td>${highValueBadge}</td>
      <td>${reasonBadge}</td>
      <td>${stratumBadge}</td>
      ${state.currentUser?.is_admin ? `<td><button class="button danger" data-action="delete-sample-item" data-id="${item.id}" type="button">Delete</button></td>` : ""}
    `;
    tbody.appendChild(row);
  });
}

function refreshOutputMetrics() {
  const totalRows = state.sampleOutput.length;
  const highValueRows = state.sampleOutput.filter(row => Boolean(row.is_high_value)).length;
  const totalAmount = state.sampleOutput.reduce((sum, row) => sum + safeNumber(row.amount), 0);
  document.getElementById("outputTotalRows").textContent = String(totalRows);
  document.getElementById("outputHighValueRows").textContent = String(highValueRows);
  document.getElementById("outputTotalAmount").textContent = formatMoney(totalAmount);
}

function renderHighValueOutput() {
  const tbody = document.querySelector("#highValueOutputTable tbody");
  if (!tbody) {
    return;
  }
  tbody.innerHTML = "";
  state.highValueOutput.forEach(item => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${item.transaction_ref || ""}</td>
      <td>${item.account_code || ""}</td>
      <td>${item.description || ""}</td>
      <td>${item.transaction_date || ""}</td>
      <td>${formatMoney(item.amount)}</td>
    `;
    tbody.appendChild(row);
  });
}

async function loadAuditLog() {
  const params = new URLSearchParams();
  const userFilter = document.getElementById("auditFilterUser")?.value?.trim();
  const methodFilter = document.getElementById("auditFilterMethod")?.value?.trim();
  const fromFilter = document.getElementById("auditFilterFrom")?.value;
  const toFilter = document.getElementById("auditFilterTo")?.value;
  const voidedFilter = document.getElementById("auditFilterVoided")?.value;
  const engagementFilter = document.getElementById("auditFilterEngagement")?.value?.trim();
  if (userFilter) {
    params.set("user", userFilter);
  }
  if (methodFilter) {
    params.set("method", methodFilter);
  }
  if (fromFilter) {
    params.set("from", fromFilter);
  }
  if (toFilter) {
    params.set("to", toFilter);
  }
  if (voidedFilter) {
    params.set("voided", voidedFilter);
  }
  let endpoint = "/audit-log";
  if (engagementFilter) {
    endpoint = `/engagements/${engagementFilter}/audit-log`;
  } else if (state.selectedEngagement) {
    endpoint = `/engagements/${state.selectedEngagement}/audit-log`;
  }
  const runs = await apiFetch(`${endpoint}${params.toString() ? `?${params.toString()}` : ""}`);
  state.auditLogRows = runs;
  document.getElementById("auditRowsCount").textContent = String(runs.length);
  document.getElementById("auditLatestTimestamp").textContent = runs.length ? formatDateTime(runs[0].run_timestamp) : "-";
  const tbody = document.querySelector("#auditLogTable tbody");
  tbody.innerHTML = "";
  runs.forEach((run, index) => {
    const overall = formatMoney(run.materiality);
    const performance = run.performance_materiality != null ? formatMoney(run.performance_materiality) : "-";
    const trivial = run.clearly_trivial_threshold != null ? formatMoney(run.clearly_trivial_threshold) : "-";
    const fullName = getFullName(run);
    const methodClass = String(run.sampling_method || "-").toLowerCase().replace(/[^a-z0-9]+/g, "-");
    const ts = formatCreatedDateTime(run.run_timestamp);
    const row = document.createElement("tr");
    row.classList.toggle("audit-voided-row", Boolean(run.is_voided));
    row.innerHTML = `
      <td>${runs.length - index}</td>
      <td class="audit-time-cell"><span class="created-date">${ts.date}</span><span class="created-time">${ts.time}</span></td>
      <td>
        <div class="audit-user-cell">
          <span class="audit-user-name">${run.user_name || "-"}</span>
          <span class="audit-user-fullname">${fullName || ""}</span>
        </div>
      </td>
      <td>${run.client_name || "-"} (${run.engagement_ref || "-"})</td>
      <td><span class="method-badge method-${methodClass}">${run.sampling_method || "-"}</span></td>
      <td>
        <div class="audit-materiality">
          <span class="mat-line overall">Overall: ${overall}</span>
          <span class="mat-line performance">Performance: ${performance}</span>
          <span class="mat-line trivial">Clearly Trivial: ${trivial}</span>
        </div>
      </td>
      <td>${run.sample_size || 0}</td>
      <td>${run.high_value_count || 0}</td>
      <td>${run.random_seed ?? "-"}</td>
      <td>${run.notes || run.details || "-"}${run.is_voided ? ' <span class="voided-tag">Voided</span>' : ""}</td>
    `;
    tbody.appendChild(row);
  });
}

function exportCsv(rows, filename, title = "Output") {
  if (!rows.length) {
    showToast("No rows to export", "error");
    return;
  }
  const report = buildReportModel(rows, title);
  const headers = report.columns.map(col => col.label);
  const csv = [
    headers.join(","),
    ...report.rows.map(row => report.columns.map(col => JSON.stringify(row[col.key] ?? "")).join(",")),
  ].join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

function exportExcel(rows, filename, title = "Output") {
  if (!rows.length) {
    showToast("No rows to export", "error");
    return;
  }
  if (!window.XLSX) {
    showToast("Excel export library unavailable", "error");
    return;
  }
  const report = buildReportModel(rows, title);
  const worksheetRows = report.rows.map(row => {
    const result = {};
    report.columns.forEach(col => {
      result[col.label] = row[col.key] ?? "";
    });
    return result;
  });
  const worksheet = window.XLSX.utils.json_to_sheet(worksheetRows);
  const workbook = window.XLSX.utils.book_new();
  window.XLSX.utils.book_append_sheet(workbook, worksheet, "Report");
  window.XLSX.writeFile(workbook, filename);
}

function exportPdf(rows, filename, title = "Output") {
  if (!rows.length) {
    showToast("No rows to export", "error");
    return;
  }
  if (!window.jspdf || !window.jspdf.jsPDF) {
    showToast("PDF export library unavailable", "error");
    return;
  }
  const report = buildReportModel(rows, title);
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const pageWidth = 595;
  const margin = 36;
  const contentWidth = pageWidth - margin * 2;
  let y = 46;

  const drawHeader = () => {
    doc.setFillColor(27, 42, 74);
    doc.rect(0, 0, pageWidth, 76, "F");
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(16);
    doc.text("VCCA Audit Sampling Toolkit", margin, 34);
    doc.setFontSize(11);
    doc.text(`${report.title} Report`, margin, 54);
    doc.setTextColor(60, 76, 100);
    doc.setFontSize(9);
    doc.text(`Generated: ${new Date().toLocaleString()}`, margin, 92);
    y = 112;

    if (report.meta?.length) {
      let x = margin;
      report.meta.forEach(meta => {
        const text = `${meta.label}: ${meta.value}`;
        const width = Math.min(180, doc.getTextWidth(text) + 18);
        doc.setFillColor(238, 242, 247);
        doc.roundedRect(x, y - 6, width, 20, 8, 8, "F");
        doc.setTextColor(31, 41, 55);
        doc.setFontSize(8.5);
        doc.text(text, x + 8, y + 7);
        x += width + 8;
      });
      y += 26;
    }
  };

  const ensureSpace = needed => {
    if (y + needed > 800) {
      doc.addPage();
      drawHeader();
    }
  };

  drawHeader();
  report.rows.forEach((row, index) => {
    const lines = [];
    report.columns.forEach(col => {
      lines.push(`${col.label}: ${String(row[col.key] ?? "-")}`);
    });
    const wrapped = lines.flatMap(line => doc.splitTextToSize(line, contentWidth));
    const blockHeight = Math.max(44, wrapped.length * 12 + 18);
    ensureSpace(blockHeight + 8);

    doc.setFillColor(245, 247, 250);
    doc.roundedRect(margin, y - 12, contentWidth, blockHeight, 6, 6, "F");
    doc.setTextColor(27, 42, 74);
    doc.setFontSize(10);
    doc.text(`${report.title} #${index + 1}`, margin + 8, y + 4);

    doc.setTextColor(51, 65, 85);
    doc.setFontSize(9);
    let lineY = y + 18;
    wrapped.forEach(line => {
      doc.text(line, margin + 10, lineY);
      lineY += 11;
    });
    y += blockHeight + 10;
  });
  doc.save(filename);
}

function printRows(rows, title) {
  if (!rows.length) {
    showToast("No rows to print", "error");
    return;
  }
  const report = buildReportModel(rows, title);
  const html = `
    <html>
      <head>
        <title>${report.title}</title>
        <style>
          body { font-family: "Segoe UI", Arial, sans-serif; margin: 28px; color: #1f2937; }
          .brand { background: #1b2a4a; color: #fff; padding: 14px 18px; border-radius: 8px; }
          .brand h1 { margin: 0; font-size: 24px; }
          .brand p { margin: 4px 0 0; font-size: 13px; opacity: 0.9; }
          .meta { margin: 16px 0; font-size: 13px; color: #4b5563; }
          .meta-pills { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 16px; }
          .meta-pill { display: inline-flex; padding: 6px 12px; border-radius: 999px; background: #eef2ff; color: #1e3a8a; font-size: 12px; font-weight: 600; }
          table { width: 100%; border-collapse: collapse; font-size: 12px; }
          th, td { border: 1px solid #d1d5db; padding: 8px; text-align: left; vertical-align: top; }
          th { background: #eef2ff; color: #1e3a8a; }
          tbody tr:nth-child(odd) { background: #f9fafb; }
        </style>
      </head>
      <body>
        <div class="brand">
          <h1>VCCA Audit Sampling Toolkit</h1>
          <p>${report.title} report</p>
        </div>
        <p class="meta">Generated: ${new Date().toLocaleString()} | Rows: ${report.rows.length}</p>
        <div class="meta-pills">${(report.meta || []).map(meta => `<span class="meta-pill">${meta.label}: ${meta.value}</span>`).join("")}</div>
        <table>
          <thead><tr>${report.columns.map(col => `<th>${col.label}</th>`).join("")}</tr></thead>
          <tbody>
            ${report.rows.map(row => `<tr>${report.columns.map(col => `<td>${row[col.key] ?? ""}</td>`).join("")}</tr>`).join("")}
          </tbody>
        </table>
      </body>
    </html>
  `;
  const printWindow = window.open("", "_blank");
  if (printWindow) {
    printWindow.document.write(html);
    printWindow.document.close();
    printWindow.focus();
    printWindow.print();
  }
}

function prettifyLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, match => match.toUpperCase());
}

function buildReportModel(rows, explicitTitle = "Output") {
  if (!rows?.length) {
    return { title: explicitTitle, columns: [], rows: [], meta: [] };
  }

  const isAudit = "event_type" in rows[0] || "run_timestamp" in rows[0];
  const isSample = "transaction_ref" in rows[0] && "population_id" in rows[0];
  const isHighValue = "transaction_ref" in rows[0] && !("population_id" in rows[0]);

  if (isAudit) {
    return {
      title: explicitTitle || "Audit Log",
      meta: [
        { label: "Rows", value: rows.length },
        { label: "Latest", value: formatDateTime(rows[0]?.run_timestamp) },
      ],
      columns: [
        { key: "timestamp", label: "Timestamp" },
        { key: "event", label: "Event" },
        { key: "user", label: "User" },
        { key: "engagement", label: "Engagement" },
        { key: "method", label: "Method" },
        { key: "overall_materiality", label: "Overall Materiality" },
        { key: "performance_materiality", label: "Performance Materiality" },
        { key: "clearly_trivial_threshold", label: "Clearly Trivial Threshold" },
        { key: "sample_size", label: "Sample Size" },
        { key: "high_value_count", label: "High Value Count" },
        { key: "random_seed", label: "Random Seed" },
        { key: "notes", label: "Notes" },
      ],
      rows: rows.map(row => ({
        timestamp: formatDateTime(row.run_timestamp),
        event: row.event_type || "sample_run_created",
        user: row.user_name || "-",
        engagement: `${row.client_name || "-"} (${row.engagement_ref || "-"})`,
        method: row.sampling_method || "-",
        overall_materiality: formatMoney(row.materiality),
        performance_materiality: row.performance_materiality != null ? formatMoney(row.performance_materiality) : "-",
        clearly_trivial_threshold: row.clearly_trivial_threshold != null ? formatMoney(row.clearly_trivial_threshold) : "-",
        sample_size: row.sample_size ?? 0,
        high_value_count: row.high_value_count ?? 0,
        random_seed: row.random_seed ?? "-",
        notes: row.notes || row.details || "-",
      })),
    };
  }

  if (isSample) {
    return {
      title: explicitTitle || "Sample Output",
      meta: [
        { label: "Rows", value: rows.length },
        { label: "High Value Rows", value: rows.filter(row => Boolean(row.is_high_value)).length },
        { label: "Total Amount", value: formatMoney(rows.reduce((sum, row) => sum + safeNumber(row.amount), 0)) },
      ],
      columns: [
        { key: "transaction_ref", label: "Transaction Ref" },
        { key: "account_code", label: "Account Code" },
        { key: "description", label: "Description" },
        { key: "transaction_date", label: "Transaction Date" },
        { key: "amount", label: "Amount" },
        { key: "is_high_value", label: "High Value" },
        { key: "selected_reason", label: "Selection Reason" },
        { key: "stratum", label: "Stratum" },
        { key: "run_id", label: "Run ID" },
      ],
      rows: rows.map(row => ({
        transaction_ref: row.transaction_ref || "-",
        account_code: row.account_code || "-",
        description: row.description || "-",
        transaction_date: row.transaction_date || "-",
        amount: formatMoney(row.amount),
        is_high_value: row.is_high_value ? "Yes" : "No",
        selected_reason: row.selected_reason || "sample",
        stratum: row.stratum || "-",
        run_id: row.run_id ?? "-",
      })),
    };
  }

  if (isHighValue) {
    return {
      title: explicitTitle || "High Value Output",
      meta: [
        { label: "Rows", value: rows.length },
        { label: "Total Amount", value: formatMoney(rows.reduce((sum, row) => sum + safeNumber(row.amount), 0)) },
      ],
      columns: [
        { key: "transaction_ref", label: "Transaction Ref" },
        { key: "account_code", label: "Account Code" },
        { key: "description", label: "Description" },
        { key: "transaction_date", label: "Transaction Date" },
        { key: "amount", label: "Amount" },
      ],
      rows: rows.map(row => ({
        transaction_ref: row.transaction_ref || "-",
        account_code: row.account_code || "-",
        description: row.description || "-",
        transaction_date: row.transaction_date || "-",
        amount: formatMoney(row.amount),
      })),
    };
  }

  const keys = Object.keys(rows[0]);
  return {
    title: explicitTitle,
    columns: keys.map(key => ({ key, label: prettifyLabel(key) })),
    rows,
    meta: [{ label: "Rows", value: rows.length }],
  };
}

function toggleTab(targetId) {
  hideAccountPage();
  const targetSection = document.getElementById(targetId);
  if (!targetSection) {
    return;
  }
  document.querySelectorAll(".tab-content").forEach(section => section.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
  targetSection.classList.add("active");
  const tabButton = document.querySelector(`.tab[data-tab='${targetId}']`);
  if (tabButton) {
    tabButton.classList.add("active");
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

function toggleSubtab(targetId) {
  document.querySelectorAll(".subtab").forEach(button => button.classList.remove("active"));
  document.querySelectorAll("#output > .card").forEach(section => {
    if (section.id === "sampleItems" || section.id === "highValueItems") {
      section.style.display = "none";
    }
  });
  document.querySelector(`[data-target='${targetId}']`).classList.add("active");
  document.getElementById(targetId).style.display = "block";
}

function wireEvents() {
  document.getElementById("adminLoginForm").addEventListener("submit", async event => {
    event.preventDefault();
    const loginErrorBanner = document.getElementById("loginErrorBanner");
    if (loginErrorBanner) {
      loginErrorBanner.classList.add("hidden");
    }
    try {
      const payload = {
        username: document.getElementById("loginUsername").value,
        password: document.getElementById("loginPassword").value,
      };
      const response = await fetch(`${url}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) {
        if (result.code === "ACCOUNT_LOCKED" && result.locked_until) {
          throw new Error(`Account locked until ${new Date(result.locked_until).toLocaleString()}`);
        }
        throw new Error(result.error || "Login failed");
      }
      setSession(result.token, result.user || { username: payload.username, is_admin: false });
      await fetchEngagements();
      await loadUsers();
      await loadAdminEngagements();
      await loadRunSelector();
      if (result.user?.must_reset_password) {
        showPasswordWarningToast();
      } else {
        hidePasswordWarningToast();
      }
      showToast("Login successful");
    } catch (error) {
      if (loginErrorBanner) {
        loginErrorBanner.classList.remove("hidden");
      }
      showToast(error.message, "error");
    }
  });

  document.getElementById("engagementForm").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const thresholds = deriveThresholdsFromInputs();
      const validationError = validateMaterialityForm();
      if (validationError) {
        throw new Error(validationError);
      }
      const data = {
        client_name: document.getElementById("clientName").value,
        engagement_ref: document.getElementById("engagementRef").value,
        auditor_name: document.getElementById("auditorName").value,
        financial_year: document.getElementById("financialYear").value,
        materiality_benchmark: document.getElementById("materialityBenchmark").value,
        materiality_base: safeNumber(document.getElementById("materialityBase").value),
        materiality_percent: safeNumber(document.getElementById("materialityPercent").value),
        materiality: thresholds.materiality,
        performance_percent: thresholds.performance_percent,
        performance_materiality: thresholds.performance_materiality,
        clearly_trivial_percent: thresholds.clearly_trivial_percent,
        clearly_trivial_threshold: thresholds.clearly_trivial_threshold,
      };
      if (state.selectedEngagement) {
        await apiFetch(`/engagements/${state.selectedEngagement}`, { method: "PUT", body: JSON.stringify(data) });
        showToast("Engagement updated");
      } else {
        await apiFetch("/engagements", { method: "POST", body: JSON.stringify(data) });
        showToast("Engagement created");
      }
      await fetchEngagements();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("createUserForm").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      if (!state.currentUser?.is_admin) {
        throw new Error("Only admins can create users");
      }
      if (!validateCreateUserForm()) {
        return;
      }
      const profilePictureFile = document.getElementById("newProfilePicture").files?.[0] || null;
      const profilePicture = profilePictureFile ? await readFileAsDataUrl(profilePictureFile) : null;
      const payload = {
        username: document.getElementById("newUsername").value,
        first_name: document.getElementById("newFirstName").value,
        surname: document.getElementById("newSurname").value,
        email: document.getElementById("newUserEmail").value,
        password: document.getElementById("newUserPassword").value,
        is_admin: document.getElementById("newUserRole").value === "administrator",
        ...(profilePicture ? { profile_picture: profilePicture } : {}),
      };
      const result = await apiFetch("/users", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showToast("User created successfully");
      document.getElementById("createUserForm").reset();
      document.getElementById("newUserRole").value = "user";
      await loadUsers();
    } catch (error) {
      if (error.validationErrors) {
        applyValidationErrors("new", error.validationErrors);
      } else {
        const msg = String(error.message || "").toLowerCase();
        if (msg.includes("username")) {
          setFieldError("newUsernameError", error.message);
        } else if (msg.includes("email")) {
          setFieldError("newUserEmailError", error.message);
        } else if (msg.includes("password")) {
          setFieldError("newUserPasswordError", error.message);
        }
      }
      showToast(error.message, "error");
    }
  });

  document.getElementById("accountProfileForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      if (!validateAccountProfileForm()) {
        return;
      }
      const profilePictureFile = document.getElementById("accountProfilePicture").files?.[0] || null;
      const profilePicture = profilePictureFile ? await readFileAsDataUrl(profilePictureFile) : null;
      const payload = {
        first_name: document.getElementById("accountFirstName").value,
        surname: document.getElementById("accountSurname").value,
        ...(profilePicture ? { profile_picture: profilePicture } : {}),
      };
      const updated = await apiFetch("/auth/profile", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      state.currentUser = updated;
      localStorage.setItem("currentUser", JSON.stringify(updated));
      setSession(state.token, updated);
      if (state.currentUser?.is_admin) {
        await loadUsers();
      }
      showToast("Profile updated successfully");
    } catch (error) {
      if (error.validationErrors) {
        applyValidationErrors("account", error.validationErrors);
      }
      showToast(error.message, "error");
    }
  });

  document.getElementById("accountPasswordForm").addEventListener("submit", async event => {
    event.preventDefault();
    clearAccountPasswordError();
    try {
      const currentPassword = document.getElementById("accountCurrentPassword").value;
      const newPassword = document.getElementById("accountNewPassword").value;
      const confirmPassword = document.getElementById("accountConfirmPassword").value;
      if (newPassword !== confirmPassword) {
        throw new Error("Passwords do not match");
      }
      await apiFetch("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      if (state.currentUser) {
        state.currentUser.must_reset_password = false;
        localStorage.setItem("currentUser", JSON.stringify(state.currentUser));
      }
      document.getElementById("accountPasswordForm").reset();
      clearAccountPasswordError();
      hidePasswordWarningToast();
      showSuccessToast("Password updated successfully.");
      await renderAccountDetails();
    } catch (error) {
      showAccountPasswordError(error.message);
    }
  });

  document.querySelector("#usersTable tbody").addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }
    const action = button.getAttribute("data-action");
    const userId = Number(button.getAttribute("data-id"));
    if (!userId || !state.currentUser?.is_admin) {
      return;
    }
    try {
      if (action === "edit-user") {
        const row = event.target.closest("tr");
        if (!row) {
          return;
        }
        document.getElementById("editUserId").value = String(userId);
        document.getElementById("editUsername").value = row.children[2].textContent.trim();
        document.getElementById("editFirstName").value = row.dataset.firstName || "";
        document.getElementById("editSurname").value = row.dataset.surname || "";
        document.getElementById("editUserEmail").value = row.children[3].textContent.trim();
        document.getElementById("editUserRole").value = row.children[4].textContent.includes("Administrator") ? "administrator" : "user";
        const editProfilePreview = document.getElementById("editProfilePreview");
        if (editProfilePreview) {
          renderAvatar(editProfilePreview, {
            username: document.getElementById("editUsername").value,
            first_name: row.dataset.firstName || "",
            surname: row.dataset.surname || "",
            profile_picture: row.dataset.profilePicture || "",
          });
        }
        document.getElementById("userEditCard").classList.remove("hidden");
        return;
      }
      if (action === "toggle-status") {
        const currentlyActive = button.textContent.trim() === "Disable";
        await apiFetch(`/users/${userId}/status`, {
          method: "PATCH",
          body: JSON.stringify({ is_active: !currentlyActive }),
        });
        showToast(`User ${currentlyActive ? "disabled" : "enabled"}`);
      }
      if (action === "reset-password") {
        document.getElementById("setPasswordUserId").value = String(userId);
        document.getElementById("setPasswordForm").reset();
        clearFieldErrors(["setPasswordValueError", "confirmPasswordValueError"]);
        document.getElementById("passwordSetCard").classList.remove("hidden");
        return;
      }
      if (action === "delete-user") {
        const row = event.target.closest("tr");
        const username = row ? row.children[2].textContent.trim() : `user ${userId}`;
        const fullName = row ? getDisplayName({ first_name: row.dataset.firstName, surname: row.dataset.surname, username }) : "";
        const label = fullName ? `${fullName} (@${username})` : username;
        const confirmed = window.confirm(`Are you sure you want to permanently delete ${label}? This action cannot be undone.`);
        if (!confirmed) {
          return;
        }
        const secondConfirmed = requireTypedConfirmation(
          "Type DELETE to confirm permanent user deletion.",
          "DELETE",
          "Permanent user deletion confirmation",
        );
        if (!secondConfirmed) {
          showToast("Deletion cancelled", "error");
          return;
        }
        await apiFetch(`/users/${userId}`, { method: "DELETE" });
        showToast("User deleted successfully");
      }
      await loadUsers();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("editUserForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      if (!validateEditUserForm()) {
        return;
      }
      const userId = Number(document.getElementById("editUserId").value);
      const profilePictureFile = document.getElementById("editProfilePicture").files?.[0] || null;
      const profilePicture = profilePictureFile ? await readFileAsDataUrl(profilePictureFile) : null;
      await apiFetch(`/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({
          username: document.getElementById("editUsername").value.trim(),
          first_name: document.getElementById("editFirstName").value.trim(),
          surname: document.getElementById("editSurname").value.trim(),
          email: document.getElementById("editUserEmail").value.trim(),
          is_admin: document.getElementById("editUserRole").value === "administrator",
          ...(profilePicture ? { profile_picture: profilePicture } : {}),
        }),
      });
      document.getElementById("userEditCard").classList.add("hidden");
      showToast("User updated successfully");
      await loadUsers();
    } catch (error) {
      if (error.validationErrors) {
        applyValidationErrors("edit", error.validationErrors);
      } else {
        const msg = String(error.message || "").toLowerCase();
        if (msg.includes("username")) {
          setFieldError("editUsernameError", error.message);
        } else if (msg.includes("email")) {
          setFieldError("editUserEmailError", error.message);
        }
      }
      showToast(error.message, "error");
    }
  });

  document.getElementById("cancelEditUser")?.addEventListener("click", () => {
    document.getElementById("userEditCard").classList.add("hidden");
  });

  document.getElementById("setPasswordForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      if (!validateSetPasswordForm()) {
        return;
      }
      const userId = Number(document.getElementById("setPasswordUserId").value);
      await apiFetch(`/users/${userId}/password`, {
        method: "PATCH",
        body: JSON.stringify({
          new_password: document.getElementById("setPasswordValue").value,
          must_reset_password: true,
        }),
      });
      document.getElementById("passwordSetCard").classList.add("hidden");
      showToast("Password updated successfully");
      await loadUsers();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("cancelSetPassword")?.addEventListener("click", () => {
    document.getElementById("passwordSetCard").classList.add("hidden");
  });

  document.getElementById("engagementSelect").addEventListener("change", () => {
    updateSelectedEngagement().catch(error => showToast(error.message, "error"));
  });

  document.getElementById("parseCsv").addEventListener("click", event => {
    event.preventDefault();
    const rows = parseCsvText(document.getElementById("csvInput").value);
    state.populationPreview = rows;
    document.getElementById("populationFileMeta").textContent = rows.length ? `${rows.length} rows parsed from text` : "No file selected.";
    renderCsvPreview(rows);
    document.getElementById("populationSize").value = String(rows.length);
    updateCalculator().catch(error => showToast(error.message, "error"));
  });

  document.getElementById("uploadPopulationFile")?.addEventListener("click", () => {
    document.getElementById("populationFileInput")?.click();
  });

  document.getElementById("populationFileInput")?.addEventListener("change", async event => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    try {
      const rows = await parsePopulationFile(file);
      applyImportedRows(rows, file.name);
      showToast(`Parsed ${rows.length} rows from ${file.name}`);
    } catch (error) {
      showToast(error.message, "error");
      document.getElementById("populationFileMeta").textContent = "No file selected.";
    } finally {
      event.target.value = "";
    }
  });

  document.getElementById("loadPopulation").addEventListener("click", event => {
    event.preventDefault();
    loadPopulationFromCsv().catch(error => showToast(error.message, "error"));
  });

  ["confidenceLevel", "expectedErrorRate"].forEach(id => {
    document.getElementById(id).addEventListener("input", () => {
      updateCalculator().catch(error => showToast(error.message, "error"));
    });
  });

  ["materialityBase", "materialityPercent", "materiality", "performancePercent", "clearlyTrivialPercent"].forEach(id => {
    document.getElementById(id).addEventListener("input", async () => {
      deriveThresholdsFromInputs();
      if (state.selectedEngagement) {
        const thresholds = deriveThresholdsFromInputs();
        await apiFetch(`/engagements/${state.selectedEngagement}`, {
          method: "PUT",
          body: JSON.stringify({
            materiality_benchmark: document.getElementById("materialityBenchmark").value,
            materiality_base: safeNumber(document.getElementById("materialityBase").value),
            materiality_percent: safeNumber(document.getElementById("materialityPercent").value),
            materiality: thresholds.materiality,
            performance_percent: thresholds.performance_percent,
            performance_materiality: thresholds.performance_materiality,
            clearly_trivial_percent: thresholds.clearly_trivial_percent,
            clearly_trivial_threshold: thresholds.clearly_trivial_threshold,
          }),
        });
        await loadPopulationSummary();
        await loadPopulationRows();
      }
    });
  });

  document.getElementById("materialityBenchmark").addEventListener("change", async () => {
    setBenchmarkHint();
    deriveThresholdsFromInputs();
    if (state.selectedEngagement) {
      await apiFetch(`/engagements/${state.selectedEngagement}`, {
        method: "PUT",
        body: JSON.stringify({ materiality_benchmark: document.getElementById("materialityBenchmark").value }),
      });
    }
  });

  document.getElementById("runSampleSize").addEventListener("input", updateIndicator);

  document.getElementById("runForm").addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await runSample();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("samplingMethod").addEventListener("change", event => {
    syncSamplingMethodFields(event.target.value);
  });
  syncSamplingMethodFields(document.getElementById("samplingMethod").value);

  document.getElementById("refreshPopulation").addEventListener("click", () => {
    loadPopulationRows().catch(error => showToast(error.message, "error"));
  });

  document.getElementById("clearPopulation")?.addEventListener("click", async () => {
    if (!state.currentUser?.is_admin || !state.selectedEngagement) {
      return;
    }
    try {
      const confirmed = window.confirm("Are you sure you want to clear all population records for this engagement?");
      if (!confirmed) {
        return;
      }
      const secondConfirmed = requireTypedConfirmation(
        "Type CLEAR to confirm clearing all population rows.",
        "CLEAR",
        "Clear all population rows",
      );
      if (!secondConfirmed) {
        showToast("Clear cancelled", "error");
        return;
      }
      await apiFetch(`/engagements/${state.selectedEngagement}/population`, { method: "DELETE" });
      showToast("Population cleared successfully");
      await loadPopulationSummary();
      await loadPopulationRows();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("accountFilter").addEventListener("change", () => {
    loadPopulationRows().catch(error => showToast(error.message, "error"));
  });

  document.getElementById("includeHighValueFilter").addEventListener("change", () => {
    loadPopulationRows().catch(error => showToast(error.message, "error"));
  });

  document.querySelector("#populationTable tbody").addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]");
    if (!button) {
      return;
    }
    const action = button.getAttribute("data-action");
    const itemId = Number(button.getAttribute("data-id"));
    if (!itemId) {
      return;
    }
    if (!state.currentUser?.is_admin) {
      showToast("Admin privileges required", "error");
      return;
    }
    try {
      if (action === "delete") {
        const confirmed = window.confirm(`Delete population row ${itemId}?`);
        if (!confirmed) {
          return;
        }
        await apiFetch(`/population/${itemId}`, { method: "DELETE" });
        showToast("Population row deleted");
      }
      if (action === "edit") {
        const item = state.populationRows.find(row => row.id === itemId);
        if (!item) {
          return;
        }
        const updated = {
          transaction_ref: window.prompt("Transaction Ref", item.transaction_ref || "") ?? item.transaction_ref,
          account_code: window.prompt("Account Code", item.account_code || "") ?? item.account_code,
          description: window.prompt("Description", item.description || "") ?? item.description,
          transaction_date: window.prompt("Transaction Date", item.transaction_date || "") ?? item.transaction_date,
          amount: safeNumber(window.prompt("Amount", String(item.amount ?? 0)) ?? item.amount),
        };
        await apiFetch(`/population/${itemId}`, { method: "PUT", body: JSON.stringify(updated) });
        showToast("Population row updated");
      }
      await loadPopulationSummary();
      await loadPopulationRows();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("exportSampleCsv")?.addEventListener("click", () => exportCsv(state.sampleOutput, "sample-items.csv", "Sample Output"));
  document.getElementById("exportHighValueCsv")?.addEventListener("click", () => exportCsv(state.highValueOutput, "high-value-items.csv", "High Value Output"));
  document.getElementById("exportSampleExcel")?.addEventListener("click", () => exportExcel(state.sampleOutput, "sample-items.xlsx", "Sample Output"));
  document.getElementById("exportHighValueExcel")?.addEventListener("click", () => exportExcel(state.highValueOutput, "high-value-items.xlsx", "High Value Output"));
  document.getElementById("exportSamplePdf")?.addEventListener("click", () => exportPdf(state.sampleOutput, "sample-items.pdf", "Sample Output"));
  document.getElementById("exportHighValuePdf")?.addEventListener("click", () => exportPdf(state.highValueOutput, "high-value-items.pdf", "High Value Output"));
  document.getElementById("printSample")?.addEventListener("click", () => printRows(state.sampleOutput, "Sample Items"));
  document.getElementById("printHighValue")?.addEventListener("click", () => printRows(state.highValueOutput, "High Value Items"));

  document.querySelector("#sampleOutputTable tbody")?.addEventListener("click", async event => {
    const button = event.target.closest("button[data-action='delete-sample-item']");
    if (!button || !state.currentUser?.is_admin) {
      return;
    }
    try {
      const itemId = Number(button.getAttribute("data-id"));
      const confirmed = window.confirm("Delete this sample record?");
      if (!confirmed) {
        return;
      }
      const secondConfirmed = requireTypedConfirmation(
        "Type DELETE to confirm sample record deletion.",
        "DELETE",
        "Delete sample record",
      );
      if (!secondConfirmed) {
        showToast("Delete cancelled", "error");
        return;
      }
      await apiFetch(`/sample-output/${itemId}`, { method: "DELETE" });
      showToast("Sample record deleted successfully");
      if (state.currentRunId) {
        await loadSampleOutput(state.currentRunId);
      }
      await loadAuditLog();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("voidSampleRun")?.addEventListener("click", async () => {
    if (!state.currentUser?.is_admin) {
      return;
    }
    const runId = Number(document.getElementById("adminRunSelect")?.value || 0);
    if (!runId) {
      showToast("Select a run first", "error");
      return;
    }
    try {
      const confirmed = window.confirm("Void this sample run? This removes output and marks audit entries as voided.");
      if (!confirmed) {
        return;
      }
      const secondConfirmed = requireTypedConfirmation(
        "Type VOID to confirm this run will be voided.",
        "VOID",
        "Void sample run",
      );
      if (!secondConfirmed) {
        showToast("Void cancelled", "error");
        return;
      }
      await apiFetch(`/runs/${runId}/void`, { method: "POST" });
      showToast("Sample run voided successfully");
      state.currentRunId = null;
      state.sampleOutput = [];
      renderSampleOutput();
      await loadRunSelector();
      await loadAuditLog();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("applyAuditFilters")?.addEventListener("click", () => {
    loadAuditLog().catch(error => showToast(error.message, "error"));
  });

  document.getElementById("deleteVoidedLogs")?.addEventListener("click", async () => {
    if (!state.currentUser?.is_admin) {
      return;
    }
    try {
      const confirmed = window.confirm("Delete all voided audit log entries?");
      if (!confirmed) {
        return;
      }
      const secondConfirmed = requireTypedConfirmation(
        "Type DELETE VOIDED to confirm removal of voided log entries.",
        "DELETE VOIDED",
        "Delete voided audit log entries",
      );
      if (!secondConfirmed) {
        showToast("Delete cancelled", "error");
        return;
      }
      await apiFetch("/audit-log/voided", { method: "DELETE" });
      showToast("Voided audit log entries deleted");
      await loadAuditLog();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.querySelector("#engagementsAdminTable tbody")?.addEventListener("click", async event => {
    const button = event.target.closest("button[data-action]");
    if (!button || !state.currentUser?.is_admin) {
      return;
    }
    const action = button.getAttribute("data-action");
    const engagementId = Number(button.getAttribute("data-id"));
    const engagement = state.adminEngagements.find(item => item.id === engagementId);
    if (!engagement) {
      return;
    }
    try {
      if (action === "edit-engagement") {
        document.getElementById("editEngagementId").value = String(engagement.id);
        document.getElementById("editClientName").value = engagement.client_name || "";
        document.getElementById("editEngagementRef").value = engagement.engagement_ref || "";
        document.getElementById("editAuditorName").value = engagement.auditor_name || "";
        document.getElementById("editFinancialYear").value = engagement.financial_year || "";
        document.getElementById("editMaterialityBenchmark").value = engagement.materiality_benchmark || "Total Assets";
        document.getElementById("editMaterialityBase").value = engagement.materiality_base || 0;
        document.getElementById("editMaterialityPercent").value = engagement.materiality_percent || 0;
        document.getElementById("editMateriality").value = engagement.materiality || 0;
        document.getElementById("editPerformancePercent").value = engagement.performance_percent || 75;
        document.getElementById("editPerformanceMateriality").value = engagement.performance_materiality || 0;
        document.getElementById("editClearlyTrivialPercent").value = engagement.clearly_trivial_percent || 3;
        document.getElementById("editClearlyTrivialThreshold").value = engagement.clearly_trivial_threshold || 0;
        document.getElementById("engagementEditCard").classList.remove("hidden");
      }
      if (action === "delete-engagement") {
        const nameConfirmed = requireTypedConfirmation(
          "Deleting this engagement will permanently remove all associated population data, samples, and audit log entries. This cannot be undone. Type the client name to confirm.",
          engagement.client_name || "",
          `Delete engagement for ${engagement.client_name || "this client"}`,
        );
        if (!nameConfirmed) {
          showToast("Client name did not match. Delete cancelled.", "error");
          return;
        }
        const secondConfirmed = requireTypedConfirmation(
          "Type DELETE to permanently remove this engagement.",
          "DELETE",
          "Permanently delete engagement",
        );
        if (!secondConfirmed) {
          showToast("Delete cancelled", "error");
          return;
        }
        await apiFetch(`/engagements/${engagementId}`, { method: "DELETE" });
        showToast("Engagement deleted successfully");
        await fetchEngagements();
        await loadAdminEngagements();
      }
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("editEngagementForm")?.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      const confirmed = window.confirm("Changing materiality will affect existing sample records linked to this engagement. Proceed?");
      if (!confirmed) {
        return;
      }
      const engagementId = Number(document.getElementById("editEngagementId").value);
      await apiFetch(`/engagements/${engagementId}`, {
        method: "PUT",
        body: JSON.stringify({
          client_name: document.getElementById("editClientName").value,
          engagement_ref: document.getElementById("editEngagementRef").value,
          auditor_name: document.getElementById("editAuditorName").value,
          financial_year: document.getElementById("editFinancialYear").value,
          materiality_benchmark: document.getElementById("editMaterialityBenchmark").value,
          materiality_base: safeNumber(document.getElementById("editMaterialityBase").value),
          materiality_percent: safeNumber(document.getElementById("editMaterialityPercent").value),
          materiality: safeNumber(document.getElementById("editMateriality").value),
          performance_percent: safeNumber(document.getElementById("editPerformancePercent").value),
          performance_materiality: safeNumber(document.getElementById("editPerformanceMateriality").value),
          clearly_trivial_percent: safeNumber(document.getElementById("editClearlyTrivialPercent").value),
          clearly_trivial_threshold: safeNumber(document.getElementById("editClearlyTrivialThreshold").value),
        }),
      });
      document.getElementById("engagementEditCard").classList.add("hidden");
      showToast("Engagement updated successfully");
      await fetchEngagements();
      await loadAdminEngagements();
      if (state.selectedEngagement === engagementId) {
        await updateSelectedEngagement();
      }
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("cancelEditEngagement")?.addEventListener("click", () => {
    document.getElementById("engagementEditCard").classList.add("hidden");
  });

  document.getElementById("exportAuditCsv")?.addEventListener("click", () => exportCsv(state.auditLogRows, "audit-log.csv", "Audit Log"));
  document.getElementById("exportAuditExcel")?.addEventListener("click", () => exportExcel(state.auditLogRows, "audit-log.xlsx", "Audit Log"));
  document.getElementById("exportAuditPdf")?.addEventListener("click", () => exportPdf(state.auditLogRows, "audit-log.pdf", "Audit Log"));

  document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => toggleTab(tab.dataset.tab)));
  document.querySelectorAll(".subtab").forEach(button => button.addEventListener("click", () => toggleSubtab(button.dataset.target)));
  document.getElementById("passwordWarningClose")?.addEventListener("click", hidePasswordWarningToast);
  document.getElementById("passwordWarningAccountLink")?.addEventListener("click", event => {
    event.preventDefault();
    openPasswordModal();
  });
  document.getElementById("userMenuTrigger")?.addEventListener("click", event => {
    event.stopPropagation();
    toggleUserMenu();
  });
  document.getElementById("menuMyAccountButton")?.addEventListener("click", () => {
    showAccountPage();
  });
  document.getElementById("menuChangePasswordButton")?.addEventListener("click", () => {
    closeUserMenu();
    openPasswordModal();
  });
  document.getElementById("menuSignOutButton")?.addEventListener("click", () => {
    forceLogout();
    showToast("Signed out");
  });
  document.getElementById("passwordModalClose")?.addEventListener("click", closePasswordModal);
  document.getElementById("passwordModal")?.addEventListener("click", event => {
    if (event.target?.id === "passwordModal" || event.target?.classList?.contains("password-modal-backdrop")) {
      closePasswordModal();
    }
  });
  document.getElementById("passwordModalCurrentPassword")?.addEventListener("input", event => {
    void event;
  });
  document.getElementById("passwordModalNewPassword")?.addEventListener("input", event => {
    updatePasswordStrength(event.target.value, "passwordModalStrengthFill", "passwordModalStrengthLabel");
  });
  document.getElementById("accountNewPassword")?.addEventListener("input", event => {
    updatePasswordStrength(event.target.value, "accountPasswordStrengthFill", "accountPasswordStrengthLabel");
  });
  document.addEventListener("click", event => {
    const menu = document.getElementById("userMenu");
    if (!menu || menu.classList.contains("hidden")) {
      return;
    }
    if (!menu.contains(event.target)) {
      closeUserMenu();
    }
  });
  document.querySelectorAll("table").forEach(table => {
    table.querySelectorAll("th").forEach((th, index) => {
      th.addEventListener("click", () => sortTable(table.id, index));
    });
  });
}

async function init() {
  wireEvents();
  setBenchmarkHint();
  toggleTab("dashboard");
  bindPasswordToggles();
  document.getElementById("userMenu")?.classList.add("hidden");
  if (state.token) {
    try {
      const me = await apiFetch("/auth/me");
      setSession(state.token, me);
      await fetchEngagements();
      await loadAuditLog();
      await loadUsers();
      await loadAdminEngagements();
      await loadRunSelector();
      if (me.must_reset_password) {
        showPasswordWarningToast();
      }
    } catch (error) {
      forceLogout();
      showToast(error.message, "error");
    }
  }
}

window.addEventListener("DOMContentLoaded", init);
