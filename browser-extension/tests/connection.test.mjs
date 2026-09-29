import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {JSDOM} from 'jsdom';

function event() {
    const listeners = [];
    return {addListener: listener => listeners.push(listener), emit: (...args) => listeners.map(listener => listener(...args))};
}
const tick = () => new Promise(resolve => setImmediate(resolve));

function worker() {
    const ports = [], injected = [], timers = new Map();
    let serial = 0, permitted = true, registrations = [];
    const chrome = {
        runtime: {onMessage: event(), onInstalled: event(), onStartup: event(), connectNative: () => {
            const port = {onMessage: event(), onDisconnect: event(), replies: [], postMessage(value) { this.replies.push(value); }, disconnect() {}};
            ports.push(port);
            return port;
        }},
        permissions: {getAll: async () => ({origins: permitted ? ['https://mail.google.com/*'] : []}), contains: async () => permitted, onAdded: event(), onRemoved: event()},
        scripting: {
            getRegisteredContentScripts: async () => registrations,
            registerContentScripts: async value => { assert.equal(registrations.length, 0); registrations = value; },
            updateContentScripts: async value => { registrations = value; },
            unregisterContentScripts: async () => { registrations = []; },
            executeScript: async value => { injected.push(value); },
        },
        windows: {getLastFocused: async () => ({id: 1, focused: true})},
        tabs: {query: async () => [{id: 2, url: 'https://mail.google.com/mail/u/0/'}], sendMessage: async () => ({ok: true, value: {text: 'draft'}})},
    };
    vm.runInNewContext(readFileSync(new URL('../dist/background.js', import.meta.url), 'utf8'), {
        chrome, URL, setTimeout: callback => { const id = ++serial; timers.set(id, callback); return id; }, clearTimeout: id => timers.delete(id),
    });
    return {ports, injected, chrome, timers, permit: value => permitted = value,
        message: op => new Promise(resolve => chrome.runtime.onMessage.emit({op}, {}, resolve))};
}

test('connection is confirmed by a host handshake and stale disconnects do not clear it', async () => {
    const w = worker();
    const first = w.ports[0];
    const state = w.message('status');
    let settled = false;
    state.then(() => settled = true);
    await tick();
    assert.equal(settled, false);
    first.onMessage.emit({op: 'hello', version: 'test'});
    assert.equal((await state).desktopState, 'connected');
    const reconnect = w.message('connect');
    const second = w.ports[1];
    second.onMessage.emit({op: 'hello'});
    first.onDisconnect.emit();
    assert.equal((await reconnect).desktopState, 'connected');
    assert.equal((await w.message('status')).desktopState, 'connected');
});

test('an already open permitted Gmail tab is injected before capture; denied access is explicit', async () => {
    const w = worker();
    const port = w.ports[0];
    port.onMessage.emit({op: 'hello'});
    port.onMessage.emit({id: 'one', op: 'capture'});
    await tick();
    assert.equal(w.injected.length, 1);
    assert.equal(w.injected[0].target.tabId, 2);
    assert.equal(port.replies[0].value.text, 'draft');
    w.permit(false);
    port.onMessage.emit({id: 'two', op: 'capture'});
    await tick();
    assert.equal(w.injected.length, 1);
    assert.equal(port.replies[1].code, 'site_permission_missing');
});

test('permission registration is serialized and popup receives real native-host failures', async () => {
    const w = worker();
    w.ports[0].onMessage.emit({op: 'hello'});
    await Promise.all([w.message('permissions'), w.message('permissions')]);
    w.chrome.runtime.lastError = {message: 'Native host has exited.'};
    w.ports[0].onDisconnect.emit();
    const status = w.message('status');
    w.ports[1].onDisconnect.emit();
    const reply = await status;
    assert.equal(reply.desktopState, 'disconnected');
    assert.equal(reply.desktopError, 'Native host has exited.');
});

test('apply addresses the captured tab even when another window is active', async () => {
    const w = worker();
    const sent = [];
    w.chrome.windows.getLastFocused = async () => ({id: 9, focused: false});
    w.chrome.tabs.get = async id => ({id, windowId: 1});
    w.chrome.tabs.sendMessage = async (id, request) => { sent.push([id, request.op]); return {ok: true, value: {background: true}}; };
    const port = w.ports[0];
    port.onMessage.emit({op: 'hello'});
    port.onMessage.emit({id: 'apply', op: 'apply', snapshot: {tabId: 2, windowId: 1}});
    await tick();
    assert.deepEqual(sent, [[2, 'apply']]);
    assert.equal(port.replies[0].value.windowId, 1);
    assert.equal(port.replies[0].value.background, true);
    w.chrome.tabs.get = async id => ({id, windowId: 7});
    port.onMessage.emit({id: 'changed', op: 'apply', snapshot: {tabId: 2, windowId: 1}});
    await tick();
    assert.equal(port.replies[1].code, 'target_changed');
    assert.equal(sent.length, 1);
});

test('popup uses the current site permission and only offers reconnect when disconnected', async () => {
    const html = readFileSync(new URL('../popup.html', import.meta.url), 'utf8');
    for (const [url, permitted, connected] of [
        ['https://mail.google.com/mail/u/0/', true, true],
        ['https://mail.google.com/mail/u/0/', false, false],
        ['https://example.com/editor', false, true],
        ['https://example.com/editor', true, false],
        ['chrome://extensions/', false, true],
    ]) {
        let enabled = permitted;
        const requested = [];
        const dom = new JSDOM(html, {runScripts: 'outside-only'});
        dom.window.chrome = {runtime: {
            getManifest: () => ({version: 'test'}),
            sendMessage: async () => ({desktopState: connected ? 'connected' : 'disconnected', desktopError: 'Host unavailable'}),
        }, tabs: {query: async () => [{url}]}, permissions: {
            contains: async ({origins}) => { assert.equal(origins[0], `${new URL(url).origin}/*`); return enabled; },
            request: async ({origins}) => { requested.push(origins[0]); enabled = true; return true; },
        }};
        dom.window.eval(readFileSync(new URL('../dist/popup.js', import.meta.url), 'utf8'));
        await tick();
        const button = dom.window.document.getElementById('enable');
        assert.equal(dom.window.document.querySelector('input'), null);
        assert.equal(dom.window.document.getElementById('gmail'), null);
        if (url.startsWith('https:')) {
            assert.equal(button.hidden, false);
            assert.equal(button.textContent, permitted ? 'Access enabled ✓' : 'Enable this site');
            assert.equal(button.disabled, permitted);
            if (!permitted) {
                button.click();
                await tick();
                assert.deepEqual(requested, [`${new URL(url).origin}/*`]);
                assert.equal(button.textContent, 'Access enabled ✓');
                assert.equal(button.disabled, true);
            }
        } else {
            assert.equal(button.hidden, true);
            assert.equal(button.disabled, true);
            assert.deepEqual(requested, []);
        }
        assert.equal(dom.window.document.getElementById('connect').hidden, connected);
        assert.equal(dom.window.document.getElementById('desktop').textContent, connected ? 'Desktop connected ✓' : 'Desktop disconnected: Host unavailable');
        dom.window.close();
    }
});
