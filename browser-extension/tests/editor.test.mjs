import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';

function editor(html = '<div contenteditable="true" role="textbox" tabindex="0">Hello <b>world</b><br><a href="https://example.test">link</a><div class="gmail_signature">signature</div></div>') {
    const dom = new JSDOM(html, {url: 'https://mail.google.com/mail/u/0/', runScripts: 'outside-only', pretendToBeVisual: true});
    const w = dom.window;
    let listener;
    w.chrome = {runtime: {onMessage: {addListener: fn => listener = fn}}};
    w.document.hasFocus = () => true;
    w.document.execCommand = (command, _, html) => {
        assert.equal(command, 'insertHTML');
        const range = w.getSelection().getRangeAt(0);
        range.deleteContents();
        range.insertNode(range.createContextualFragment(html));
        return true;
    };
    const field = w.document.querySelector('[contenteditable],input,textarea');
    field.focus();
    if (field.hasAttribute('contenteditable')) {
        const range = w.document.createRange(); range.setStart(field.firstChild, 0); range.collapse(true);
        w.getSelection().addRange(range);
    }
    w.eval(readFileSync(new URL('../dist/content.js', import.meta.url), 'utf8'));
    const request = value => { let reply; listener(value, {}, v => reply = v); return reply; };
    return {w, field, request};
}

test('rich text keeps styles, link attributes, signature and restoration', () => {
    const {field, request} = editor();
    const before = field.innerHTML;
    const captured = request({op: 'capture'});
    assert.equal(captured.ok, true);
    const result = request({op: 'apply', snapshot: captured.value, text: captured.value.text.replace('Hello', 'Ahoj').replace('world', 'světe')});
    assert.equal(result.ok, true, result.error);
    assert.equal(field.querySelector('b').textContent, 'světe');
    assert.equal(field.querySelector('a').getAttribute('href'), 'https://example.test');
    assert.equal(field.querySelector('.gmail_signature').textContent, 'signature');
    assert.equal(request({op: 'restore', snapshot: result.value}).ok, true);
    assert.equal(field.innerHTML, before);
});

test('changed editor is not overwritten', () => {
    const {field, request} = editor();
    const captured = request({op: 'capture'}).value;
    field.firstChild.textContent = 'New draft';
    assert.equal(request({op: 'apply', snapshot: captured, text: captured.text}).ok, false);
    assert.equal(field.firstChild.textContent, 'New draft');
});

test('unknown formatting and executable HTML are rejected', () => {
    const {field, request} = editor();
    const before = field.innerHTML;
    const captured = request({op: 'capture'}).value;
    assert.equal(request({op: 'apply', snapshot: captured, text: '<script>alert(1)</script>'}).ok, false);
    assert.equal(field.innerHTML, before);
});

test('only selected text changes across formatting boundaries', () => {
    const {w, field, request} = editor('<div contenteditable="true" role="textbox" tabindex="0">Before <b>hello world</b> after</div>');
    const range = w.document.createRange();
    range.setStart(field.firstChild, 4);
    range.setEnd(field.querySelector('b').firstChild, 5);
    w.getSelection().removeAllRanges(); w.getSelection().addRange(range);
    const captured = request({op: 'capture'}).value;
    const result = request({op: 'apply', snapshot: captured, text: captured.text.replace('hello', 'ahoj')});
    assert.equal(result.ok, true, result.error);
    assert.equal(field.textContent, 'Before ahoj world after');
});

test('passwords and Gmail recipients are refused', () => {
    for (const html of ['<input type="password" value="secret">', '<input type="text" name="to" value="someone">']) {
        const {request} = editor(html);
        assert.equal(request({op: 'capture'}).ok, false);
    }
});

test('plain text is returned to the saved field without changing focus or selection elsewhere', () => {
    const {w, field, request} = editor('<input type="text" name="subjectbox" value="Hello world"><input id="other" value="Other work">');
    field.setSelectionRange(6, 11);
    const captured = request({op: 'capture'}).value;
    const other = w.document.getElementById('other');
    other.focus();
    other.setSelectionRange(1, 4);
    w.document.hasFocus = () => false;
    const result = request({op: 'apply', snapshot: captured, text: 'Earth'});
    assert.equal(result.ok, true, result.error);
    assert.equal(result.value.background, true);
    assert.equal(field.value, 'Hello Earth');
    assert.equal(other.value, 'Other work');
    assert.equal(w.document.activeElement, other);
    assert.equal(other.selectionStart, 1);
    assert.equal(other.selectionEnd, 4);
});

test('a changed, detached or repurposed original field is never overwritten', () => {
    for (const change of ['text', 'detach', 'readonly', 'type', 'location']) {
        const {w, field, request} = editor('<input type="text" name="subjectbox" value="Original">');
        const captured = request({op: 'capture'}).value;
        if (change === 'text') field.value = 'Newer draft';
        else if (change === 'detach') field.remove();
        else if (change === 'readonly') field.readOnly = true;
        else if (change === 'type') field.type = 'password';
        else if (change === 'location') w.history.pushState({}, '', '#different-draft');
        else throw Error('Unknown test change');
        assert.equal(request({op: 'apply', snapshot: captured, text: 'WRONG'}).ok, false);
        assert.notEqual(field.value, 'WRONG');
    }
});

test('rich text waits for its original field and then applies the original range', () => {
    const {w, field, request} = editor('<div contenteditable="true" role="textbox" tabindex="0">Before <b>hello world</b> after</div><input id="other">');
    const range = w.document.createRange();
    range.setStart(field.querySelector('b').firstChild, 0);
    range.setEnd(field.querySelector('b').firstChild, 5);
    w.getSelection().removeAllRanges(); w.getSelection().addRange(range);
    const captured = request({op: 'capture'}).value;
    w.document.getElementById('other').focus();
    assert.equal(request({op: 'apply', snapshot: captured, text: 'ahoj'}).value.deferred, true);
    assert.equal(field.textContent, 'Before hello world after');
    field.focus();
    w.getSelection().removeAllRanges();
    const result = request({op: 'apply', snapshot: captured, text: 'ahoj'});
    assert.equal(result.ok, true, result.error);
    assert.equal(field.textContent, 'Before ahoj world after');
});
