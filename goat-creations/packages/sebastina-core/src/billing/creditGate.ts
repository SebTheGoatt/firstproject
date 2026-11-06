import type { GenerationMiddleware, GenerationResult } from '../engine.js';
import { describeError } from '../engine.js';
import type { LagoBilling } from './lago.js';

/**
 * Lago credit gate. Before ImageGOAT or MotionGOAT runs, it checks that the
 * customer has an active subscription and enough credits, takes the credits,
 * then lets the request through. If generation fails, the credits are given back.
 *
 * Note: check-then-debit is two calls, so two requests at the exact same moment
 * could both pass on the last credit. Fine for one user at a terminal; a web
 * service with many users should move this into a server with a per-customer lock.
 */
export function lagoCreditGate(
    billing: LagoBilling,
    cost: { image: number; video: number } = { image: 1, video: 1 },
): GenerationMiddleware {
    return async (config, next) => {
        const customerId = config.customerId?.trim();
        if (!customerId) {
            return { success: false, error: 'No customer ID. Set SEBASTINA_CUSTOMER_ID or enter it when asked.' };
        }
        const credits = config.isMotion ? cost.video : cost.image;
        const mode = config.isMotion ? 'MotionGOAT' : 'ImageGOAT';

        const status = await billing.getCreditStatus(customerId);
        if (!status.hasActiveSubscription) {
            return { success: false, error: 'No active subscription for this account.' };
        }
        if (!status.walletId || status.credits < credits) {
            return { success: false, error: `Not enough credits: ${status.credits} left, ${mode} needs ${credits}.` };
        }

        await billing.debit(status.walletId, credits, `${mode} generation`);
        console.log(`[SEBastina] ${credits} credit(s) used. ${status.credits - credits} left.`);

        let result: GenerationResult;
        try {
            result = await next();
        } catch (error) {
            result = { success: false, error: describeError(error) };
        }
        if (!result.success) {
            try {
                await billing.refund(status.walletId, credits, `${mode} refund (generation failed)`);
                result = { ...result, error: `${result.error} (${credits} credit(s) refunded)` };
            } catch (refundError) {
                result = {
                    ...result,
                    error: `${result.error} (refund of ${credits} credit(s) failed: ${describeError(refundError)}; please refund by hand in Lago)`,
                };
            }
        }
        return result;
    };
}

