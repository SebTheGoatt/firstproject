/**
 * Customer access tokens for the SEBastina server (server-side only).
 *
 * The desktop and mobile apps never hold the MuAPI or Lago keys; they send a
 * customer token instead. A token is the Lago customer ID plus an HMAC
 * signature made with SEBASTINA_TOKEN_SECRET, so it can't be forged or edited
 * to bill someone else. Issue one per customer with `npm run token -- <customerId>`
 * in apps/server.
 */
import { createHmac, timingSafeEqual } from 'node:crypto';

const MIN_SECRET_LENGTH = 32;

function sign(customerId: string, secret: string): string {
    return createHmac('sha256', secret).update(`sebastina:v1:${customerId}`).digest('base64url');
}

function assertSecret(secret: string): void {
    if (!secret || secret.length < MIN_SECRET_LENGTH) {
        throw new Error(`SEBASTINA_TOKEN_SECRET must be at least ${MIN_SECRET_LENGTH} characters.`);
    }
}

export function issueCustomerToken(customerId: string, secret: string): string {
    assertSecret(secret);
    if (!customerId.trim()) throw new Error('Customer ID is empty.');
    return `${Buffer.from(customerId, 'utf8').toString('base64url')}.${sign(customerId, secret)}`;
}

/** The customer ID inside a valid token, or null if the token is missing, edited or forged. */
export function verifyCustomerToken(token: string | undefined, secret: string): string | null {
    assertSecret(secret);
    const [encodedId, signature, extra] = (token ?? '').split('.');
    if (!encodedId || !signature || extra !== undefined) return null;
    const customerId = Buffer.from(encodedId, 'base64url').toString('utf8');
    const expected = Buffer.from(sign(customerId, secret));
    const given = Buffer.from(signature);
    return expected.length === given.length && timingSafeEqual(expected, given) ? customerId : null;
}
