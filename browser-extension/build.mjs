import { copyFileSync, mkdirSync } from 'node:fs';
mkdirSync('dist', { recursive: true });
for (const file of ['manifest.json', 'popup.html']) copyFileSync(file, `dist/${file}`);
