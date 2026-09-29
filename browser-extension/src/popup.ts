type PopupStatus = {desktopState: string; desktopError: string; error?: string};
const siteButton = document.getElementById('enable') as HTMLButtonElement;
const siteLabel = document.getElementById('site')!;
let siteOrigin: string | undefined;
const connectButton = document.getElementById('connect') as HTMLButtonElement;
const desktopLabel = document.getElementById('desktop')!;
const statusLabel = document.getElementById('status')!;
document.getElementById('version')!.textContent = `Extension ${chrome.runtime.getManifest().version}`;

async function refreshStatus(operation = 'status') {
    connectButton.hidden = true;
    try {
        const status: PopupStatus = await chrome.runtime.sendMessage({op: operation});
        if (status?.error) throw Error(status.error);
        if (!status || typeof status.desktopState !== 'string') throw Error('Reload the extension in chrome://extensions to finish the update.');
        desktopLabel.textContent = status.desktopState === 'connected' ? 'Desktop connected ✓' : `Desktop disconnected: ${status.desktopError || 'Start Desktop AI and reconnect.'}`;
        desktopLabel.classList.toggle('connected', status.desktopState === 'connected');
        connectButton.hidden = status.desktopState !== 'disconnected';
    } catch (error) {
        connectButton.hidden = false;
        desktopLabel.classList.remove('connected');
        desktopLabel.textContent = error instanceof Error ? error.message : String(error);
    }
}

async function refreshSite() {
    siteOrigin = undefined;
    siteButton.disabled = true;
    siteButton.hidden = true;
    try {
        const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
        const url = new URL(tab?.url || 'about:blank');
        if (url.protocol !== 'https:' && !(url.protocol === 'http:' && url.hostname === 'localhost')) {
            siteLabel.textContent = 'Open an HTTPS website to enable text editing.';
            return;
        }
        const origin = `${url.origin}/*`;
        const enabled = await chrome.permissions.contains({origins: [origin]});
        siteOrigin = origin;
        siteLabel.textContent = url.hostname;
        siteButton.textContent = enabled ? 'Access enabled ✓' : 'Enable this site';
        siteButton.disabled = enabled;
        siteButton.classList.toggle('enabled', enabled);
        siteButton.hidden = false;
    } catch (error) {
        siteLabel.textContent = error instanceof Error ? error.message : String(error);
    }
}

async function permit() {
    if (!siteOrigin) return;
    try {
        const accepted = await chrome.permissions.request({origins: [siteOrigin]});
        statusLabel.textContent = accepted ? 'Access enabled. Focus a message body or text field, then use the desktop hotkey.' : 'Permission not granted.';
        await refreshSite();
        await refreshStatus('permissions');
    } catch (error) {
        statusLabel.textContent = error instanceof Error ? error.message : String(error);
    }
}

siteButton.onclick = () => void permit();
connectButton.onclick = () => void refreshStatus('connect');
void refreshSite();
void refreshStatus();
