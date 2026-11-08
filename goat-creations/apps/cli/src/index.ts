// Load settings (API keys, backend URL, customer ID) from a local .env file.
import 'dotenv/config';
import { SEBastinaEngine, lagoCreditGate, LagoBilling } from 'sebastina-core/server';
import * as readline from 'readline';

const env = process.env;

const sebastina = new SEBastinaEngine({
    apiBaseUrl: env.AI_BACKEND_URL || 'https://api.muapi.ai',
    apiKey: env.MUAPI_API_KEY,
    imageModel: env.SEBASTINA_IMAGE_MODEL,
    videoModel: env.SEBASTINA_VIDEO_MODEL,
});

// Billing is on unless explicitly switched off (for local testing only).
const billingOn = (env.SEBASTINA_BILLING || 'on').toLowerCase() !== 'off';
if (billingOn) {
    try {
        sebastina.use(
            lagoCreditGate(LagoBilling.fromEnv(env), {
                image: Number(env.CREDITS_PER_IMAGE || 1),
                video: Number(env.CREDITS_PER_VIDEO || 1),
            }),
        );
    } catch (error: any) {
        console.error(`[SEBastina] Billing setup failed: ${error.message}`);
        console.error('Set LAGO_API_KEY in .env, or SEBASTINA_BILLING=off for local testing.');
        process.exit(1);
    }
}

let customerId = env.SEBASTINA_CUSTOMER_ID || '';

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function displayBanner() {
    console.clear();
    console.log('====================================================');
    console.log('                GOAT CREATIONS v1.0                 ');
    console.log('        --- Powered by SEBastina Engine ---         ');
    console.log('====================================================');
    console.log(' 1. ImageGOAT  - Open-Source Image Studio');
    console.log(' 2. MotionGOAT - Open-Source Video Studio');
    console.log(' 3. Exit Studio');
    console.log('====================================================');
    if (!billingOn) console.log(' (Billing is OFF: SEBASTINA_BILLING=off)');
}

/** Ask for the customer ID once, if billing needs it and .env doesn't set it. */
function ensureCustomerId(then: () => void) {
    if (!billingOn || customerId) return then();
    rl.question('Enter your GOAT CREATIONS customer ID: ', (answer) => {
        customerId = answer.trim();
        then();
    });
}

function runStudioMenu() {
    displayBanner();
    rl.question('Select a GOAT module to initiate: ', async (choice) => {
        if (choice === '1' || choice === '2') {
            const isVideo = choice === '2';

            rl.question(`\nEnter your prompt for ${isVideo ? 'MotionGOAT' : 'ImageGOAT'}: `, async (prompt) => {
                if (!prompt.trim()) {
                    console.log('Prompt cannot be empty.');
                    setTimeout(runStudioMenu, 1500);
                    return;
                }

                console.log('\nContacting SEBastina generation nodes...');
                const result = await sebastina.generateAsset({
                    prompt: prompt,
                    isMotion: isVideo,
                    customerId,
                });

                if (result.success) {
                    console.log('\n🎉 SUCCESS: SEBastina successfully rendered your asset!');
                    console.log(`Asset URL: ${result.data}`);
                } else {
                    console.log(`\n❌ ENGINE FAILURE: ${result.error}`);
                }

                rl.question('\nPress Enter to return to main dashboard...', () => {
                    runStudioMenu();
                });
            });
        } else if (choice === '3') {
            console.log('Shutting down GOAT CREATIONS workspace environments. Goodbye!');
            rl.close();
            process.exit(0);
        } else {
            console.log('Invalid assignment selection.');
            setTimeout(runStudioMenu, 1500);
        }
    });
}

// Ignition
ensureCustomerId(runStudioMenu);
