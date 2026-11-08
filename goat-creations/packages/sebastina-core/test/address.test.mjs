// Address check used by the apps' settings screens: what works on mobile data.
import assert from 'node:assert/strict';
import { checkAddress } from '../dist/index.js';

assert.deepEqual(checkAddress('https://abc-def.trycloudflare.com'), { reach: 'internet' });
assert.deepEqual(checkAddress('https://goat.example.com/'), { reach: 'internet' });
assert.match(checkAddress('http://goat.example.com').issue, /https:\/\//);
assert.match(checkAddress('http://203.0.113.9:8787').issue, /https:\/\//);
console.log('PASS 1  internet addresses work on mobile data, but only over https (the token stays encrypted)');

for (const a of ['http://192.168.1.20:8188', 'http://10.0.0.5:8188', 'http://172.20.1.1:8188', 'http://localhost:8787', 'http://gaming-pc.local:8188']) {
  assert.deepEqual(checkAddress(a), { reach: 'wifi' }, a);
}
assert.deepEqual(checkAddress('http://172.32.0.1:8188').reach, 'internet');
console.log('PASS 2  home network addresses are allowed over http but marked "same Wi-Fi only"');

assert.deepEqual(checkAddress('http://100.101.102.103:8188'), { reach: 'tailnet' });
assert.deepEqual(checkAddress('https://gaming-pc.tail1234.ts.net'), { reach: 'tailnet' });
console.log('PASS 3  Tailscale addresses (100.64-127.x, *.ts.net) work on mobile data');

assert.match(checkAddress('goat server').issue, /not valid/);
assert.match(checkAddress('ftp://x.example.com').issue, /https:\/\//);
console.log('PASS 4  typos and other schemes get a plain explanation');

console.log('\nAll address checks passed.');
