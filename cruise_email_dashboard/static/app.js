const sidebar = document.getElementById("sidebar");
const backdrop = document.getElementById("backdrop");
const hamburger = document.getElementById("hamburger");
const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');

function getCsrfToken() {
    return csrfTokenMeta?.content || "";
}

function withCsrfHeaders(headers = {}) {
    const token = getCsrfToken();
    if (!token) {
        return { ...headers };
    }
    return {
        ...headers,
        "X-CSRF-Token": token,
    };
}

window.dashboardCsrf = {
    getToken: getCsrfToken,
    withHeaders: withCsrfHeaders,
};

function openSidebar() {
    sidebar?.classList.remove("-translate-x-full");
    backdrop?.classList.remove("hidden");
    document.body.style.overflow = "hidden";
}

function closeSidebar() {
    sidebar?.classList.add("-translate-x-full");
    backdrop?.classList.add("hidden");
    document.body.style.overflow = "";
}

if (window.innerWidth < 768) {
    closeSidebar();
}

window.addEventListener("DOMContentLoaded", () => {
    if (window.innerWidth < 768) {
        closeSidebar();
    }
});

window.addEventListener("pageshow", () => {
    if (window.innerWidth < 768) {
        closeSidebar();
    }
});

hamburger?.addEventListener("click", () => {
    console.log("hamburger clicked");
    openSidebar();
});
backdrop?.addEventListener("click", closeSidebar);

document.querySelectorAll("#sidebar a").forEach((a) => {
    a.addEventListener("click", () => {
        if (window.innerWidth < 768) {
            closeSidebar();
        }
    });
});

document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement)) {
        return;
    }
    if ((form.method || "").toLowerCase() !== "post") {
        return;
    }
    if (form.dataset.submitting === "true") {
        event.preventDefault();
        return;
    }
    form.dataset.submitting = "true";
    form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((control) => {
        control.disabled = true;
        control.classList.add("opacity-60", "cursor-not-allowed");
    });
});

document.querySelectorAll("form").forEach((form) => {
    if ((form.method || "").toLowerCase() !== "post") {
        return;
    }
    if (form.querySelector('input[name="csrf_token"]')) {
        return;
    }
    const token = getCsrfToken();
    if (!token) {
        return;
    }
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = token;
    form.prepend(input);
});

window.addEventListener("pageshow", () => {
    document.querySelectorAll("form[data-submitting='true']").forEach((form) => {
        form.dataset.submitting = "false";
        form.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((control) => {
            control.disabled = false;
            control.classList.remove("opacity-60", "cursor-not-allowed");
        });
    });
});

function updateUnreadBadge(count) {
    const badge = document.getElementById("sidebarUnreadBadge");
    if (!badge) {
        return;
    }
    badge.textContent = count;
    badge.classList.toggle("hidden", !count);
}

function dispatchDashboardEvent(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail }));
}

let dashboardEventSource = null;
let dashboardReconnectTimer = null;

function cleanupDashboardStream() {
    if (dashboardReconnectTimer) {
        window.clearTimeout(dashboardReconnectTimer);
        dashboardReconnectTimer = null;
    }
    if (dashboardEventSource) {
        dashboardEventSource.close();
        dashboardEventSource = null;
    }
}

function scheduleDashboardReconnect() {
    if (dashboardReconnectTimer || document.visibilityState === "hidden") {
        return;
    }
    dashboardReconnectTimer = window.setTimeout(() => {
        dashboardReconnectTimer = null;
        connectDashboardStream();
    }, 3000);
}

function connectDashboardStream() {
    if (!window.EventSource || !document.getElementById("sidebarUnreadBadge") || dashboardEventSource) {
        return;
    }
    cleanupDashboardStream();
    const source = new EventSource("/stream");
    dashboardEventSource = source;
    source.addEventListener("open", () => {
        if (dashboardReconnectTimer) {
            window.clearTimeout(dashboardReconnectTimer);
            dashboardReconnectTimer = null;
        }
    });
    source.addEventListener("new_emails", (event) => {
        const data = JSON.parse(event.data);
        dispatchDashboardEvent("dashboard:new-emails", data);
        if (window.Notification && Notification.permission === "granted") {
            new Notification("New customer emails", {
                body: `${data.count} new email(s) have arrived in the inbox.`,
            });
        }
    });
    source.addEventListener("unread_count", (event) => {
        const data = JSON.parse(event.data);
        updateUnreadBadge(data.count);
        dispatchDashboardEvent("dashboard:unread-count", data);
    });
    source.addEventListener("presence_changed", (event) => {
        dispatchDashboardEvent("dashboard:presence-changed", JSON.parse(event.data));
    });
    source.onerror = () => {
        cleanupDashboardStream();
        scheduleDashboardReconnect();
    };
}

if (window.Notification && Notification.permission === "default") {
    Notification.requestPermission();
}

if (document.getElementById("sidebarUnreadBadge")) {
    connectDashboardStream();
}

document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
        connectDashboardStream();
    }
});

window.addEventListener("pagehide", cleanupDashboardStream);
window.addEventListener("beforeunload", cleanupDashboardStream);
