async function copyViewerCode(button) {
  try {
    const text = JSON.parse(button.dataset.copy || '""');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    }
    button.classList.add("is-copied");
    button.setAttribute("title", button.dataset.labelActive || "복사됨");
    button.setAttribute("aria-label", button.dataset.labelActive || "복사됨");
    window.setTimeout(() => {
      button.classList.remove("is-copied");
      button.setAttribute("title", button.dataset.labelDefault || "복사");
      button.setAttribute("aria-label", button.dataset.labelDefault || "복사");
    }, 1400);
  } catch (error) {
    button.setAttribute("title", "실패");
    button.setAttribute("aria-label", "실패");
    window.setTimeout(() => {
      const label = button.dataset.labelDefault || "복사";
      button.setAttribute("title", label);
      button.setAttribute("aria-label", label);
    }, 1400);
  }
}

function toggleViewerCodeWrap(button) {
  const block = button.closest(".code-block");
  if (!block) return;
  block.classList.toggle("is-wrapped");
  const wrapped = block.classList.contains("is-wrapped");
  const label = wrapped
    ? (button.dataset.labelActive || "줄바꿈 해제")
    : (button.dataset.labelDefault || "줄바꿈");
  button.setAttribute("aria-pressed", wrapped ? "true" : "false");
  button.setAttribute("title", label);
  button.setAttribute("aria-label", label);
}

function toggleViewerCodeCollapse(button) {
  const block = button.closest(".code-block");
  if (!block) return;
  block.classList.toggle("is-collapsed");
  const collapsed = block.classList.contains("is-collapsed");
  button.textContent = collapsed
    ? (button.dataset.labelCollapsed || "Show more")
    : (button.dataset.labelExpanded || "Show less");
  button.classList.toggle("is-collapsed", collapsed);
  button.setAttribute("aria-expanded", collapsed ? "false" : "true");
}

const OVERLAY_USER_KEY = "playbook_studio_overlay_user";

function overlayUserId() {
  return window.localStorage.getItem(OVERLAY_USER_KEY) || "viewer-user";
}

async function overlayFetch(path, init) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json; charset=utf-8" },
    ...init,
  });
  if (!response.ok) {
    throw new Error("overlay request failed");
  }
  return response.json();
}

function toolbarPayload(toolbar) {
  return {
    user_id: overlayUserId(),
    target_kind: toolbar.dataset.targetKind || "",
    target_ref: toolbar.dataset.targetRef || "",
    book_slug: toolbar.dataset.bookSlug || "",
    anchor: toolbar.dataset.anchor || "",
    asset_name: toolbar.dataset.assetName || "",
    entity_slug: toolbar.dataset.entitySlug || "",
    viewer_path: toolbar.dataset.viewerPath || window.location.pathname + window.location.hash,
  };
}

async function markRecentPosition() {
  const target = document.querySelector(".overlay-page-target[data-page-root='true']");
  if (!target) return;
  const payload = toolbarPayload(target);
  await overlayFetch("/api/wiki-overlays", {
    method: "POST",
    body: JSON.stringify({ ...payload, kind: "recent_position" }),
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await markRecentPosition();
  } catch (error) {
    console.error(error);
  }
});

document.addEventListener("click", (event) => {
  const anchor = event.target instanceof Element ? event.target.closest(".document-nav-menu a[href]") : null;
  if (!(anchor instanceof HTMLAnchorElement)) {
    return;
  }
  const menu = anchor.closest(".document-nav-menu");
  if (menu instanceof HTMLDetailsElement) {
    menu.open = false;
  }
});

if (window.self !== window.top) {
  document.body.classList.add("is-embedded");
}
