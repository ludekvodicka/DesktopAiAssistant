(() => {
    if ((globalThis as unknown as {desktopAiLoaded?: boolean}).desktopAiLoaded) return;
    (globalThis as unknown as {desktopAiLoaded?: boolean}).desktopAiLoaded = true;
    type Field = HTMLElement | HTMLInputElement | HTMLTextAreaElement;
    type RecordEntry = {element: Field; full: string; text: string; start: number; end: number; selection: string; context: string; range?: [number[], number, number[], number]; nodes: Map<string, Node>; after?: string};
    const records = new Map<string, RecordEntry>();
    let composing: EventTarget | null = null;
    document.addEventListener('compositionstart', event => { composing = event.target; });
    document.addEventListener('compositionend', () => { composing = null; });
    const escapeText = (text: string) => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    const isPlain = (element: Field): element is HTMLInputElement | HTMLTextAreaElement => element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement;
    const fullText = (element: Field) => isPlain(element) ? element.value : element.innerHTML;
    const contextKey = (element: Field) => JSON.stringify([location.href, element.id, element.getAttribute('name'), element.getAttribute('type'), element.getAttribute('role'), element.getAttribute('contenteditable')]);
    function path(node: Node, root: Node): number[] {
        const result: number[] = [];
        while (node !== root) {
            const parent = node.parentNode;
            if (!parent) throw Error('Editor detached');
            result.unshift(Array.prototype.indexOf.call(parent.childNodes, node)); node = parent;
        }
        return result;
    }
    function selectionKey(element: Field) {
        if (isPlain(element)) return JSON.stringify([element.selectionStart, element.selectionEnd, element.selectionDirection]);
        const selection = getSelection();
        if (!selection || selection.rangeCount !== 1) throw Error('No single selection');
        const range = selection.getRangeAt(0);
        if (!element.contains(range.startContainer) || !element.contains(range.endContainer)) throw Error('Selection crosses editors');
        return JSON.stringify([path(range.startContainer, element), range.startOffset, path(range.endContainer, element), range.endOffset]);
    }
    function focused(): Field {
        if (!document.hasFocus() || composing) throw Error('Focus a field and finish text composition');
        const active = document.activeElement;
        if (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) {
            if (active.readOnly || active.disabled || active instanceof HTMLInputElement && !['text', 'search'].includes(active.type)) throw Error('Unsupported field');
            if (location.hostname === 'mail.google.com' && !(active instanceof HTMLInputElement && active.name === 'subjectbox')) throw Error('Focus the Gmail subject or message body');
            return active;
        }
        const editor = active instanceof HTMLElement ? active.closest<HTMLElement>('[contenteditable="true"]') : null;
        if (!editor || location.hostname !== 'mail.google.com' || editor.getAttribute('role') !== 'textbox') throw Error('Rich editing is supported in Gmail compose only');
        return editor;
    }
    function encode(fragment: DocumentFragment, protect: boolean) {
        const nodes = new Map<string, Node>(); let counter = 0;
        function walk(node: Node): string {
            if (node.nodeType === Node.TEXT_NODE) return escapeText(node.textContent || '');
            if (!(node instanceof Element)) throw Error('Unsupported editor node');
            if (['SCRIPT', 'STYLE', 'IFRAME', 'INPUT', 'BUTTON'].includes(node.tagName)) throw Error('Unsupported embedded content');
            const object = ['BR', 'IMG', 'HR'].includes(node.tagName) || node.getAttribute('contenteditable') === 'false' || protect && node.matches('.gmail_signature, .gmail_quote, [data-smartmail="gmail_signature"]');
            const id = `${object ? 'o' : 't'}${counter++}`;
            nodes.set(id, node.cloneNode(object));
            if (object) return `<${id}/>`;
            return `<${id}>${Array.from(node.childNodes).map(walk).join('')}</${id}>`;
        }
        return {text: Array.from(fragment.childNodes).map(walk).join(''), nodes};
    }
    function render(text: string, record: RecordEntry) {
        const markers = (value: string) => value.match(/<\/?t\d+>|<o\d+\/>/g)?.join('|') || '';
        if (markers(text) !== markers(record.text)) throw Error('Formatting marker order or nesting changed');
        const document = new DOMParser().parseFromString(`<root>${text}</root>`, 'application/xml');
        if (document.querySelector('parsererror')) throw Error('Malformed formatting markers');
        const seen: string[] = [];
        function walk(node: Node): Node {
            if (node.nodeType === Node.TEXT_NODE) return window.document.createTextNode(node.textContent || '');
            if (node.nodeType !== Node.ELEMENT_NODE) throw Error('Invalid formatting node');
            const element = node as Element;
            const source = record.nodes.get(element.tagName);
            if (!source || element.attributes.length || seen.includes(element.tagName)) throw Error('Unknown or duplicate formatting marker');
            seen.push(element.tagName);
            if (element.tagName.startsWith('o')) {
                if (element.childNodes.length) throw Error('Protected object was modified');
                return source.cloneNode(true);
            }
            const clone = source.cloneNode(false);
            for (const child of Array.from(element.childNodes)) clone.appendChild(walk(child));
            return clone;
        }
        const container = window.document.createElement('div');
        for (const child of Array.from(document.documentElement.childNodes)) container.appendChild(walk(child));
        if (seen.join(',') !== [...record.nodes.keys()].join(',')) throw Error('Formatting markers changed');
        return container.innerHTML;
    }
    function capture() {
        const element = focused();
        const full = fullText(element);
        if (full.length > 500000) throw Error('Editor is too large');
        const selection = selectionKey(element);
        let record: RecordEntry;
        if (isPlain(element)) {
            if (element.selectionStart === null || element.selectionEnd === null) throw Error('Selection unavailable');
            const selected = element.selectionStart !== element.selectionEnd;
            const start = selected ? element.selectionStart : 0;
            const end = selected ? element.selectionEnd : full.length;
            record = {element, full, text: full.slice(start, end), start, end, selection, context: contextKey(element), nodes: new Map()};
        } else {
            const selected = getSelection()!;
            const range = selected.getRangeAt(0).cloneRange();
            const whole = range.collapsed;
            if (whole) range.selectNodeContents(element);
            const encoded = encode(range.cloneContents(), whole);
            record = {element, full, text: encoded.text, start: 0, end: 0, selection, context: contextKey(element), range: [path(range.startContainer, element), range.startOffset, path(range.endContainer, element), range.endOffset], nodes: encoded.nodes};
        }
        if (records.size > 100) records.delete(records.keys().next().value!);
        const token = crypto.randomUUID(); records.set(token, record);
        return {token, full, text: record.text, url: location.origin, document: performance.timeOrigin, rich: !isPlain(element)};
    }
    function apply(snapshot: {token: string; document: number; insert?: boolean}, text: string) {
        const record = records.get(snapshot.token);
        if (!record || snapshot.document !== performance.timeOrigin || !record.element.isConnected || contextKey(record.element) !== record.context || fullText(record.element) !== record.full) throw Error('The original editor or document changed; result kept in history');
        if (composing instanceof Node && record.element.contains(composing)) return {deferred: true};
        const background = !document.hasFocus() || document.activeElement !== record.element;
        if (isPlain(record.element)) {
            if (record.element.readOnly || record.element.disabled) throw Error('The original field is no longer editable');
            const originalSelection = JSON.parse(record.selection) as [number, number, string];
            const start = snapshot.insert ? originalSelection[0] : record.start;
            const end = snapshot.insert ? originalSelection[1] : record.end;
            record.element.setRangeText(text, start, end, 'preserve');
            record.element.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertReplacementText', data: text}));
            if (record.element.value !== record.full.slice(0, start) + text + record.full.slice(end)) throw Error('Write was not verified');
        } else {
            if (background) return {deferred: true};
            if (focused() !== record.element) return {deferred: true};
            const html = render(text, record);
            const clone = record.element.cloneNode(true) as HTMLElement;
            const locate = (root: Node, indices: number[]) => indices.reduce((node, index) => node.childNodes[index], root);
            const [startPath, startOffset, endPath, endOffset] = record.range!;
            const expected = document.createRange();
            expected.setStart(locate(clone, startPath), startOffset);
            expected.setEnd(locate(clone, endPath), endOffset);
            expected.deleteContents(); expected.insertNode(expected.createContextualFragment(html));
            const selection = getSelection()!;
            const range = document.createRange();
            range.setStart(locate(record.element, startPath), startOffset);
            range.setEnd(locate(record.element, endPath), endOffset);
            selection.removeAllRanges(); selection.addRange(range);
            if (!document.execCommand('insertHTML', false, html)) throw Error('Editor rejected formatted insertion');
            record.element.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertReplacementText'}));
            const objects = (node: HTMLElement) => Array.from(node.querySelectorAll('img,a,.gmail_signature,.gmail_quote')).map(element => [element.tagName, element.getAttribute('src'), element.getAttribute('href'), element.textContent]);
            if (record.element.textContent !== clone.textContent || JSON.stringify(objects(record.element)) !== JSON.stringify(objects(clone))) throw Error('Formatted write was not verified. Do not repeat automatically.');
        }
        record.after = fullText(record.element);
        return {token: snapshot.token, document: performance.timeOrigin, full: record.after, text, originalFull: record.full, rich: !isPlain(record.element), background};
    }
    function restore(snapshot: {token: string; document: number}) {
        const record = records.get(snapshot.token);
        if (!record || !record.after || snapshot.document !== performance.timeOrigin || focused() !== record.element || fullText(record.element) !== record.after) throw Error('Original target is no longer unchanged. Use the history copy instead.');
        if (isPlain(record.element)) {
            record.element.setRangeText(record.full, 0, record.element.value.length, 'end');
        } else {
            const range = document.createRange(); range.selectNodeContents(record.element);
            getSelection()!.removeAllRanges(); getSelection()!.addRange(range);
            if (!document.execCommand('insertHTML', false, record.full)) throw Error('Restore rejected');
        }
        record.element.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertReplacementText'}));
        if (fullText(record.element) !== record.full) throw Error('Restore was not verified');
        records.delete(snapshot.token);
        return {restored: true};
    }
    chrome.runtime.onMessage.addListener((request, _sender, reply) => {
        try {
            let value;
            if (request.op === 'capture') value = capture();
            else if (request.op === 'apply') value = apply(request.snapshot, request.text);
            else if (request.op === 'restore') value = restore(request.snapshot);
            else throw Error('Unknown operation');
            reply({ok: true, value});
        } catch (error) { reply({ok: false, error: String(error)}); }
        return false;
    });
})();
