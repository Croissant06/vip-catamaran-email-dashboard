const sidebarToggle = document.getElementById("sidebarToggle");
const sidebar = document.getElementById("sidebar");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");
const sidebarClose = document.getElementById("sidebarClose");

function openSidebar() {
    if (!sidebar) {
        return;
    }
    sidebar.classList.remove("-translate-x-full");
    sidebarBackdrop?.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
}

function closeSidebar() {
    if (!sidebar) {
        return;
    }
    sidebar.classList.add("-translate-x-full");
    sidebarBackdrop?.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
}

if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", openSidebar);
    sidebarClose?.addEventListener("click", closeSidebar);
    sidebarBackdrop?.addEventListener("click", closeSidebar);
    window.addEventListener("resize", () => {
        if (window.innerWidth >= 768) {
            sidebarBackdrop?.classList.add("hidden");
            document.body.classList.remove("overflow-hidden");
        }
    });
}

function updateUnreadBadge(count) {
    const badge = document.getElementById("sidebarUnreadBadge");
    if (!badge) {
        return;
    }
    badge.textContent = count;
    badge.classList.toggle("hidden", !count);
}

if (window.Notification && Notification.permission === "default") {
    Notification.requestPermission();
}

if (window.EventSource && document.getElementById("sidebarUnreadBadge")) {
    const source = new EventSource("/stream");
    source.addEventListener("new_emails", (event) => {
        const data = JSON.parse(event.data);
        if (window.Notification && Notification.permission === "granted") {
            new Notification("New customer emails", {
                body: `${data.count} new email(s) have arrived in the inbox.`,
            });
        }
    });
    source.addEventListener("unread_count", (event) => {
        const data = JSON.parse(event.data);
        updateUnreadBadge(data.count);
    });
}
