document.addEventListener('DOMContentLoaded', () => {
    function initOverview() {
        if (!storyModel) return;

        // Populate Quick Stats KPIs
        const totalWords = storyModel.total_words || 0;
        const totalScenes = storyModel.scenes ? storyModel.scenes.length : 0;
        const readingTimeMins = Math.ceil(totalWords / 250);

        let openTodosCount = 0;
        if (meta) {
            for (const path in meta) {
                if (meta[path].todos) {
                    openTodosCount += meta[path].todos.length;
                }
            }
        }

        const kpiWordsEl = document.getElementById('kpiTotalWords');
        const kpiScenesEl = document.getElementById('kpiTotalScenes');
        const kpiTimeEl = document.getElementById('kpiReadingTime');
        const kpiTodosEl = document.getElementById('kpiOpenTodos');

        if (kpiWordsEl) kpiWordsEl.innerText = totalWords.toLocaleString();
        if (kpiScenesEl) kpiScenesEl.innerText = totalScenes.toLocaleString();
        if (kpiTimeEl) {
            const hours = Math.floor(readingTimeMins / 60);
            const mins = readingTimeMins % 60;
            kpiTimeEl.innerText = hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
        }
        if (kpiTodosEl) kpiTodosEl.innerText = openTodosCount.toLocaleString();

        // Populate Actionable Insights
        const insightsList = document.getElementById('actionableInsightsList');
        const insightsSection = document.getElementById('actionableInsightsSection');
        if (insightsList && insightsSection) {
            let insightsHtml = '';

            // 1. Missing Location Metadata
            let missingLocationCount = 0;
            if (storyModel.scenes) {
                for (const scene of storyModel.scenes) {
                    if (!scene.where) missingLocationCount++;
                }
            }
            if (missingLocationCount > 0 && totalScenes > 0) {
                insightsHtml += `<li class="actionable-insight-item"><strong>Missing Location Data:</strong> ${missingLocationCount} scene(s) are missing a location tag. Add <code>where: Location Name</code> to their frontmatter to improve the Location chart.</li>`;
            }

            // 2. Open TODOs
            if (openTodosCount > 0) {
                insightsHtml += `<li class="actionable-insight-item"><strong>Open Tasks:</strong> You have ${openTodosCount} open TODO(s) across the manuscript. Check the Scenes table filter to find them.</li>`;
            }

            // 3. No Recent Edits
            if (totalWords === 0) {
                insightsHtml += `<li class="actionable-insight-item"><strong>Get Started:</strong> Your manuscript is empty! Create a new scene to start tracking your progress.</li>`;
            }

            if (insightsHtml.length > 0) {
                insightsList.innerHTML = insightsHtml;
                insightsSection.style.display = '';
            } else {
                insightsSection.style.display = 'none';
            }
        }
    }

    initOverview();
});
