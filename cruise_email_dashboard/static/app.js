const sidebar = document.getElementById("sidebar");
const backdrop = document.getElementById("backdrop");
const hamburger = document.getElementById("hamburger");

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
