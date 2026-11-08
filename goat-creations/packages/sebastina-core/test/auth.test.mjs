// Customer token checks.
import assert from 'node:assert/strict';
import { issueCustomerToken, verifyCustomerToken } from '../dist/server.js';

const secret = 'x'.repeat(40);
const token = issueCustomerToken('goat-pro', secret);
assert.equal(verifyCustomerToken(token, secret), 'goat-pro');

// Editing the customer part (to bill someone else) breaks the signature.
const [, sig] = token.split('.');
const swapped = `${Buffer.from('goat-other').toString('base64url')}.${sig}`;
assert.equal(verifyCustomerToken(swapped, secret), null);
assert.equal(verifyCustomerToken(token, 'y'.repeat(40)), null);
assert.equal(verifyCustomerToken(undefined, secret), null);
assert.equal(verifyCustomerToken('a.b.c', secret), null);
assert.throws(() => issueCustomerToken('goat-pro', 'short'), /at least 32/);
console.log('PASS    customer tokens: valid accepted; edited, forged or wrong-secret rejected');
