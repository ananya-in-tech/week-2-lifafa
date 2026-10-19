// Shared helpers for every Lifafa screen.

export const app = document.getElementById("app");
export const dialog = document.getElementById("dialog");
export const dialogBody = document.getElementById("dialog-body");

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function rupees(n) {
  if (n === null || n === undefined || n === "") return "";
  return "₹" + Number(n).toLocaleString("en-IN");
}

export function prettyDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    ...options,
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
  });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(Array.isArray(d) ? `${d[0].loc.at(-1)}: ${d[0].msg}` : d || `Request failed (${res.status})`);
  }
  return body;
}

export function openDialog(html) {
  dialogBody.innerHTML = html;
  if (!dialog.open) dialog.showModal();
}
dialog.addEventListener("click", (e) => { if (e.target === dialog || e.target.closest("[data-close]")) dialog.close(); });

export function toast(msg, tone = "warn") {
  const p = document.createElement("p");
  p.className = `banner ${tone}`;
  p.textContent = msg;
  app.prepend(p);
  setTimeout(() => p.remove(), 6000);
}

export function alertIn(msg) {
  const p = document.createElement("p");
  p.className = "banner warn";
  p.textContent = msg;
  dialogBody.prepend(p);
}
