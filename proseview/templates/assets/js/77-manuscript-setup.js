        // Without a manuscript folder the dashboard is a Markdown viewer. The
        // writer says where the book is here; nothing is guessed.
        function openManuscriptChooser() {
            var dialog = document.getElementById('manuscriptChooser');
            var options = document.getElementById('manuscriptChooserOptions');
            if (!dialog || !options) return;
            options.replaceChildren();
            var choices = (sidebarTree || []).filter(function(node) { return !node.is_file; }).map(function(node) {
                return {value: node.path, label: node.path + '/', hint: 'Its folders are the chapters'};
            });
            choices.push({value: '.', label: 'The whole folder', hint: 'Its top-level folders are the chapters'});
            choices.forEach(function(choice) {
                var label = document.createElement('label');
                label.className = 'manuscript-chooser-option';
                var input = document.createElement('input');
                input.type = 'radio';
                input.name = 'manuscriptPath';
                input.value = choice.value;
                var name = document.createElement('strong');
                name.textContent = choice.label;
                var hint = document.createElement('span');
                hint.textContent = choice.hint;
                label.append(input, name, hint);
                options.appendChild(label);
            });
            document.getElementById('manuscriptChooserError').hidden = true;
            dialog.showModal();
        }

        function saveManuscriptChoice() {
            var picked = document.querySelector('#manuscriptChooserOptions input:checked');
            var error = document.getElementById('manuscriptChooserError');
            if (!picked) {
                error.textContent = 'Choose the folder that holds the book.';
                error.hidden = false;
                return;
            }
            fetch('/api/settings', {
                method: 'PATCH',
                headers: pvHeaders(),
                body: JSON.stringify({manuscript_path: picked.value}),
            }).then(function(response) {
                return response.json().catch(function() { return {}; }).then(function(data) {
                    if (!response.ok || !data.ok) throw new Error(data.error || 'The folder could not be saved.');
                    location.reload();
                });
            }).catch(function(problem) {
                error.textContent = problem.message;
                error.hidden = false;
            });
        }
