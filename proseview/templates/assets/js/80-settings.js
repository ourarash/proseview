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
            genre: document.getElementById("setting_genre").value,
            mattr_band: [
                parseInt(document.getElementById("setting_mattr_min").value) / 100,
                parseInt(document.getElementById("setting_mattr_max").value) / 100
            ],
            mtld_band: [
                parseInt(document.getElementById("setting_mtld_min").value),
                parseInt(document.getElementById("setting_mtld_max").value)
            ]
        };

        const res = await fetch("/api/settings", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
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
