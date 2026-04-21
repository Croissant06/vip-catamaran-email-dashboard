const sidebarToggle = document.getElementById("sidebarToggle");
const sidebar = document.getElementById("sidebar");

if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener("click", () => {
        sidebar.classList.toggle("-translate-x-full");
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
