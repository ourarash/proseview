        // Lossless save for the scene and note editors.
        //
        // The stock Markdown serializer rewrites what it does not model:
        // [[wikilinks]] come back escaped, > [!note] callouts lose their line
        // breaks, `-` bullets turn into `*` and _italic_ into *italic*. So a
        // save would rewrite text nobody touched. When a document opens,
        // markdownSourceBlocks keeps each top-level block's source text next
        // to how the serializer writes that block; serializeKeepingSource then
        // writes a block that still serializes the same as its source, and only
        // edited or new blocks go through the serializer.

        // *tokenizer* with inline HTML (`<br>`, `<span>`) kept as literal
        // text. The editor has no node for it: ProseMirror's parser throws on
        // the token (which left the scene blank), and dropping it would lose
        // it on save.
        function tokenizerKeepingInlineHtml(tokenizer) {
            return {parse: function(src, env) {
                var tokens = tokenizer.parse(src, env);
                tokens.forEach(function(token) {
                    (token.children || []).forEach(function(child) {
                        if (child.type === 'html_inline') child.type = 'text';
                    });
                });
                return tokens;
            }};
        }

        // One document holding just *node*, as the serializer writes it.
        function _serializeBlock(serializer, doc, node) {
            return serializer.serialize(doc.type.create(doc.attrs, node));
        }

        // The source text of each top-level block of *doc*, parsed from
        // *markdown* by *tokenizer* (markdown-it). Each block's text runs to the
        // start of the next, so it carries the blank lines after it. Null when
        // the tokens and the blocks do not pair up one to one, and the caller
        // falls back to serializing the whole document.
        function markdownSourceBlocks(tokenizer, markdown, doc, serializer) {
            var tokens;
            try {
                tokens = tokenizer.parse(markdown, {});
            } catch (e) {
                return null;
            }
            var starts = [];
            for (var i = 0; i < tokens.length; i++) {
                var t = tokens[i];
                if (t.level !== 0 || !t.map || t.nesting === -1) continue;
                starts.push(t.map[0]);
                if (t.nesting === 1) {
                    for (var depth = 1; depth > 0 && ++i < tokens.length;) depth += tokens[i].nesting;
                }
            }
            if (!starts.length || starts.length !== doc.childCount) return null;
            var lineStarts = [0];
            for (var c = markdown.indexOf('\n'); c !== -1; c = markdown.indexOf('\n', c + 1)) lineStarts.push(c + 1);
            function at(line) { return line < lineStarts.length ? lineStarts[line] : markdown.length; }
            var blocks = [];
            doc.forEach(function(node, _offset, index) {
                var end = index + 1 < starts.length ? at(starts[index + 1]) : markdown.length;
                blocks.push({
                    type: node.type.name,
                    serialized: _serializeBlock(serializer, doc, node),
                    source: markdown.slice(at(starts[index]), end),
                });
            });
            return {prefix: markdown.slice(0, at(starts[0])), blocks: blocks, tail: /\n*$/.exec(markdown)[0]};
        }

        // The old block an edited block replaced: the one at the same place
        // between the nearest unchanged blocks, when as many blocks were
        // there before as now.
        function _counterpart(match, k, old) {
            var before = k - 1, after = k + 1;
            while (before >= 0 && match[before] === -1) before--;
            while (after < match.length && match[after] === -1) after++;
            var oldStart = before >= 0 ? match[before] + 1 : 0;
            var oldEnd = after < match.length ? match[after] : old.length;
            if (oldEnd - oldStart !== after - before - 1) return null;
            return old[oldStart + (k - before - 1)] || null;
        }

        // A word that would start a list, heading, quote, rule or HTML block
        // if a wrapped line began with it.
        var _BLOCK_START = /^(?:[-+*>|]|#{1,6}|\d{1,9}[.)]|[=-]+|`{3,}.*|~{3,}.*|<.*)$/;

        // An edited paragraph keeps the lines its source had, so a writer who
        // wraps at 80 columns does not get the paragraph back as one long
        // line and only the lines around the edit change. Unchanged lines at
        // the start and end of the paragraph are written exactly as they were;
        // the changed words between them are wrapped to the paragraph's width
        // (or kept on one line when its lines are short, as in a chat log).
        function _keepWrap(text, type, before) {
            if (type !== 'paragraph' || !before || before.type !== 'paragraph') return text;
            var oldLines = before.source.replace(/\n\s*$/, '').split('\n');
            if (oldLines.length < 2) return text;
            var words = function(line) { return line.replace(/\\$/, '').trim().split(/\s+/).filter(Boolean); };
            // The new words, each marked when a hard break follows it.
            var tokens = [];
            text.split('\n').forEach(function(segment, index, all) {
                var row = words(segment);
                row.forEach(function(word, at) { tokens.push({word: word, hard: index < all.length - 1 && at === row.length - 1}); });
            });
            var fits = function(line, from) {
                var row = words(line);
                if (!row.length || from + row.length > tokens.length) return 0;
                for (var i = 0; i < row.length; i++) if (tokens[from + i].word !== row[i]) return 0;
                return row.length;
            };
            var head = 0, used = 0;
            while (head < oldLines.length) {
                var taken = fits(oldLines[head], used);
                if (!taken) break;
                used += taken; head++;
            }
            var tail = oldLines.length, end = tokens.length;
            while (tail > head) {
                var row = words(oldLines[tail - 1]);
                if (!row.length || end - row.length < used || !fits(oldLines[tail - 1], end - row.length)) break;
                end -= row.length; tail--;
            }
            // Words added at the end of a kept line belong on that line.
            if (head && used < end) { head--; used -= words(oldLines[head]).length; }
            var width = Math.max.apply(null, oldLines.map(function(line) { return line.replace(/\s+$/, '').length; }));
            var hardBreak = oldLines.some(function(line) { return / {2,}$/.test(line); }) ? '  ' : '\\';
            var middle = [], current = '';
            tokens.slice(used, end).forEach(function(token) {
                var wrap = width >= 40 && current && (current + ' ' + token.word).length > width && !_BLOCK_START.test(token.word);
                if (wrap) { middle.push(current); current = ''; }
                current = current ? current + ' ' + token.word : token.word;
                if (token.hard) { middle.push(current + hardBreak); current = ''; }
            });
            if (current) middle.push(current);
            return oldLines.slice(0, head).concat(middle, oldLines.slice(tail)).join('\n');
        }

        // *doc* as Markdown, writing each block that is unchanged since
        // *saved* (from markdownSourceBlocks) exactly as it was in the file.
        function serializeKeepingSource(saved, doc, serializer) {
            if (!saved) return serializer.serialize(doc);
            var now = [], types = [];
            doc.forEach(function(node) { now.push(_serializeBlock(serializer, doc, node)); types.push(node.type.name); });
            var old = saved.blocks;
            // Pair unchanged blocks in order (longest common subsequence),
            // after skipping the common head and tail, so an inserted scene
            // break cannot pair with a later one and orphan everything between.
            var match = new Array(now.length).fill(-1);
            var head = 0;
            while (head < now.length && head < old.length && now[head] === old[head].serialized) { match[head] = head; head++; }
            var tailN = now.length, tailO = old.length;
            while (tailN > head && tailO > head && now[tailN - 1] === old[tailO - 1].serialized) { match[--tailN] = --tailO; }
            var n = tailN - head, m = tailO - head;
            if (n && m) {
                var lcs = [];
                for (var a = 0; a <= n; a++) lcs.push(new Int32Array(m + 1));
                for (a = n - 1; a >= 0; a--) {
                    for (var b = m - 1; b >= 0; b--) {
                        lcs[a][b] = now[head + a] === old[head + b].serialized
                            ? lcs[a + 1][b + 1] + 1 : Math.max(lcs[a + 1][b], lcs[a][b + 1]);
                    }
                }
                for (a = 0, b = 0; a < n && b < m;) {
                    if (now[head + a] === old[head + b].serialized) { match[head + a] = head + b; a++; b++; }
                    else if (lcs[a + 1][b] >= lcs[a][b + 1]) a++;
                    else b++;
                }
            }
            var out = saved.prefix;
            for (var k = 0; k < now.length; k++) {
                var src = match[k];
                var last = k === now.length - 1;
                // A kept block followed by its own successor keeps the exact
                // gap between them; anything else gets one blank line.
                if (src !== -1 && (last ? src === old.length - 1 : match[k + 1] === src + 1)) {
                    out += old[src].source;
                    continue;
                }
                var text = src !== -1 ? old[src].source.replace(/\n\s*$/, '') : _keepWrap(now[k], types[k], _counterpart(match, k, old));
                out += last ? text + saved.tail : text + '\n\n';
            }
            return out;
        }
