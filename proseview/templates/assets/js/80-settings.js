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
            btn.innerText = "Save Changes";
            btn.classList.remove("danger");
            btn.disabled = false;
        }, 3000);
    }
}
