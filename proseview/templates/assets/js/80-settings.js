// Settings UI Logic

function markSettingsDirty() {
    const btn = document.getElementById("settingsSaveBtn");
    if (btn) {
        btn.disabled = false;
    }
}

async function saveSettings() {
    const btn = document.getElementById("settingsSaveBtn");
    const originalText = btn.innerText;
    btn.innerText = "Saving...";
    btn.disabled = true;

    try {
        const payload = {
            target_words: document.getElementById("setting_target_words").value,
            daily_target: document.getElementById("setting_daily_target").value,
            genre: document.getElementById("setting_genre").value
        };

        // pvHeaders() is the single source of the session header name. Spelling
        // it out here sent "X-Session-Token" while the server reads
        // "X-Proseview-Session", so every save was rejected as unauthorized.
        const res = await fetch("/api/settings", {
            method: "PATCH",
            headers: pvHeaders(),
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.error || "Failed to save settings");
        }

        btn.innerText = "Saved";
        const banner = document.getElementById("settingsEmptyBanner");
        if (banner) {
            banner.style.display = "none";
        }
    } catch (err) {
        console.error("Save settings error:", err);
        btn.innerText = "Error";
        btn.classList.add("danger");
        setTimeout(() => {
            btn.innerText = "Save changes";
            btn.classList.remove("danger");
            btn.disabled = false;
        }, 3000);
    }
}

function updateBackupStats() {
    fetch('/api/backups/stats')
        .then(res => res.json())
        .then(data => {
            const el = document.getElementById('setting_backup_size');
            if (el) {
                if (data.ok) {
                    el.textContent = data.formatted;
                } else {
                    el.textContent = "Error";
                }
            }
        })
        .catch(err => console.error("Stats fetch error", err));
}

function clearAllBackups() {
    if (!confirm("Are you sure you want to clear ALL backups for this project? This cannot be undone.")) return;
    fetch('/api/backups', { method: 'DELETE', headers: pvHeaders() })
        .then(res => res.json())
        .then(data => {
            if (!data.ok) {
                alert("Failed to clear backups: " + data.error);
                return;
            }
            updateBackupStats();
            // If history tab is open, refresh it
            if (paths[curIdx] && document.getElementById('sceneHistoryPane') && !document.getElementById('sceneHistoryPane').hidden) {
                if (typeof loadSceneHistory === "function") {
                    loadSceneHistory(paths[curIdx]);
                }
            }
        });
}

// Settings is a dialog over whatever tab is open: the goals, genre and
// theme are changed now and then, never worked in.
function openSettings() {
    const dialog = document.getElementById('settingsDialog');
    if (!dialog || dialog.open) return;
    dialog.showModal();
    updateBackupStats();
}

function closeSettings() {
    const dialog = document.getElementById('settingsDialog');
    if (dialog && dialog.open) dialog.close();
}

document.addEventListener('DOMContentLoaded', () => {
    // Esc closes an open theme list first, not the whole dialog. The list's
    // own Esc handler has closed it by the time "cancel" fires, so note
    // whether it was open before any handler ran.
    const dialog = document.getElementById('settingsDialog');
    let themeListWasOpen = false;
    if (dialog) {
        dialog.addEventListener('keydown', function(event) {
            if (event.key === 'Escape') {
                themeListWasOpen = typeof themeMenuIsOpen === 'function' && themeMenuIsOpen();
            }
        }, true);
        dialog.addEventListener('cancel', function(event) {
            if (themeListWasOpen) event.preventDefault();
            themeListWasOpen = false;
        });
    }
});
