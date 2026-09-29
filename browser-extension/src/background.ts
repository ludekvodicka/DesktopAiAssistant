let nativePort: chrome.runtime.Port | undefined;
let connectionReady: Promise<void> | undefined;
let desktopState: 'disconnected' | 'connecting' | 'connected' = 'disconnected';
let desktopError = '';
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let retryCount = 0;
let sitesUpdate = Promise.resolve();

function registerSites() {
    sitesUpdate = sitesUpdate.catch(() => {}).then(async () => {
        const {origins = []} = await chrome.permissions.getAll();
        const existing = await chrome.scripting.getRegisteredContentScripts({ids: ['editors']});
        if (!origins.length) {
            if (existing.length) await chrome.scripting.unregisterContentScripts({ids: ['editors']});
        } else if (existing.length) {
            await chrome.scripting.updateContentScripts([{id: 'editors', js: ['content.js'], matches: origins, runAt: 'document_idle'}]);
        } else {
            await chrome.scripting.registerContentScripts([{id: 'editors', js: ['content.js'], matches: origins, runAt: 'document_idle'}]);
        }
    });
    return sitesUpdate;
}

class BrowserActionError extends Error {
    code: string;
    constructor(code: string, message: string) {
        super(message);
        this.code = code;
    }
}

async function forwardRequest(port: chrome.runtime.Port, request: {id: string; op: string; snapshot?: {tabId: number; windowId: number}}) {
    try {
        const window = await chrome.windows.getLastFocused();
        const savedTarget = request.op === 'apply' && request.snapshot;
        if (!savedTarget && !window.focused) throw new BrowserActionError('browser_not_focused', 'Focus the Chrome or Edge window containing your text.');
        const tab = savedTarget ? await chrome.tabs.get(savedTarget.tabId) : (await chrome.tabs.query({active: true, windowId: window.id}))[0];
        if (!tab?.id) throw new BrowserActionError('no_active_tab', 'No active browser tab.');
        const windowId = savedTarget ? tab.windowId : window.id;
        if (request.snapshot && (request.snapshot.tabId !== tab.id || request.snapshot.windowId !== windowId)) throw new BrowserActionError('target_changed', 'Browser tab changed. Result kept in History.');
        if (request.op === 'capture') {
            const url = new URL(tab.url || 'about:blank');
            if (url.protocol !== 'https:' && !(url.protocol === 'http:' && url.hostname === 'localhost')) throw new BrowserActionError('unsupported_page', 'This page does not support text editing. Open an enabled HTTPS website.');
            if (!await chrome.permissions.contains({origins: [`${url.origin}/*`]})) throw new BrowserActionError('site_permission_missing', `Access to ${url.hostname} is disabled. Enable this site in the Desktop AI extension.`);
            // Permission may have been granted after this tab loaded. Injection is idempotent.
            await chrome.scripting.executeScript({target: {tabId: tab.id, frameIds: [0]}, files: ['content.js']});
        }
        const response = await chrome.tabs.sendMessage(tab.id, request, {frameId: 0});
        if (!response?.ok) throw new BrowserActionError('editor_error', response?.error || 'The editor did not respond. Reload the page and focus its text field.');
        port.postMessage({id: request.id, ok: true, value: {...response.value, tabId: tab.id, windowId}});
    } catch (error) {
        try {
            port.postMessage({id: request.id, ok: false, code: error instanceof BrowserActionError ? error.code : 'browser_error', error: error instanceof Error ? error.message : String(error)});
        } catch { /* The desktop may have closed while the browser request was running. */ }
    }
}

function connectDesktop(): Promise<void> {
    if (nativePort) return connectionReady || Promise.resolve();
    if (retryTimer) clearTimeout(retryTimer);
    retryTimer = undefined;
    desktopState = 'connecting';
    desktopError = '';
    let settle: () => void;
    connectionReady = new Promise<void>(resolve => settle = resolve);
    const ready = connectionReady;
    let port: chrome.runtime.Port;
    try {
        port = chrome.runtime.connectNative('com.desktopai.assistant');
    } catch (error) {
        desktopState = 'disconnected';
        desktopError = String(error);
        settle!();
        return ready;
    }
    nativePort = port;
    const timeout = setTimeout(() => {
        if (nativePort !== port || desktopState === 'connected') return;
        nativePort = undefined;
        desktopState = 'disconnected';
        desktopError = 'Desktop handshake timed out. Restart Desktop AI and reconnect.';
        port.disconnect();
        settle();
    }, 3000);
    port.onDisconnect.addListener(() => {
        const error = chrome.runtime.lastError?.message;
        clearTimeout(timeout);
        settle();
        // A late disconnect from a replaced port must not clear its replacement.
        if (nativePort !== port) return;
        nativePort = undefined;
        desktopState = 'disconnected';
        desktopError = error || 'Desktop app disconnected. Start or restart Desktop AI.';
        if (retryCount < 3)
            retryTimer = setTimeout(() => { retryCount++; void connectDesktop(); }, 500 * 2 ** retryCount);
    });
    port.onMessage.addListener(request => {
        if (nativePort !== port) return;
        if (request.op === 'hello') {
            clearTimeout(timeout);
            desktopState = 'connected';
            desktopError = '';
            retryCount = 0;
            settle();
        } else {
            void forwardRequest(port, request);
        }
    });
    return ready;
}

async function popupStatus() {
    await connectDesktop();
    return {desktopState, desktopError};
}

chrome.runtime.onMessage.addListener((request, _sender, reply) => {
    if (request.op === 'permissions') {
        registerSites().then(popupStatus).then(reply, error => reply({error: String(error)}));
        return true;
    } else if (request.op === 'connect') {
        const previous = nativePort;
        nativePort = undefined;
        previous?.disconnect();
        retryCount = 0;
        popupStatus().then(reply, error => reply({error: String(error)}));
        return true;
    } else if (request.op === 'status') {
        popupStatus().then(reply, error => reply({error: String(error)}));
        return true;
    }
    return false;
});
chrome.runtime.onInstalled.addListener(() => { void registerSites().catch(error => { desktopError = String(error); }); void connectDesktop(); });
chrome.runtime.onStartup.addListener(() => { void connectDesktop(); });
chrome.permissions.onAdded.addListener(() => { void registerSites().catch(error => { desktopError = String(error); }); });
chrome.permissions.onRemoved.addListener(() => { void registerSites().catch(error => { desktopError = String(error); }); });
void connectDesktop();
