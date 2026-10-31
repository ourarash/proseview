// Settings UI Logic

function markSettingsDirty() {
    const btn = document.getElementById("settingsSaveBtn");
    if (btn) {
        btn.disabled = false;
    }
}

// Word variety: the typical Variety and MTLD ranges. Sent only once the
// writer picks something: a preset is a genre, saved as the genre with no
// ranges of the book's own; Custom saves both ranges.
let _varietyEdited = false;

function pickVariety() {
    const custom = document.getElementById("setting_variety").value === "custom";
    document.getElementById("settingVarietyCustom").hidden = !custom;
    editVariety();
}

function editVariety() {
    _varietyEdited = true;
    markSettingsDirty();
}

// Two numbers, the lower first, or the browser says what is wrong.
function _bandValue(key) {
    const low = document.getElementById(`setting_${key}_low`);
    const high = document.getElementById(`setting_${key}_high`);
    high.setCustomValidity("");
    if (!low.reportValidity() || !high.reportValidity()) return undefined;
    if (Number(low.value) >= Number(high.value)) {
        high.setCustomValidity("Make this higher than the first number.");
        high.reportValidity();
        return undefined;
    }
    return [Number(low.value), Number(high.value)];
}

// What to send for the picked preset; undefined when a custom range is wrong.
function _varietyPayload() {
    const pick = document.getElementById("setting_variety").value;
    if (pick !== "custom") return {genre: pick, mattr_band: null, mtld_band: null};
    const mattr = _bandValue("mattr");
    const mtld = mattr && _bandValue("mtld");
    return mtld ? {mattr_band: mattr, mtld_band: mtld} : undefined;
}

// Word variety's ⓘ says what the scene page's does, for the ranges in use.
function _showVarietyInfo() {
    const label = document.querySelector('label[for="setting_variety"]');
    if (!label || typeof wordVarietyAbout !== "function") return;
    label.querySelectorAll(".scene-pass-info, .scene-pass-info-pop").forEach(function(el) { el.remove(); });
    const parts = _sceneInfo("settingVarietyInfo", "About word variety", wordVarietyAbout(null, false));
    label.insertBefore(parts[1], label.querySelector(".settings-hint"));
    label.insertBefore(parts[0], parts[1]);
}

// After a save, the picker and the page show the ranges now in use.
function _showBands(bands) {
    if (!bands) return;
    Object.assign(lexicalBands, bands);
    document.getElementById("setting_variety").value = bands.preset;
    document.getElementById("settingVarietyCustom").hidden = bands.preset !== "custom";
    ["mattr", "mtld"].forEach(function(key) {
        document.getElementById(`setting_${key}_low`).value = bands[key][0];
        document.getElementById(`setting_${key}_high`).value = bands[key][1];
    });
    _varietyEdited = false;
    _showVarietyInfo();
    if (typeof refreshSceneSummary === "function") refreshSceneSummary();
}

async function saveSettings() {
    const btn = document.getElementById("settingsSaveBtn");
    const payload = {
        target_words: document.getElementById("setting_target_words").value,
        daily_target: document.getElementById("setting_daily_target").value
    };
    if (_varietyEdited) {
        const bands = _varietyPayload();
        if (bands === undefined) return;
        Object.assign(payload, bands);
    }
    const originalText = btn.innerText;
    btn.innerText = "Saving...";
    btn.disabled = true;

    try {

        // pvHeaders() is the single source of the session header name. Spelling
        // it out here sent "X-Session-Token" while the server reads
        // "X-Proseview-Session", so every save was rejected as unauthorized.
        const res = await fetch("/api/settings", {
            method: "PATCH",
            headers: pvHeaders(),
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || "Failed to save settings");
        _showBands(data.lexical_bands);
        // Suggestions keep their own store; they save with the same button.
        if (typeof saveSuggestionSettings === "function") await saveSuggestionSettings();

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

// Settings is a dialog over whatever tab is open: the goals, word variety and
// theme are changed now and then, never worked in.
function openSettings() {
    const dialog = document.getElementById('settingsDialog');
    if (!dialog || dialog.open) return;
    _showVarietyInfo();
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

// Settings is as wide as the writer last left it. The dialog is centred, so
// the edge moves half as far as the width changes: dragging it by d widens
// the dialog by 2d.
const SETTINGS_WIDTH_KEY = 'proseview-settings-width';
const SETTINGS_WIDTH_MIN = 520;

function setSettingsWidth(width, remember) {
    const dialog = document.getElementById('settingsDialog');
    if (!dialog) return;
    if (width === null) {
        dialog.style.removeProperty('--settings-width');
        try { localStorage.removeItem(SETTINGS_WIDTH_KEY); } catch (e) {}
        return;
    }
    const clamped = Math.round(Math.max(SETTINGS_WIDTH_MIN, Math.min(width, window.innerWidth - 32)));
    dialog.style.setProperty('--settings-width', clamped + 'px');
    if (remember) {
        try { localStorage.setItem(SETTINGS_WIDTH_KEY, String(clamped)); } catch (e) {}
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const dialog = document.getElementById('settingsDialog');
    const handle = dialog && dialog.querySelector('.settings-resize');
    if (!handle) return;
    try {
        const saved = Number(localStorage.getItem(SETTINGS_WIDTH_KEY));
        if (saved) setSettingsWidth(saved, false);
    } catch (e) {}
    handle.addEventListener('pointerdown', (event) => {
        event.preventDefault();
        const startX = event.clientX;
        const startWidth = dialog.getBoundingClientRect().width;
        handle.setPointerCapture(event.pointerId);
        handle.classList.add('is-dragging');
        const move = (e) => setSettingsWidth(startWidth + 2 * (e.clientX - startX), false);
        const up = (e) => {
            handle.releasePointerCapture(event.pointerId);
            handle.classList.remove('is-dragging');
            handle.removeEventListener('pointermove', move);
            handle.removeEventListener('pointerup', up);
            setSettingsWidth(startWidth + 2 * (e.clientX - startX), true);
        };
        handle.addEventListener('pointermove', move);
        handle.addEventListener('pointerup', up);
    });
    handle.addEventListener('dblclick', () => setSettingsWidth(null));
    handle.addEventListener('keydown', (event) => {
        if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
        event.preventDefault();
        const width = dialog.getBoundingClientRect().width;
        setSettingsWidth(width + (event.key === 'ArrowRight' ? 40 : -40), true);
    });
});
