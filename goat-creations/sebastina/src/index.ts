// Load AI_BACKEND_URL (and any other settings) from a local .env file.
import 'dotenv/config';
import { SEBastinaEngine } from './sebastina.js';
import * as readline from 'readline';

const sebastina = new SEBastinaEngine(process.env.AI_BACKEND_URL || 'http://127.0.0.1:7860');

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
                    isMotion: isVideo
                });

                if (result.success) {
                    console.log('\n🎉 SUCCESS: SEBastina successfully rendered your asset!');
                    console.log(`Asset Byte Stream Data Payload: ${result.data?.substring(0, 60)}... [Truncated]`);
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
runStudioMenu();
