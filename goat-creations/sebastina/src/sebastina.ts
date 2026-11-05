import axios from 'axios';

interface GenerationConfig {
    prompt: string;
    negativePrompt?: string;
    steps?: number;
    width?: number;
    height?: number;
    isMotion?: boolean;
}

export class SEBastinaEngine {
    private apiBaseUrl: string;

    constructor(apiBaseUrl: string = 'http://127.0.0.1:7860') {
        this.apiBaseUrl = apiBaseUrl;
    }

    /**
     * Core processing method for SEBastina pipeline assets
     */
    async generateAsset(config: GenerationConfig): Promise<{ success: boolean; data?: string; error?: string }> {
        // Route dynamically if user flips the switch to MotionGOAT (AI Video)
        const endpoint = config.isMotion
            ? `${this.apiBaseUrl}/v1/video/generate`
            : `${this.apiBaseUrl}/sdapi/v1/txt2img`;

        const payload = {
            prompt: config.prompt,
            negative_prompt: config.negativePrompt || 'blurry, low quality, distorted, watermark',
            steps: config.steps || 25,
            width: config.width || 512,
            height: config.height || 512,
        };

        try {
            console.log(`[SEBastina] Initiating asset creation pipeline... Mode: ${config.isMotion ? 'MotionGOAT' : 'ImageGOAT'}`);
            const response = await axios.post(endpoint, payload, { timeout: 60000 });

            if (response.data && response.data.images && response.data.images.length > 0) {
                // Returns raw generated base64 image strings or frame URIs
                return { success: true, data: response.data.images[0] };
            }

            return { success: false, error: 'Engine returned an empty generation response array.' };
        } catch (error: any) {
            return { success: false, error: error.message };
        }
    }
}
