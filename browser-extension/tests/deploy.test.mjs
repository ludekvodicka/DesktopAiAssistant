import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {deployExtension} from '../deploy.mjs';

test('new installations get the key and upgrades retain their installed identity', () => {
    const target = mkdtempSync(join(tmpdir(), 'desktop-ai-extension-'));
    const source = fileURLToPath(new URL('../dist', import.meta.url));
    try {
        deployExtension(source, target);
        const file = join(target, 'manifest.json');
        const manifest = JSON.parse(readFileSync(file, 'utf8'));
        assert.ok(manifest.key);
        delete manifest.key;
        writeFileSync(file, JSON.stringify(manifest));
        deployExtension(source, target);
        assert.equal(JSON.parse(readFileSync(file, 'utf8')).key, undefined);
        manifest.key = 'previous-public-key';
        writeFileSync(file, JSON.stringify(manifest));
        deployExtension(source, target);
        assert.equal(JSON.parse(readFileSync(file, 'utf8')).key, 'previous-public-key');
    } finally {
        assert.equal(dirname(target), tmpdir());
        rmSync(target, {recursive: true});
    }
});
