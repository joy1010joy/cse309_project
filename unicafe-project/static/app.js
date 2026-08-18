"use strict";

const TOKEN_KEY = "unicafe_token";
const ADMIN_KEY = "unicafe_is_admin";
const CART_KEY = "unicafe_cart";
const CHAT_SESSION_KEY = "unicafe_chat_session";
const ORDER_STEPS = ["pending", "confirmed", "preparing", "ready", "completed"];
const STATUS_META = {
  pending: ["warning", "Pending"], confirmed: ["info", "Confirmed"], preparing: ["violet", "Preparing"],
  ready: ["success", "Ready"], completed: ["neutral", "Completed"], cancelled: ["danger", "Cancelled"]
};
const IMAGE_FALLBACKS = {
  coffee: "/static/images/menu/classic-latte.jpg",
  tea: "/static/images/menu/matcha-latte.jpg",
  dessert: "/static/images/menu/blueberry-muffin.jpg",
  bakery: "/static/images/menu/chocolate-croissant.jpg",
  snack: "/static/images/menu/chicken-sandwich.jpg",
  sandwich: "/static/images/menu/chicken-sandwich.jpg",
  toast: "/static/images/menu/cheese-toast.jpg",
  wrap: "/static/images/menu/vegan-wrap.jpg",
  default: "/static/images/menu/vegan-wrap.jpg"
};

const state = {
  token: localStorage.getItem(TOKEN_KEY) || localStorage.getItem("token") || "",
  isAdmin: (localStorage.getItem(ADMIN_KEY) || localStorage.getItem("isAdmin")) === "true",
  user: null,
  currentView: "home",
  adminTab: "dashboard",
  menu: [],
  menuFilter: "All",
  menuSearch: "",
  users: [],
  cart: readCart(),
  chatActive: false,
  chatSessionId: readChatSessionId()
};

function $(selector, root = document) { return root.querySelector(selector); }
function $$(selector, root = document) { return [...root.querySelectorAll(selector)]; }
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;"})[char]);
}
function safeId(value) { return escapeHtml(String(value ?? "").replace(/[^A-Za-z0-9_.:-]/g, "")); }
function formatCurrency(value) {
  const amount = Number(value || 0);
  return `৳ ${new Intl.NumberFormat("en-BD", {minimumFractionDigits: Number.isInteger(amount) ? 0 : 2, maximumFractionDigits: 2}).format(amount)}`;
}
function formatDate(value, withTime = true) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("en-BD", withTime ? {dateStyle: "medium", timeStyle: "short"} : {dateStyle: "medium"}).format(date);
}
function detailMessage(payload, fallback = "Something went wrong") {
  const detail = payload?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join(" · ");
  return fallback;
}
function iconRefresh() { if (window.lucide) window.lucide.createIcons(); }
function readCart() {
  try {
    const value = JSON.parse(localStorage.getItem(CART_KEY) || localStorage.getItem("cart") || "[]");
    return Array.isArray(value) ? value.filter(item => item && item.id && Number(item.quantity) > 0) : [];
  } catch { return []; }
}
function saveCart() { localStorage.setItem(CART_KEY, JSON.stringify(state.cart)); }
function readChatSessionId() {
  let value = sessionStorage.getItem(CHAT_SESSION_KEY);
  if (!value) {
    value = globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(CHAT_SESSION_KEY, value);
  }
  return value;
}
function fallbackImage(item) {
  const haystack = `${item?.name || ""} ${item?.category || ""}`.toLowerCase();
  const key = Object.keys(IMAGE_FALLBACKS).find(name => name !== "default" && haystack.includes(name));
  return IMAGE_FALLBACKS[key || "default"];
}
function menuImage(item) {
  if (!item?.image_url) return fallbackImage(item);
  if (item.image_url.startsWith("static/")) return `/${item.image_url}`;
  return item.image_url;
}
function imageHtml(item, className = "", alt = "") {
  return `<img class="${escapeHtml(className)}" src="${escapeHtml(menuImage(item))}" alt="${escapeHtml(alt || item?.name || "Menu item")}" loading="lazy" data-fallback-image data-fallback-src="${escapeHtml(fallbackImage(item))}">`;
}
function statusBadge(status) {
  const [style, label] = STATUS_META[status] || ["neutral", String(status || "unknown")];
  return `<span class="badge ${style}">${escapeHtml(label)}</span>`;
}
function loadingHtml() { return `<div class="loading-state"><span class="spinner" aria-label="Loading"></span></div>`; }
function emptyHtml(icon, title, text, action = "") {
  return `<div class="empty-state"><span><i data-lucide="${escapeHtml(icon)}"></i></span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p>${action}</div>`;
}
function errorHtml(text, retryAction = "") {
  return `<div class="error-state"><span><i data-lucide="circle-alert"></i></span><h3>Couldn’t load this</h3><p>${escapeHtml(text)}</p>${retryAction ? `<button class="btn btn-soft" type="button" data-action="${escapeHtml(retryAction)}">Try again</button>` : ""}</div>`;
}
function setButtonLoading(button, loading, label = "Working…") {
  if (!button) return;
  if (loading) {
    button.dataset.originalHtml = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner" aria-hidden="true"></span>${escapeHtml(label)}`;
  } else {
    button.disabled = false;
    if (button.dataset.originalHtml) button.innerHTML = button.dataset.originalHtml;
    delete button.dataset.originalHtml;
    iconRefresh();
  }
}

async function api(path, options = {}) {
  const {auth = true, ...fetchOptions} = options;
  const headers = new Headers(fetchOptions.headers || {});
  if (fetchOptions.body && !(fetchOptions.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (auth && state.token) headers.set("Authorization", `Bearer ${state.token}`);
  const response = await fetch(path, {...fetchOptions, headers});
  if (response.status === 401 && auth) {
    clearSession();
    updateNavigation();
    if (state.currentView !== "login") showView("login");
    showToast("error", "Session expired", "Please sign in again to continue.");
    throw new Error("Session expired");
  }
  return response;
}
async function responseData(response) {
  if (response.status === 204) return null;
  const type = response.headers.get("content-type") || "";
  return type.includes("application/json") ? response.json() : response.text();
}
async function expectOk(response, fallback) {
  const data = await responseData(response);
  if (!response.ok) throw new Error(detailMessage(data, fallback));
  return data;
}
function storeSession(data) {
  state.token = data.access_token;
  state.isAdmin = Boolean(data.is_admin);
  localStorage.setItem(TOKEN_KEY, state.token);
  localStorage.setItem(ADMIN_KEY, String(state.isAdmin));
  localStorage.removeItem("token");
  localStorage.removeItem("isAdmin");
}
function clearSession() {
  state.token = ""; state.isAdmin = false; state.user = null;
  localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(ADMIN_KEY);
  localStorage.removeItem("token"); localStorage.removeItem("isAdmin");
}

function navItem(view, label, icon = "") {
  return `<button type="button" data-view="${view}" class="${state.currentView === view ? "active" : ""}">${icon ? `<i data-lucide="${icon}"></i>` : ""}${escapeHtml(label)}</button>`;
}
function updateNavigation() {
  const desktop = $("#desktop-nav");
  const actions = $("#nav-actions");
  const mobile = $("#mobile-menu");
  if (state.token) {
    desktop.innerHTML = [navItem("menu", "Menu"), navItem("orders", "My Orders"), state.isAdmin ? navItem("admin", "Admin") : ""].join("");
    actions.innerHTML = `<button class="icon-btn notification-nav" type="button" data-view="notifications" aria-label="Notifications"><i data-lucide="bell"></i><span class="notification-badge hidden" id="notification-badge">0</span></button><button class="icon-btn" type="button" data-view="profile" aria-label="Profile"><i data-lucide="user-round"></i></button><button class="btn btn-soft" type="button" data-action="logout"><i data-lucide="log-out"></i>Logout</button>`;
    mobile.innerHTML = [navItem("menu", "Menu", "utensils"), navItem("orders", "My Orders", "receipt-text"), navItem("notifications", "Notifications", "bell"), navItem("profile", "Profile", "user-round"), state.isAdmin ? navItem("admin", "Admin", "shield-check") : "", `<div class="mobile-divider"></div><button type="button" data-action="logout"><i data-lucide="log-out"></i>Logout</button>`].join("");
  } else {
    desktop.innerHTML = navItem("home", "Home");
    actions.innerHTML = `<button class="btn btn-soft" type="button" data-view="login">Sign in</button><button class="btn btn-primary" type="button" data-view="register">Get started</button>`;
    mobile.innerHTML = [navItem("home", "Home", "house"), navItem("login", "Sign in", "log-in"), navItem("register", "Get started", "user-plus")].join("");
  }
  iconRefresh();
}

const protectedViews = new Set(["orders", "notifications", "profile", "admin"]);
function showView(requested) {
  let view = requested || "home";
  if (protectedViews.has(view) && !state.token) {
    showToast("info", "Sign in required", "Please sign in to continue.");
    view = "login";
  }
  if (view === "admin" && !state.isAdmin) view = state.token ? "menu" : "login";
  const target = $(`#${view}-view`);
  if (!target) view = "home";
  $$(".view").forEach(node => node.classList.add("hidden"));
  $(`#${view}-view`).classList.remove("hidden");
  state.currentView = view;
  history.replaceState(null, "", `#${view}`);
  $("#mobile-menu").classList.remove("open");
  $("#mobile-menu-trigger").setAttribute("aria-expanded", "false");
  $("#site-footer").classList.toggle("hidden", !["home", "login", "register"].includes(view));
  updateNavigation();
  window.scrollTo({top: 0, behavior: "smooth"});
  if (view === "menu") loadMenu();
  if (view === "orders") loadOrders();
  if (view === "notifications") loadNotifications();
  if (view === "profile") loadProfile();
  if (view === "admin") showAdminTab(state.adminTab);
  if (state.token) refreshUnreadCount();
}

function showInlineError(id, message) {
  const node = $(id);
  node.textContent = message;
  node.classList.remove("hidden");
}
function clearInlineError(id) { const node = $(id); node.textContent = ""; node.classList.add("hidden"); }
function showToast(type, title, message = "") {
  const icons = {success: "circle-check", error: "circle-alert", warning: "triangle-alert", info: "info"};
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span><i data-lucide="${icons[type] || icons.info}"></i></span><div><strong>${escapeHtml(title)}</strong>${message ? `<small>${escapeHtml(message)}</small>` : ""}</div><button type="button" aria-label="Dismiss"><i data-lucide="x"></i></button>`;
  toast.querySelector("button").addEventListener("click", () => toast.remove());
  $("#toast-region").append(toast);
  iconRefresh();
  setTimeout(() => toast.remove(), 5000);
}

async function handleLogin(event) {
  event.preventDefault(); clearInlineError("#login-error");
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  if (!email || !password || !$("#login-email").checkValidity()) return showInlineError("#login-error", "Enter a valid email address and password.");
  const button = $("#login-submit"); setButtonLoading(button, true, "Signing in…");
  try {
    const data = await expectOk(await api("/api/auth/login", {method: "POST", auth: false, body: JSON.stringify({email, password})}), "Sign in failed");
    storeSession(data);
    state.user = await expectOk(await api("/api/auth/me"), "Could not load your account");
    event.target.reset(); updateNavigation(); showToast("success", "Welcome back", `Signed in as ${state.user.full_name}.`); showView(state.isAdmin ? "admin" : "menu");
  } catch (error) { showInlineError("#login-error", error.message || "Unable to sign in."); }
  finally { setButtonLoading(button, false); }
}
async function handleRegister(event) {
  event.preventDefault(); clearInlineError("#register-error");
  const payload = {full_name: $("#register-name").value.trim(), email: $("#register-email").value.trim(), university_id: $("#register-university-id").value.trim() || null, password: $("#register-password").value};
  const confirm = $("#register-confirm").value;
  if (!event.target.checkValidity()) return showInlineError("#register-error", "Complete all required fields with valid details.");
  if (payload.password.length < 8) return showInlineError("#register-error", "Password must be at least 8 characters.");
  if (payload.password !== confirm) return showInlineError("#register-error", "Passwords do not match.");
  const button = $("#register-submit"); setButtonLoading(button, true, "Creating account…");
  try {
    const data = await expectOk(await api("/api/auth/register", {method: "POST", auth: false, body: JSON.stringify(payload)}), "Registration failed");
    storeSession(data); state.user = await expectOk(await api("/api/auth/me"), "Could not load your account");
    event.target.reset(); updateNavigation(); showToast("success", "Account created", "Welcome to UniCafe."); showView("menu");
  } catch (error) { showInlineError("#register-error", error.message || "Unable to create your account."); }
  finally { setButtonLoading(button, false); }
}
function logout() { clearSession(); updateNavigation(); showToast("info", "Signed out", "Your cart is saved on this device."); showView("home"); }

async function loadMenu(force = false) {
  const grid = $("#menu-grid");
  if (!state.menu.length || force) {
    grid.innerHTML = `<div class="skeleton-grid" style="grid-column:1/-1"><div class="skeleton"></div><div class="skeleton"></div></div>`;
    try {
      state.menu = await expectOk(await api("/api/menu?include_unavailable=true", {auth: false}), "Could not load the menu");
    } catch (error) { grid.innerHTML = errorHtml(error.message, "reload-menu"); iconRefresh(); return; }
  }
  renderMenuFilters(); renderMenu(); renderCart();
}
function renderMenuFilters() {
  const categories = ["All", ...new Set(state.menu.map(item => item.category).filter(Boolean).sort())];
  if (!categories.includes(state.menuFilter)) state.menuFilter = "All";
  $("#menu-filters").innerHTML = categories.map(category => `<button type="button" class="${category === state.menuFilter ? "active" : ""}" data-filter="${escapeHtml(category)}">${escapeHtml(category)}</button>`).join("");
}
function renderMenu() {
  const search = state.menuSearch.toLowerCase();
  const items = state.menu.filter(item => (state.menuFilter === "All" || item.category === state.menuFilter) && (!search || `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(search)));
  const grid = $("#menu-grid");
  if (!items.length) {
    grid.innerHTML = emptyHtml("search-x", "No matching items", "Try another search or category.", `<button class="btn btn-soft" type="button" data-action="clear-menu-search">Clear filters</button>`); iconRefresh(); return;
  }
  grid.innerHTML = items.map(item => {
    const available = item.is_available && Number(item.stock_quantity) > 0;
    const id = safeId(item.id);
    return `<article class="menu-card ${available ? "" : "unavailable"}"><div class="menu-card-image">${imageHtml(item, "", `${item.name} from UniCafe`)}</div><div class="menu-card-body"><div class="menu-card-top"><div><h3>${escapeHtml(item.name)}</h3></div><strong class="price">${formatCurrency(item.price)}</strong></div><p>${escapeHtml(item.description || "Freshly prepared on campus.")}</p><div class="menu-card-meta"><span class="badge">${escapeHtml(item.category)}</span><span class="stock-label">${available ? `${Number(item.stock_quantity)} available` : "Out of stock"}</span></div><button class="btn ${available ? "btn-primary" : "btn-soft"} btn-full" type="button" data-action="add-cart" data-id="${id}" ${available ? "" : "disabled"}>${available ? `<i data-lucide="plus"></i>Add to cart` : `<i data-lucide="circle-slash-2"></i>Unavailable`}</button></div></article>`;
  }).join("");
  iconRefresh();
}
function addToCart(id, quantity = 1) {
  const item = state.menu.find(row => String(row.id) === String(id));
  if (!item || !item.is_available || Number(item.stock_quantity) <= 0) return showToast("warning", "Item unavailable", "Choose another menu item.");
  const requested = Math.max(1, Number(quantity) || 1);
  const existing = state.cart.find(row => String(row.id) === String(id));
  if (existing) {
    if (existing.quantity + requested > Number(item.stock_quantity)) return showToast("warning", "Stock limit reached", `Only ${item.stock_quantity} available.`);
    existing.quantity += requested;
  } else {
    if (requested > Number(item.stock_quantity)) return showToast("warning", "Stock limit reached", `Only ${item.stock_quantity} available.`);
    state.cart.push({id: item.id, name: item.name, price: Number(item.price), quantity: requested, image_url: item.image_url || "", category: item.category || "", stock_quantity: Number(item.stock_quantity)});
  }
  saveCart(); renderCart(); showToast("success", "Added to cart", `${requested} × ${item.name} added to your cart.`);
  return true;
}
function updateCartQuantity(id, change) {
  const row = state.cart.find(item => String(item.id) === String(id));
  if (!row) return;
  const menuRow = state.menu.find(item => String(item.id) === String(id));
  const limit = Number(menuRow?.stock_quantity ?? row.stock_quantity ?? 999);
  const next = row.quantity + change;
  if (next <= 0) return removeCartItem(id);
  if (next > limit) return showToast("warning", "Stock limit reached", `Only ${limit} available.`);
  row.quantity = next; saveCart(); renderCart();
}
function removeCartItem(id) { state.cart = state.cart.filter(item => String(item.id) !== String(id)); saveCart(); renderCart(); }
function renderCart() {
  const count = state.cart.reduce((sum, item) => sum + Number(item.quantity), 0);
  const total = state.cart.reduce((sum, item) => sum + Number(item.price) * Number(item.quantity), 0);
  $("#cart-count").textContent = `${count} ${count === 1 ? "item" : "items"}`;
  $("#cart-subtotal").textContent = formatCurrency(total); $("#cart-total").textContent = formatCurrency(total);
  $("#clear-cart").classList.toggle("hidden", !state.cart.length);
  $("#place-order-button").disabled = !state.cart.length;
  $("#cart-items").innerHTML = state.cart.length ? state.cart.map(item => `<div class="cart-item">${imageHtml(item, "", item.name)}<div><h4>${escapeHtml(item.name)}</h4><small>${formatCurrency(item.price)} each</small><div class="quantity-control"><button type="button" data-action="cart-minus" data-id="${safeId(item.id)}" aria-label="Decrease ${escapeHtml(item.name)}"><i data-lucide="minus"></i></button><span>${Number(item.quantity)}</span><button type="button" data-action="cart-plus" data-id="${safeId(item.id)}" aria-label="Increase ${escapeHtml(item.name)}"><i data-lucide="plus"></i></button></div></div><div class="cart-item-aside"><strong>${formatCurrency(Number(item.price) * Number(item.quantity))}</strong><button type="button" data-action="remove-cart" data-id="${safeId(item.id)}" aria-label="Remove ${escapeHtml(item.name)}"><i data-lucide="trash-2"></i></button></div></div>`).join("") : `<div class="cart-empty"><i data-lucide="shopping-basket"></i><strong>Your cart is empty</strong><br><small>Add something delicious to begin.</small></div>`;
  iconRefresh();
}

async function placeOrder() {
  if (!state.cart.length) return;
  if (!state.token) { showToast("info", "Ready to order?", "Sign in and your cart will be waiting."); return showView("login"); }
  const button = $("#place-order-button"); setButtonLoading(button, true, "Placing order…");
  const pickup = $("#pickup-time").value || null;
  try {
    const order = await expectOk(await api("/api/orders", {method: "POST", body: JSON.stringify({items: state.cart.map(item => ({menu_item_id: item.id, quantity: Number(item.quantity)})), pickup_time: pickup})}), "Order could not be placed");
    state.cart = []; saveCart(); renderCart(); $("#pickup-time").value = "";
    showToast("success", "Order placed", `Order #${String(order.id).slice(0, 8)} is now pending.`);
    showOrderSuccess(order); await loadMenu(true);
  } catch (error) { showToast("error", "Order failed", error.message || "Your cart has been preserved."); }
  finally { setButtonLoading(button, false); }
}
function showOrderSuccess(order) {
  openModal(`<div class="modal-head"><div><span class="kicker">Order received</span><h2>You’re all set!</h2><p>We’ll notify you as your order moves forward.</p></div><button class="icon-btn" type="button" data-close-modal aria-label="Close"><i data-lucide="x"></i></button></div><div class="card" style="padding:18px;margin-bottom:20px"><div class="top-list-row"><span>Order ID</span><strong>#${escapeHtml(String(order.id).slice(0, 8))}</strong></div><div class="top-list-row"><span>Total</span><strong>${formatCurrency(order.total_amount)}</strong></div><div class="top-list-row"><span>Status</span>${statusBadge(order.status)}</div>${order.pickup_time ? `<div class="top-list-row"><span>Pickup</span><strong>${escapeHtml(formatDate(order.pickup_time))}</strong></div>` : ""}</div><div class="modal-actions"><button class="btn btn-soft" type="button" data-close-modal>Keep browsing</button><button class="btn btn-primary" type="button" data-view="orders" data-close-modal>View my orders</button></div>`);
}

async function loadOrders() {
  const container = $("#orders-content"); container.innerHTML = loadingHtml();
  try {
    const orders = await expectOk(await api("/api/orders/history"), "Could not load your orders");
    if (!orders.length) container.innerHTML = emptyHtml("receipt-text", "No orders yet", "Your first campus pickup will appear here.", `<button class="btn btn-primary" type="button" data-view="menu">Browse menu</button>`);
    else container.innerHTML = `<div class="order-list">${orders.map(orderCardHtml).join("")}</div>`;
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-orders"); }
  iconRefresh();
}
function orderCardHtml(order) {
  const id = safeId(order.id); const status = String(order.status || "pending"); const current = ORDER_STEPS.indexOf(status);
  const progress = status === "cancelled" ? "" : `<div class="order-progress">${ORDER_STEPS.map((step, index) => `<div class="progress-step ${index < current ? "done" : index === current ? "current" : ""}"><span class="progress-dot"></span>${escapeHtml(step)}</div>`).join("")}</div>`;
  return `<article class="order-card card"><div class="order-card-header"><div><h3>Order #${escapeHtml(String(order.id).slice(0, 8))}</h3><p>${escapeHtml(formatDate(order.created_at))}${order.pickup_time ? ` · Pickup ${escapeHtml(formatDate(order.pickup_time))}` : ""}</p></div>${statusBadge(status)}</div>${progress}<div class="order-items">${(order.items || []).map(item => `<div class="order-item-row"><span>${escapeHtml(item.name)}<small>× ${Number(item.quantity)}</small></span><strong>${formatCurrency(item.subtotal ?? Number(item.price) * Number(item.quantity))}</strong></div>`).join("")}</div><div class="order-card-footer"><div><small>Total</small><strong>${formatCurrency(order.total_amount)}</strong></div><div class="order-actions">${["pending", "confirmed"].includes(status) ? `<button class="btn btn-danger-soft btn-sm" type="button" data-action="cancel-order" data-id="${id}">Cancel order</button>` : ""}${status === "completed" && !order.feedback_id ? `<button class="btn btn-primary btn-sm" type="button" data-action="feedback" data-id="${id}"><i data-lucide="star"></i>Leave feedback</button>` : ""}${order.feedback_id ? `<span class="badge success"><i data-lucide="check"></i>Feedback sent</span>` : ""}</div></div></article>`;
}
async function cancelOrder(id) {
  confirmDialog("Cancel this order?", "Available stock will be restored. This action can’t be undone.", async button => {
    setButtonLoading(button, true, "Cancelling…");
    try { await expectOk(await api(`/api/orders/${encodeURIComponent(id)}/cancel`, {method: "PUT"}), "Could not cancel order"); closeModal(); showToast("success", "Order cancelled", "Stock has been restored."); loadOrders(); }
    catch (error) { showToast("error", "Cancellation failed", error.message); setButtonLoading(button, false); }
  }, "Cancel order", true);
}
function openFeedback(id) {
  openModal(`<div class="modal-head"><div><span class="kicker">Your experience</span><h2>Leave feedback</h2><p>Feedback is available once per completed order.</p></div><button class="icon-btn" type="button" data-close-modal aria-label="Close"><i data-lucide="x"></i></button></div><form id="feedback-form" data-order-id="${safeId(id)}"><fieldset style="border:0;padding:0;margin:0 0 18px"><legend style="font-weight:700;margin-bottom:9px">Rating</legend><div class="stars" id="star-picker" style="font-size:28px"><button type="button" data-rating="1" aria-label="1 star">☆</button><button type="button" data-rating="2" aria-label="2 stars">☆</button><button type="button" data-rating="3" aria-label="3 stars">☆</button><button type="button" data-rating="4" aria-label="4 stars">☆</button><button type="button" data-rating="5" aria-label="5 stars">☆</button></div><input type="hidden" id="feedback-rating" value="5"></fieldset><label class="field"><span>Comment <em>optional</em></span><span class="input-wrap"><i data-lucide="message-square"></i><textarea id="feedback-comment" maxlength="1000" placeholder="What did you enjoy?"></textarea></span></label><div class="modal-actions"><button class="btn btn-soft" type="button" data-close-modal>Cancel</button><button class="btn btn-primary" id="feedback-submit" type="submit">Submit feedback</button></div></form>`);
  updateStars(5);
}
function updateStars(value) { $("#feedback-rating").value = value; $$("#star-picker button").forEach((button, index) => button.textContent = index < value ? "★" : "☆"); }
async function submitFeedback(event) {
  event.preventDefault(); const button = $("#feedback-submit"); setButtonLoading(button, true, "Submitting…");
  try { await expectOk(await api("/api/feedback", {method: "POST", body: JSON.stringify({order_id: event.target.dataset.orderId, rating: Number($("#feedback-rating").value), comment: $("#feedback-comment").value.trim() || null})}), "Could not submit feedback"); closeModal(); showToast("success", "Thank you", "Your feedback has been submitted."); loadOrders(); }
  catch (error) { showToast("error", "Feedback failed", error.message); setButtonLoading(button, false); }
}

async function refreshUnreadCount() {
  if (!state.token) return;
  try {
    const data = await expectOk(await api("/api/notifications/unread-count"), "Could not load notifications");
    const badge = $("#notification-badge"); if (!badge) return;
    const count = Number(data.unread || 0); badge.textContent = count > 99 ? "99+" : String(count); badge.classList.toggle("hidden", count === 0);
  } catch { /* Session handling already provides feedback. */ }
}
async function loadNotifications() {
  const container = $("#notifications-content"); container.innerHTML = loadingHtml();
  try {
    const notes = await expectOk(await api("/api/notifications"), "Could not load notifications");
    container.innerHTML = notes.length ? notes.map(note => `<article class="notification-card card ${note.is_read ? "" : "unread"}"><span class="notification-icon"><i data-lucide="${String(note.type).includes("ready") ? "package-check" : String(note.type).includes("cancel") ? "circle-x" : "bell-ring"}"></i></span><div><h3>${escapeHtml(note.title)}</h3><p>${escapeHtml(note.message)}</p><time datetime="${escapeHtml(note.created_at)}">${escapeHtml(formatDate(note.created_at))}</time>${note.order_id ? `<div><button class="text-btn" type="button" data-view="orders">View related order</button></div>` : ""}</div>${note.is_read ? "" : `<button class="btn btn-soft btn-sm" type="button" data-action="mark-read" data-id="${safeId(note.id)}">Mark read</button>`}</article>`).join("") : emptyHtml("bell-off", "You’re all caught up", "Order updates will appear here.");
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-notifications"); }
  iconRefresh(); refreshUnreadCount();
}
async function markRead(id) {
  try { await expectOk(await api(`/api/notifications/${encodeURIComponent(id)}/read`, {method: "PUT"}), "Could not update notification"); loadNotifications(); }
  catch (error) { showToast("error", "Update failed", error.message); }
}
async function markAllRead() {
  const button = $("#mark-all-read"); setButtonLoading(button, true, "Updating…");
  try { await expectOk(await api("/api/notifications/read-all", {method: "PUT"}), "Could not update notifications"); showToast("success", "All caught up", "Every notification is marked read."); loadNotifications(); }
  catch (error) { showToast("error", "Update failed", error.message); }
  finally { setButtonLoading(button, false); }
}

async function loadProfile() {
  $("#profile-summary").innerHTML = loadingHtml();
  try {
    state.user = await expectOk(await api("/api/profile"), "Could not load profile");
    $("#profile-name").value = state.user.full_name || ""; $("#profile-email").value = state.user.email || ""; $("#profile-university-id").value = state.user.university_id || "";
    const initials = String(state.user.full_name || "U").split(/\s+/).slice(0, 2).map(part => part[0]).join("").toUpperCase();
    $("#profile-summary").innerHTML = `<div class="profile-avatar">${escapeHtml(initials)}</div><h2>${escapeHtml(state.user.full_name)}</h2><p>${escapeHtml(state.user.email)}</p><span class="badge ${state.user.is_admin ? "violet" : "success"}">${state.user.is_admin ? "Administrator" : "Student account"}</span><div class="profile-details"><div><span>University ID</span><strong>${escapeHtml(state.user.university_id || "Not added")}</strong></div><div><span>Account</span><strong>${state.user.is_active ? "Active" : "Disabled"}</strong></div><div><span>Joined</span><strong>${escapeHtml(formatDate(state.user.created_at, false))}</strong></div></div>`;
  } catch (error) { $("#profile-summary").innerHTML = errorHtml(error.message, "reload-profile"); }
  iconRefresh();
}
async function updateProfile(event) {
  event.preventDefault(); clearInlineError("#profile-error");
  if (!event.target.checkValidity()) return showInlineError("#profile-error", "Enter valid profile details.");
  const button = $("#profile-submit"); setButtonLoading(button, true, "Saving…");
  try {
    state.user = await expectOk(await api("/api/profile", {method: "PUT", body: JSON.stringify({full_name: $("#profile-name").value.trim(), email: $("#profile-email").value.trim(), university_id: $("#profile-university-id").value.trim() || null})}), "Could not update profile");
    showToast("success", "Profile updated", "Your account details are saved."); loadProfile();
  } catch (error) { showInlineError("#profile-error", error.message); }
  finally { setButtonLoading(button, false); }
}

function showAdminTab(tab) {
  if (!state.isAdmin) return showView("menu");
  state.adminTab = tab;
  $$(".admin-panel").forEach(panel => panel.classList.add("hidden"));
  $(`#admin-${tab}-panel`)?.classList.remove("hidden");
  $$('[data-admin-tab]').forEach(button => button.classList.toggle("active", button.dataset.adminTab === tab));
  const loaders = {dashboard: loadDashboard, menu: loadAdminMenu, inventory: loadInventory, orders: loadAdminOrders, users: loadUsers, feedback: loadAdminFeedback, reports: loadReports, ai: loadInsights};
  loaders[tab]?.(); iconRefresh();
}
async function loadDashboard() {
  const container = $("#admin-dashboard-content"); container.innerHTML = loadingHtml();
  try {
    const data = await expectOk(await api("/api/admin/dashboard"), "Could not load dashboard");
    const byStatus = data.orders_by_status || {}; const max = Math.max(1, ...Object.values(byStatus).map(Number));
    const kpis = [["users", "Total users", data.total_users || 0], ["receipt-text", "Total orders", data.total_orders || 0], ["clock-3", "Pending orders", byStatus.pending || 0], ["circle-check-big", "Completed", byStatus.completed || 0], ["banknote", "Total revenue", formatCurrency(data.total_revenue)], ["star", "Average rating", `${Number(data.average_rating || 0).toFixed(1)} / 5`]];
    container.innerHTML = `<div class="page-heading"><span class="kicker">Live overview</span><h1>Dashboard</h1><p>Current performance from real UniCafe data.</p></div><div class="kpi-grid">${kpis.map(([icon, label, value]) => `<article class="kpi-card card"><span><i data-lucide="${icon}"></i></span><div><small>${label}</small><strong>${escapeHtml(value)}</strong></div></article>`).join("")}</div><div class="dashboard-grid"><section class="dashboard-block card"><h2>Orders by status</h2><div class="status-bars">${ORDER_STEPS.concat(["cancelled"]).map(status => `<div><div class="status-bar-head"><span>${escapeHtml(status)}</span><strong>${Number(byStatus[status] || 0)}</strong></div><div class="status-bar-track"><div class="status-bar-fill" style="width:${Math.min(100, Number(byStatus[status] || 0) / max * 100)}%"></div></div></div>`).join("")}</div></section><section class="dashboard-block card"><h2>Top items</h2><div class="top-list">${(data.top_items || []).length ? data.top_items.map((item, index) => `<div class="top-list-row"><span><b>${index + 1}.</b> ${escapeHtml(item.name)}</span><strong>${Number(item.quantity)} sold</strong></div>`).join("") : `<p style="color:var(--muted)">No item sales yet.</p>`}</div></section></div>`;
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-dashboard"); }
  iconRefresh();
}

async function loadAdminMenu() {
  const container = $("#admin-menu-content"); container.innerHTML = loadingHtml();
  try {
    state.menu = await expectOk(await api("/api/menu?include_unavailable=true", {auth: false}), "Could not load menu");
    container.innerHTML = state.menu.length ? state.menu.map(item => `<article class="admin-menu-card card">${imageHtml(item, "", item.name)}<div class="admin-menu-card-body"><div class="menu-card-top"><div><h3>${escapeHtml(item.name)}</h3><span class="badge">${escapeHtml(item.category)}</span></div><strong class="price">${formatCurrency(item.price)}</strong></div><p>${escapeHtml(item.description)}</p><div class="menu-card-meta"><span class="stock-label">${Number(item.stock_quantity)} in stock</span>${item.is_available ? `<span class="badge success">Available</span>` : `<span class="badge danger">Unavailable</span>`}</div><div class="admin-card-actions"><button class="btn btn-soft btn-sm" type="button" data-action="edit-menu" data-id="${safeId(item.id)}"><i data-lucide="pencil"></i>Edit</button><button class="btn btn-danger-soft btn-sm" type="button" data-action="delete-menu" data-id="${safeId(item.id)}"><i data-lucide="trash-2"></i>Delete</button></div></div></article>`).join("") : emptyHtml("utensils", "No menu items", "Create the first item for your cafe.", `<button class="btn btn-primary" type="button" data-action="add-menu"><i data-lucide="plus"></i>Add item</button>`);
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-admin-menu"); }
  iconRefresh();
}
function openMenuForm(id = "") {
  const item = state.menu.find(row => String(row.id) === String(id));
    openModal(`<div class="modal-head"><div><span class="kicker">${item ? "Update catalogue" : "New menu item"}</span><h2>${item ? "Edit item" : "Add menu item"}</h2><p>Use a local /static image path or a direct URL. Leave blank for a category fallback.</p></div><button class="icon-btn" type="button" data-close-modal aria-label="Close"><i data-lucide="x"></i></button></div><form id="menu-item-form" data-item-id="${item ? safeId(item.id) : ""}"><div class="field-row"><label class="field"><span>Name</span><span class="input-wrap"><i data-lucide="utensils"></i><input id="menu-form-name" required maxlength="120" value="${escapeHtml(item?.name || "")}"></span></label><label class="field"><span>Category</span><span class="input-wrap"><i data-lucide="tag"></i><input id="menu-form-category" required maxlength="80" value="${escapeHtml(item?.category || "")}" placeholder="Meals, Coffee…"></span></label></div><label class="field"><span>Description</span><span class="input-wrap"><i data-lucide="align-left"></i><textarea id="menu-form-description" required maxlength="600" placeholder="Short, useful description">${escapeHtml(item?.description || "")}</textarea></span></label><div class="field-row"><label class="field"><span>Price (BDT)</span><span class="input-wrap"><i data-lucide="banknote"></i><input id="menu-form-price" type="number" min="0.01" max="10000" step="0.01" required value="${item ? Number(item.price) : ""}"></span></label><label class="field"><span>Stock</span><span class="input-wrap"><i data-lucide="package"></i><input id="menu-form-stock" type="number" min="0" max="100000" step="1" required value="${item ? Number(item.stock_quantity) : 0}"></span></label></div><label class="field"><span>Image URL <em>optional</em></span><span class="input-wrap"><i data-lucide="image"></i><input id="menu-form-image" type="text" maxlength="2000" value="${escapeHtml(item?.image_url || "")}" placeholder="/static/images/menu/item.jpg"></span></label><label style="display:flex;align-items:center;gap:9px;margin-top:4px"><input id="menu-form-available" type="checkbox" ${item ? (item.is_available ? "checked" : "") : "checked"}> Available for ordering</label><div class="modal-actions"><button class="btn btn-soft" type="button" data-close-modal>Cancel</button><button class="btn btn-primary" id="menu-form-submit" type="submit">${item ? "Save changes" : "Create item"}</button></div></form>`, "wide");
}
async function submitMenuForm(event) {
  event.preventDefault(); if (!event.target.checkValidity()) return showToast("warning", "Check the form", "Complete all required values.");
  const id = event.target.dataset.itemId;
  const payload = {name: $("#menu-form-name").value.trim(), category: $("#menu-form-category").value.trim(), description: $("#menu-form-description").value.trim(), price: Number($("#menu-form-price").value), stock_quantity: Number($("#menu-form-stock").value), image_url: $("#menu-form-image").value.trim() || null, is_available: $("#menu-form-available").checked};
  const button = $("#menu-form-submit"); setButtonLoading(button, true, "Saving…");
  try { await expectOk(await api(id ? `/api/admin/menu/${encodeURIComponent(id)}` : "/api/admin/menu", {method: id ? "PUT" : "POST", body: JSON.stringify(payload)}), "Could not save menu item"); closeModal(); showToast("success", id ? "Item updated" : "Item created", payload.name); loadAdminMenu(); }
  catch (error) { showToast("error", "Save failed", error.message); setButtonLoading(button, false); }
}
function deleteMenu(id) {
  const item = state.menu.find(row => String(row.id) === String(id));
  confirmDialog("Delete this menu item?", `${item?.name || "This item"} will be permanently removed.`, async button => {
    setButtonLoading(button, true, "Deleting…");
    try { await expectOk(await api(`/api/admin/menu/${encodeURIComponent(id)}`, {method: "DELETE"}), "Could not delete item"); closeModal(); showToast("success", "Item deleted", item?.name || "Menu item removed."); loadAdminMenu(); }
    catch (error) { showToast("error", "Delete failed", error.message); setButtonLoading(button, false); }
  }, "Delete item", true);
}

async function loadInventory() {
  const container = $("#admin-inventory-content"); container.innerHTML = loadingHtml();
  try {
    const items = await expectOk(await api("/api/admin/inventory"), "Could not load inventory");
    container.innerHTML = items.length ? `<div class="table-card card"><table class="data-table"><thead><tr><th>Item</th><th>Category</th><th>Status</th><th>Stock level</th><th>Update</th></tr></thead><tbody>${items.map(item => { const stock = Number(item.stock_quantity); return `<tr><td><div class="table-item">${imageHtml(item, "", item.name)}<strong>${escapeHtml(item.name)}</strong></div></td><td>${escapeHtml(item.category || "—")}</td><td>${stock === 0 ? `<span class="badge danger">Out of stock</span>` : stock <= 5 ? `<span class="badge warning">Low stock</span>` : `<span class="badge success">In stock</span>`}</td><td><strong>${stock}</strong></td><td><div class="inline-stock"><input id="stock-${safeId(item.id)}" type="number" min="0" max="100000" value="${stock}" aria-label="Stock for ${escapeHtml(item.name)}"><button class="btn btn-soft btn-sm" type="button" data-action="update-stock" data-id="${safeId(item.id)}">Update</button></div></td></tr>`; }).join("")}</tbody></table></div>` : emptyHtml("package-open", "No inventory", "Menu items will appear here once created.");
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-inventory"); }
  iconRefresh();
}
async function updateStock(id, button) {
  const input = $(`#stock-${CSS.escape(id)}`); const stock = Number(input?.value);
  if (!Number.isInteger(stock) || stock < 0) return showToast("warning", "Invalid stock", "Use a whole number of zero or more.");
  setButtonLoading(button, true, "Updating…");
  try { await expectOk(await api(`/api/admin/inventory/${encodeURIComponent(id)}`, {method: "PUT", body: JSON.stringify({stock_quantity: stock})}), "Could not update stock"); showToast("success", "Stock updated", `New quantity: ${stock}`); loadInventory(); }
  catch (error) { showToast("error", "Update failed", error.message); setButtonLoading(button, false); }
}

async function loadAdminOrders() {
  const container = $("#admin-orders-content"); container.innerHTML = loadingHtml();
  try {
    const orders = await expectOk(await api("/api/admin/orders"), "Could not load orders");
    container.innerHTML = orders.length ? `<div class="table-card card"><table class="data-table"><thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Total</th><th>Status</th><th>Next action</th></tr></thead><tbody>${orders.map(order => `<tr><td><strong>#${escapeHtml(String(order.id).slice(0, 8))}</strong><br><small>${escapeHtml(formatDate(order.created_at))}</small></td><td><strong>${escapeHtml(order.user_name || "Student")}</strong><br><small>${escapeHtml(order.user_email || "")}</small></td><td>${(order.items || []).map(item => `${escapeHtml(item.name)} × ${Number(item.quantity)}`).join("<br>")}</td><td><strong>${formatCurrency(order.total_amount)}</strong></td><td>${statusBadge(order.status)}</td><td>${adminOrderActionHtml(order)}</td></tr>`).join("")}</tbody></table></div>` : emptyHtml("receipt-text", "No orders", "New orders will appear here.");
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-admin-orders"); }
  iconRefresh();
}
function adminOrderActionHtml(order) {
  const next = {pending: ["confirmed", "Confirm"], confirmed: ["preparing", "Start preparing"], preparing: ["ready", "Mark ready"], ready: ["completed", "Complete"]}[order.status];
  return `<div style="display:flex;gap:6px">${next ? `<button class="btn btn-primary btn-sm" type="button" data-action="order-status" data-id="${safeId(order.id)}" data-status="${next[0]}">${next[1]}</button>` : ""}${["pending", "confirmed"].includes(order.status) ? `<button class="btn btn-danger-soft btn-sm" type="button" data-action="order-status" data-id="${safeId(order.id)}" data-status="cancelled">Cancel</button>` : ""}${!next && !["pending", "confirmed"].includes(order.status) ? `<span style="color:var(--muted)">No action</span>` : ""}</div>`;
}
async function updateOrderStatus(id, status, button) {
  setButtonLoading(button, true, "Updating…");
  try { await expectOk(await api(`/api/admin/orders/${encodeURIComponent(id)}/status`, {method: "PUT", body: JSON.stringify({status})}), "Could not update order"); showToast("success", "Order updated", `Status is now ${status}.`); loadAdminOrders(); }
  catch (error) { showToast("error", "Status update failed", error.message); setButtonLoading(button, false); }
}

async function loadUsers() {
  const container = $("#admin-users-content"); container.innerHTML = loadingHtml();
  try { state.users = await expectOk(await api("/api/admin/users"), "Could not load users"); renderUsers(); }
  catch (error) { container.innerHTML = errorHtml(error.message, "reload-users"); iconRefresh(); }
}
function renderUsers() {
  const search = ($("#user-search")?.value || "").toLowerCase();
  const users = state.users.filter(user => !search || `${user.full_name} ${user.email} ${user.university_id || ""}`.toLowerCase().includes(search));
  $("#admin-users-content").innerHTML = users.length ? `<div class="table-card card"><table class="data-table"><thead><tr><th>User</th><th>University ID</th><th>Role</th><th>Orders</th><th>Total spent</th><th>Status</th><th>Action</th></tr></thead><tbody>${users.map(user => `<tr><td><strong>${escapeHtml(user.full_name)}</strong><br><small>${escapeHtml(user.email)}</small></td><td>${escapeHtml(user.university_id || "—")}</td><td><span class="badge ${user.is_admin ? "violet" : "neutral"}">${user.is_admin ? "Admin" : "Student"}</span></td><td>${Number(user.order_count || 0)}</td><td>${formatCurrency(user.total_spent)}</td><td>${user.is_active ? `<span class="badge success">Active</span>` : `<span class="badge danger">Disabled</span>`}</td><td>${state.user?.id === user.id ? `<span style="color:var(--muted)">You</span>` : `<button class="btn ${user.is_active ? "btn-danger-soft" : "btn-soft"} btn-sm" type="button" data-action="user-status" data-id="${safeId(user.id)}" data-active="${user.is_active ? "false" : "true"}">${user.is_active ? "Disable" : "Enable"}</button>`}</td></tr>`).join("")}</tbody></table></div>` : emptyHtml("user-search", "No users found", "Try another search term.");
  iconRefresh();
}
function changeUserStatus(id, isActive) {
  const user = state.users.find(row => String(row.id) === String(id));
  confirmDialog(`${isActive ? "Enable" : "Disable"} this account?`, `${user?.full_name || "This user"} will ${isActive ? "regain" : "lose"} access to protected UniCafe features.`, async button => {
    setButtonLoading(button, true, "Updating…");
    try { await expectOk(await api(`/api/admin/users/${encodeURIComponent(id)}/status`, {method: "PUT", body: JSON.stringify({is_active: isActive})}), "Could not update user"); closeModal(); showToast("success", "User updated", `Account ${isActive ? "enabled" : "disabled"}.`); loadUsers(); }
    catch (error) { showToast("error", "Update failed", error.message); setButtonLoading(button, false); }
  }, isActive ? "Enable account" : "Disable account", !isActive);
}

async function loadAdminFeedback() {
  const container = $("#admin-feedback-content"); container.innerHTML = loadingHtml();
  try {
    const feedback = await expectOk(await api("/api/feedback"), "Could not load feedback");
    container.innerHTML = feedback.length ? `<div class="feedback-grid">${feedback.map(item => `<article class="feedback-card card"><div class="feedback-card-head"><div><h3>${escapeHtml(item.user_name || "Student")}</h3><time>${escapeHtml(formatDate(item.created_at))} · Order #${escapeHtml(String(item.order_id).slice(0, 8))}</time></div><span class="stars" aria-label="${Number(item.rating)} out of 5 stars">${"★".repeat(Number(item.rating))}${"☆".repeat(5 - Number(item.rating))}</span></div><p>${item.comment ? escapeHtml(item.comment) : "No written comment."}</p></article>`).join("")}</div>` : emptyHtml("messages-square", "No feedback yet", "Completed-order ratings will appear here.");
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-feedback"); }
  iconRefresh();
}

function reportControlsHtml() {
  const today = new Date().toISOString().slice(0, 10); const month = today.slice(0, 7);
  return `<div class="report-controls card"><label class="field"><span>Daily report</span><span class="input-wrap"><i data-lucide="calendar-days"></i><input id="report-day" type="date" value="${today}"></span></label><label class="field"><span>Monthly report</span><span class="input-wrap"><i data-lucide="calendar-range"></i><input id="report-month" type="month" value="${month}"></span></label><button class="btn btn-primary" id="load-reports-button" type="button">Load reports</button></div><div id="report-results"></div>`;
}
async function loadReports() {
  const container = $("#admin-reports-content");
  if (!$("#report-day")) { container.innerHTML = reportControlsHtml(); iconRefresh(); }
  const results = $("#report-results"); results.innerHTML = loadingHtml();
  const day = $("#report-day").value; const month = $("#report-month").value;
  try {
    const [daily, monthly, popular] = await Promise.all([
      api(`/api/admin/reports/daily?day=${encodeURIComponent(day)}`).then(res => expectOk(res, "Daily report failed")),
      api(`/api/admin/reports/monthly?year_month=${encodeURIComponent(month)}`).then(res => expectOk(res, "Monthly report failed")),
      api("/api/admin/reports/popular-items?limit=10").then(res => expectOk(res, "Popular items failed"))
    ]);
    results.innerHTML = `<div class="report-grid"><article class="report-card card"><small>Daily orders</small><strong>${Number(daily.total_orders)}</strong></article><article class="report-card card"><small>Daily revenue</small><strong>${formatCurrency(daily.total_revenue)}</strong></article><article class="report-card card"><small>Monthly orders</small><strong>${Number(monthly.total_orders)}</strong></article><article class="report-card card"><small>Monthly sales</small><strong>${formatCurrency(monthly.total_sales)}</strong></article></div><section class="popular-report card"><div class="split-heading" style="align-items:center"><h2 style="font-size:19px;margin:0">Popular items</h2><div style="display:flex;gap:7px"><button class="btn btn-soft btn-sm" type="button" data-action="export-report" data-report="daily"><i data-lucide="download"></i>Daily CSV</button><button class="btn btn-soft btn-sm" type="button" data-action="export-report" data-report="monthly"><i data-lucide="download"></i>Monthly CSV</button><button class="btn btn-soft btn-sm" type="button" data-action="export-report" data-report="popular"><i data-lucide="download"></i>Popular CSV</button></div></div><div class="top-list" style="margin-top:15px">${popular.length ? popular.map(item => `<div class="top-list-row"><span><b>#${Number(item.rank)}</b> ${escapeHtml(item.name)} <small>${escapeHtml(item.category || "")}</small></span><strong>${Number(item.total_quantity)} sold · ${formatCurrency(item.revenue)}</strong></div>`).join("") : `<p style="color:var(--muted)">No sales data yet.</p>`}</div><div class="top-list-row" style="margin-top:12px"><span>Best day this month</span><strong>${escapeHtml(monthly.best_day || "—")} · ${formatCurrency(monthly.best_day_revenue)}</strong></div></section>`;
  } catch (error) { results.innerHTML = errorHtml(error.message, "reload-reports"); }
  iconRefresh();
}
async function exportReport(kind) {
  let url = `/api/admin/reports/export?report=${encodeURIComponent(kind)}`;
  if (kind === "daily") url += `&day=${encodeURIComponent($("#report-day").value)}`;
  if (kind === "monthly") url += `&year_month=${encodeURIComponent($("#report-month").value)}`;
  try {
    const response = await api(url); if (!response.ok) throw new Error("Export failed");
    const blob = await response.blob(); const link = document.createElement("a"); const objectUrl = URL.createObjectURL(blob);
    link.href = objectUrl; link.download = `${kind}-unicafe-report.csv`; document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(objectUrl);
    showToast("success", "Report exported", `${kind} CSV downloaded.`);
  } catch (error) { showToast("error", "Export failed", error.message); }
}

async function loadInsights() {
  const container = $("#admin-ai-content"); container.innerHTML = loadingHtml();
  try {
    const data = await expectOk(await api("/api/admin/ai/insights"), "Could not generate insights");
    container.innerHTML = `<article class="insight-card card"><div class="card-heading"><span class="heading-icon accent"><i data-lucide="brain-circuit"></i></span><div><h2>Current operational summary</h2><p>${data.fallback ? "Reliable local summary while Gemini is unavailable" : "Generated from current UniCafe data"}</p></div></div><pre>${escapeHtml(data.response)}</pre></article>`;
  } catch (error) { container.innerHTML = errorHtml(error.message, "reload-insights"); }
  iconRefresh();
}

async function recommend() {
  if (!state.token) { showToast("info", "Sign in for smart picks", "Recommendations use your account securely."); return showView("login"); }
  const button = $("#recommend-button"); setButtonLoading(button, true, "Finding picks…");
  try {
    const data = await expectOk(await api("/api/ai/recommendations"), "Could not load recommendations");
    const items = data.recommendations || [];
    openModal(`<div class="modal-head"><div><span class="kicker">Smart picks</span><h2>Recommended for you</h2><p>${data.fallback ? "Good available options from today’s menu." : "Personalized from today’s menu."}</p></div><button class="icon-btn" type="button" data-close-modal aria-label="Close"><i data-lucide="x"></i></button></div><div class="recommend-grid">${items.length ? items.map(rec => { const full = state.menu.find(item => String(item.id) === String(rec.menu_item_id)) || rec; return `<article class="recommend-card">${imageHtml(full, "", rec.name)}<div><h3>${escapeHtml(rec.name)}</h3><p>${escapeHtml(rec.reason || "Available on today’s menu.")}</p><strong>${formatCurrency(rec.price)} · ${escapeHtml(rec.category || "")}</strong></div></article>`; }).join("") : `<p>No recommendations are available right now.</p>`}</div><div class="modal-actions"><button class="btn btn-primary" type="button" data-close-modal>Back to menu</button></div>`);
  } catch (error) { showToast("error", "Recommendations unavailable", error.message); }
  finally { setButtonLoading(button, false); }
}
async function sendChat(event) {
  event.preventDefault(); const input = $("#chat-input"); const message = input.value.trim(); if (!message) return;
  if (!state.token) { showToast("info", "Sign in to chat", "The assistant is available to signed-in students."); return showView("login"); }
  if (state.chatActive) return;
  state.chatActive = true;
  const sendButton = $("#chat-form button[type='submit']");
  sendButton.disabled = true;
  appendChat(message, "user"); input.value = "";
  const pending = appendChat("UniCafe AI is thinking…", "assistant typing");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  let receivedText = false; let chatAction = null;
  try {
    const response = await api("/api/ai/chat/stream", {method: "POST", body: JSON.stringify({message, session_id: state.chatSessionId}), signal: controller.signal});
    if (!response.ok) throw new Error(detailMessage(await responseData(response), "Assistant unavailable"));
    if (!response.body) throw new Error("Streaming is not supported by this browser");
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const {value, done} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        let eventName = "message"; const dataLines = [];
        block.split("\n").forEach(line => {
          if (line.startsWith("event:")) eventName = line.slice(6).trim();
          if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        });
        if (!dataLines.length) continue;
        const data = JSON.parse(dataLines.join("\n"));
        if (eventName === "chunk" && data.text) {
          if (!receivedText) { pending.textContent = ""; pending.classList.remove("typing"); receivedText = true; }
          pending.textContent += cleanChatText(data.text); scrollChat();
        }
        if (eventName === "done" && data.action?.type === "add_to_cart") chatAction = data.action;
      }
    }
    if (!receivedText) throw new Error("The assistant returned an empty response");
    pending.textContent = cleanChatText(pending.textContent);
    if (chatAction) renderChatAction(pending, chatAction);
  } catch (error) {
    pending.classList.remove("typing");
    pending.textContent = error.name === "AbortError" ? "The assistant took too long. Please try again." : `Sorry, I couldn’t answer: ${error.message}`;
  } finally {
    clearTimeout(timeout); state.chatActive = false; sendButton.disabled = false; input.focus(); scrollChat();
  }
}
function cleanChatText(value) { return String(value || "").replaceAll("*", "").replaceAll("#", ""); }
function renderChatAction(bubble, action) {
  const controls = document.createElement("div"); controls.className = "chat-actions";
  const addButton = document.createElement("button"); addButton.type = "button"; addButton.className = "btn btn-primary btn-sm"; addButton.textContent = "Add to Cart";
  const viewButton = document.createElement("button"); viewButton.type = "button"; viewButton.className = "btn btn-soft btn-sm"; viewButton.textContent = "View Cart";
  addButton.addEventListener("click", async () => {
    addButton.disabled = true;
    if (!state.menu.some(item => String(item.id) === String(action.menu_item_id))) await loadMenu(true);
    if (addToCart(action.menu_item_id, action.quantity)) addButton.textContent = "Added";
    else addButton.disabled = false;
  });
  viewButton.addEventListener("click", () => showView("cart"));
  controls.append(addButton, viewButton); bubble.append(controls); iconRefresh(); scrollChat();
}
function scrollChat() { $("#chat-messages").scrollTop = $("#chat-messages").scrollHeight; }
function appendChat(message, role) { const node = document.createElement("div"); node.className = `chat-bubble ${role}`; node.textContent = message; $("#chat-messages").append(node); scrollChat(); return node; }

function openModal(content, extraClass = "") {
  $("#modal-root").innerHTML = `<div class="modal-overlay" role="presentation"><section class="modal ${extraClass}" role="dialog" aria-modal="true">${content}</section></div>`;
  document.body.style.overflow = "hidden"; iconRefresh(); setTimeout(() => $("#modal-root button, #modal-root input, #modal-root textarea, #modal-root select")?.focus(), 0);
}
function closeModal() { $("#modal-root").innerHTML = ""; document.body.style.overflow = ""; }
function confirmDialog(title, text, onConfirm, confirmLabel = "Confirm", danger = false) {
  openModal(`<div class="modal-head"><div><span class="kicker">Please confirm</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(text)}</p></div><button class="icon-btn" type="button" data-close-modal aria-label="Close"><i data-lucide="x"></i></button></div><div class="modal-actions"><button class="btn btn-soft" type="button" data-close-modal>Go back</button><button class="btn ${danger ? "btn-danger-soft" : "btn-primary"}" id="confirm-action-button" type="button">${escapeHtml(confirmLabel)}</button></div>`);
  $("#confirm-action-button").addEventListener("click", event => onConfirm(event.currentTarget));
}

function handleDynamicAction(button) {
  const {action, id, status, active, report} = button.dataset;
  const actions = {
    logout, "reload-menu": () => loadMenu(true), "clear-menu-search": () => { state.menuFilter = "All"; state.menuSearch = ""; $("#menu-search").value = ""; renderMenuFilters(); renderMenu(); },
    "add-cart": () => addToCart(id), "cart-minus": () => updateCartQuantity(id, -1), "cart-plus": () => updateCartQuantity(id, 1), "remove-cart": () => removeCartItem(id),
    "reload-orders": loadOrders, "cancel-order": () => cancelOrder(id), feedback: () => openFeedback(id), "mark-read": () => markRead(id), "reload-notifications": loadNotifications,
    "reload-profile": loadProfile, "reload-dashboard": loadDashboard, "reload-admin-menu": loadAdminMenu, "add-menu": () => openMenuForm(), "edit-menu": () => openMenuForm(id), "delete-menu": () => deleteMenu(id),
    "reload-inventory": loadInventory, "update-stock": () => updateStock(id, button), "reload-admin-orders": loadAdminOrders, "order-status": () => updateOrderStatus(id, status, button),
    "reload-users": loadUsers, "user-status": () => changeUserStatus(id, active === "true"), "reload-feedback": loadAdminFeedback, "reload-reports": loadReports,
    "export-report": () => exportReport(report), "reload-insights": loadInsights
  };
  actions[action]?.();
}

function bindEvents() {
  document.addEventListener("click", event => {
    const viewButton = event.target.closest("[data-view]");
    if (viewButton) { if (viewButton.hasAttribute("data-close-modal")) closeModal(); showView(viewButton.dataset.view); return; }
    const close = event.target.closest("[data-close-modal]"); if (close) return closeModal();
    const adminButton = event.target.closest("[data-admin-tab]"); if (adminButton) return showAdminTab(adminButton.dataset.adminTab);
    const filter = event.target.closest("[data-filter]"); if (filter) { state.menuFilter = filter.dataset.filter; renderMenuFilters(); renderMenu(); return; }
    const action = event.target.closest("[data-action]"); if (action) handleDynamicAction(action);
    const rating = event.target.closest("[data-rating]"); if (rating) updateStars(Number(rating.dataset.rating));
  });
  document.addEventListener("submit", event => {
    if (event.target.id === "feedback-form") submitFeedback(event);
    if (event.target.id === "menu-item-form") submitMenuForm(event);
  });
  document.addEventListener("error", event => {
    if (!(event.target instanceof HTMLImageElement) || !event.target.hasAttribute("data-fallback-image")) return;
    if (event.target.dataset.fallbackApplied !== "true") {
      event.target.dataset.fallbackApplied = "true";
      event.target.src = event.target.dataset.fallbackSrc || IMAGE_FALLBACKS.default;
      return;
    }
    const fallback = document.createElement("div"); fallback.className = "image-fallback"; fallback.innerHTML = `<i data-lucide="utensils"></i>`; event.target.replaceWith(fallback); iconRefresh();
  }, true);
  $("#login-form").addEventListener("submit", handleLogin); $("#register-form").addEventListener("submit", handleRegister); $("#profile-form").addEventListener("submit", updateProfile);
  $("#place-order-button").addEventListener("click", placeOrder); $("#clear-cart").addEventListener("click", () => { state.cart = []; saveCart(); renderCart(); });
  $("#menu-search").addEventListener("input", event => { state.menuSearch = event.target.value.trim(); renderMenu(); });
  $("#mark-all-read").addEventListener("click", markAllRead); $("#recommend-button").addEventListener("click", recommend);
  $("#add-menu-button").addEventListener("click", () => openMenuForm()); $("#user-search").addEventListener("input", renderUsers);
  $("#refresh-insights").addEventListener("click", loadInsights); $("#chat-form").addEventListener("submit", sendChat);
  $("#chat-launcher").addEventListener("click", () => $("#chat-panel").classList.toggle("hidden")); $("#chat-close").addEventListener("click", () => $("#chat-panel").classList.add("hidden"));
  $("#mobile-menu-trigger").addEventListener("click", event => { const open = $("#mobile-menu").classList.toggle("open"); event.currentTarget.setAttribute("aria-expanded", String(open)); });
  $$("[data-password-target]").forEach(button => button.addEventListener("click", () => { const input = $(`#${button.dataset.passwordTarget}`); input.type = input.type === "password" ? "text" : "password"; button.setAttribute("aria-label", input.type === "password" ? "Show password" : "Hide password"); }));
  document.addEventListener("keydown", event => { if (event.key === "Escape" && $("#modal-root").children.length) closeModal(); });
  $("#modal-root").addEventListener("click", event => { if (event.target.classList.contains("modal-overlay")) closeModal(); });
  document.addEventListener("click", event => { if (event.target.id === "load-reports-button" || event.target.closest("#load-reports-button")) loadReports(); });
}

async function init() {
  $("#current-year").textContent = new Date().getFullYear(); bindEvents(); updateNavigation(); renderCart();
  if (state.token) {
    try { state.user = await expectOk(await api("/api/auth/me"), "Your session is no longer valid"); state.isAdmin = Boolean(state.user.is_admin); localStorage.setItem(ADMIN_KEY, String(state.isAdmin)); }
    catch { clearSession(); }
  }
  updateNavigation();
  const requested = location.hash.replace("#", "") || (state.token ? (state.isAdmin ? "admin" : "menu") : "home");
  showView(requested); iconRefresh();
}

document.addEventListener("DOMContentLoaded", init);
