function loadSceneHistory(scenePath) {
    fetch(`/api/scene/history?path=${encodeURIComponent(scenePath)}`)
        .then(res => res.json())
        .then(data => {
            if (!data.ok) {
                console.error("Failed to load history:", data.error);
                return;
            }
            const container = document.getElementById("historyListContent");
            if (!container) return;
            
            
            
            let html = "";
            if (data.is_git_repo && !data.git_ignored) {
                html += `<div style="padding: 12px 16px; color: var(--text-muted); font-size: 13px; font-style: italic;">
                    Proseview creates local backups when you save. To keep your Git repository clean, we recommend adding <code>.proseview/backups/</code> to your <code>.gitignore</code>.
                </div>`;
            }
            
            if (data.history.length === 0) {
                const gitNote = data.is_git_repo ? `<br><br><span style="font-size: 11px;">Note: These are temporary, local snapshots and do not replace Git commits.</span>` : ``;
                container.innerHTML = html + `<div style="padding: 24px 16px; color: var(--text-muted); text-align: center; font-size: 13px; line-height: 1.5;">
                    <div style="margin-bottom: 8px;">No local backups found.</div>
                    File history is generated automatically when you save changes or apply AI edits.${gitNote}
                </div>`;
                return;
            }
            data.history.forEach(item => {
                const date = new Date(item.timestamp);
                const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const dateStr = date.toLocaleDateString();
                
                html += `
                    <div class="history-item" onclick="openDiffModal('${scenePath}', '${item.file_ts}')">
                        <div class="history-item-header">
                            <span class="history-item-time">${timeStr} <span style="font-size: 11px; font-weight: normal; color: var(--text-muted);">${dateStr}</span></span>
                            <span class="history-item-source">${item.source}</span>
                        </div>
                        <div class="history-item-details">
                            <span>${item.diff_summary}</span>
                            <span>${item.word_count} words</span>
                        </div>
                    </div>
                `;
            });
            container.innerHTML = html;
        })
        .catch(err => console.error("History fetch error:", err));
}

let currentDiffScene = null;
let currentDiffTs = null;

function openDiffModal(scenePath, timestamp) {
    currentDiffScene = scenePath;
    currentDiffTs = timestamp;
    
    fetch(`/api/scene/history/diff?path=${encodeURIComponent(scenePath)}&timestamp=${encodeURIComponent(timestamp)}`)
        .then(res => res.json())
        .then(data => {
            if (!data.ok) {
                alert("Could not load diff: " + data.error);
                return;
            }
            document.getElementById("diffModalContent").innerHTML = data.diff_html;
            document.getElementById("diffModalOverlay").hidden = false;
        })
        .catch(err => console.error("Diff fetch error:", err));
}

function closeDiffModal() {
    document.getElementById("diffModalOverlay").hidden = true;
    currentDiffScene = null;
    currentDiffTs = null;
}

document.getElementById("diffModalRestoreBtn")?.addEventListener("click", () => {
    if (!currentDiffScene || !currentDiffTs) return;
    
    // Check if dirty
    if (window.isDirty && window.isDirty()) {
        alert("Please save your current changes before restoring an older version.");
        return;
    }
    
    fetch(`/api/scene/history/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentDiffScene, timestamp: currentDiffTs })
    })
    .then(res => res.json())
    .then(data => {
        if (!data.ok) {
            alert("Failed to restore: " + data.error);
            return;
        }
        closeDiffModal();
        refreshContent();
        
        // Show success highlight or toast
        setTimeout(() => {
            const editorView = document.querySelector(".ProseMirror");
            if (editorView) {
                editorView.classList.add("codex-highlight");
                setTimeout(() => editorView.classList.remove("codex-highlight"), 3000);
            }
        }, 500);
    })
    .catch(err => console.error("Restore error:", err));
});

function clearSceneHistory() {
    if (!paths[curIdx]) return;
    if (!confirm("Are you sure you want to clear all history for this file? This cannot be undone.")) return;
    
    fetch(`/api/scene/history?path=${encodeURIComponent(paths[curIdx])}`, {
        method: "DELETE"
    })
    .then(res => res.json())
    .then(data => {
        if (!data.ok) {
            alert("Failed to clear history: " + data.error);
            return;
        }
        loadSceneHistory(paths[curIdx]);
    })
    .catch(err => console.error("Clear history error:", err));
}
