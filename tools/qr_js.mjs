// Companion to tests/test_qr.py: prints the QR matrix web/js/qr.js makes for each line of stdin (as JSON).
import { readFileSync } from 'node:fs';
import { qrMatrix } from '../web/js/qr.js';

const texts = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(texts.map((t) => qrMatrix(t).map((row) => row.map((c) => (c ? 1 : 0)).join('')))));
