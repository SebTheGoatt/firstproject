/**
 * Print an access token for a customer: `npm run token -- <lago-customer-id>`.
 * Give the token to that customer; they paste it into the desktop or mobile app.
 */
import 'dotenv/config';
import { issueCustomerToken } from 'sebastina-core/server';

const customerId = process.argv[2];
if (!customerId) {
    console.error('Usage: npm run token -- <lago-customer-id>');
    process.exit(1);
}
try {
    console.log(issueCustomerToken(customerId, process.env.SEBASTINA_TOKEN_SECRET || ''));
} catch (error: any) {
    console.error(error.message);
    process.exit(1);
}
