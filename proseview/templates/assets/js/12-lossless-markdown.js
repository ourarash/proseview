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
                blocks.push({serialized: _serializeBlock(serializer, doc, node), source: markdown.slice(at(starts[index]), end)});
            });
            return {prefix: markdown.slice(0, at(starts[0])), blocks: blocks, tail: /\n*$/.exec(markdown)[0]};
        }

        // *doc* as Markdown, writing each block that is unchanged since
        // *saved* (from markdownSourceBlocks) exactly as it was in the file.
        function serializeKeepingSource(saved, doc, serializer) {
            if (!saved) return serializer.serialize(doc);
            var now = [];
            doc.forEach(function(node) { now.push(_serializeBlock(serializer, doc, node)); });
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
                var text = (src !== -1 ? old[src].source : now[k]).replace(/\n\s*$/, '');
                out += last ? text + saved.tail : text + '\n\n';
            }
            return out;
        }
