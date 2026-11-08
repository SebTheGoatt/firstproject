/**
 * Lago billing connector for SEBastina.
 *
 * Uses Lago's official JavaScript SDK (`lago-javascript-client`, github.com/getlago).
 * Credits live in a Lago *wallet* (prepaid credits) attached to the customer;
 * the customer must also hold an *active subscription*.
 *
 * Settings (environment / .env, never committed):
 *   LAGO_API_KEY   API key from Lago > Developers > API keys
 *   LAGO_API_URL   API base URL; defaults to Lago Cloud. Self-hosted: http://your-host:3000/api/v1
 */
import { Client } from 'lago-javascript-client';

type LagoApi = ReturnType<typeof Client>;

const LAGO_CLOUD_URL = 'https://api.getlago.com/api/v1';

/** What the gate found for a customer. */
export interface CreditStatus {
    hasActiveSubscription: boolean;
    /** The customer's active wallet, if any. */
    walletId?: string;
    /** Credits left in that wallet (Lago returns them as a decimal string). */
    credits: number;
}

export class LagoBilling {
    private readonly api: LagoApi;

    constructor(apiKey: string, apiUrl: string = LAGO_CLOUD_URL) {
        if (!apiKey) {
            throw new Error('LAGO_API_KEY is missing. Add it to your .env file (never commit it).');
        }
        this.api = Client(apiKey, { baseUrl: apiUrl });
    }

    /** Build the connector from LAGO_API_KEY / LAGO_API_URL. */
    static fromEnv(env: NodeJS.ProcessEnv = process.env): LagoBilling {
        return new LagoBilling(env.LAGO_API_KEY ?? '', env.LAGO_API_URL || LAGO_CLOUD_URL);
    }

    /** True when the customer has at least one subscription in `active` status. */
    async hasActiveSubscription(customerId: string): Promise<boolean> {
        const { data } = await this.api.subscriptions.findAllSubscriptions({
            external_customer_id: customerId,
            'status[]': ['active'],
        });
        return data.subscriptions.some((s) => s.status === 'active');
    }

    /** Subscription + wallet check in one call. */
    async getCreditStatus(customerId: string): Promise<CreditStatus> {
        const [hasActiveSubscription, walletsResponse] = await Promise.all([
            this.hasActiveSubscription(customerId),
            this.api.wallets.findAllWallets({ external_customer_id: customerId }),
        ]);
        const wallet = walletsResponse.data.wallets.find((w) => w.status === 'active');
        return {
            hasActiveSubscription,
            walletId: wallet?.lago_id,
            credits: wallet ? Number.parseFloat(wallet.credits_balance) || 0 : 0,
        };
    }

    /** Remove `credits` from the wallet right away (a "voided credits" transaction). */
    async debit(walletId: string, credits: number, label: string): Promise<void> {
        await this.api.walletTransactions.createWalletTransaction({
            wallet_transaction: { wallet_id: walletId, voided_credits: credits.toFixed(2), name: label },
        });
    }

    /** Give `credits` back as free credits (used when a paid generation fails). */
    async refund(walletId: string, credits: number, label: string): Promise<void> {
        await this.api.walletTransactions.createWalletTransaction({
            wallet_transaction: { wallet_id: walletId, granted_credits: credits.toFixed(2), name: label },
        });
    }
}
