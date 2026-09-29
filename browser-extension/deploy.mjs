import {copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

export function deployExtension(source, target) {
    const manifestPath = resolve(target, 'manifest.json');
    const previous = existsSync(manifestPath) ? JSON.parse(readFileSync(manifestPath, 'utf8')) : null;
    const manifest = JSON.parse(readFileSync(resolve(source, 'manifest.json'), 'utf8'));
    // Reloading an installed unpacked extension must retain its original identity.
    if (previous && !previous.key) delete manifest.key;
    else if (previous?.key) manifest.key = previous.key;
    mkdirSync(target, {recursive: true});
    for (const file of ['background.js', 'content.js', 'popup.js', 'popup.html'])
        copyFileSync(resolve(source, file), resolve(target, file));
    writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    if (!process.argv[2]) throw new Error('Pass the extension destination directory');
    deployExtension(fileURLToPath(new URL('./dist', import.meta.url)), resolve(process.argv[2]));
}
