/**
 * GOAT Skills: one-tap creative recipes, and photo tools.
 *
 * Inspired by the "Skill" workflows in MuAPI's ComfyUI pack (SamurAIGPT/muapi-comfyui,
 * MIT), rebuilt as fill-in templates: where theirs are fixed examples ("INSANE
 * RESULT!"), ours take the user's own subject and words. Each Skill is plain data
 * (no functions) so the same file drives the apps, the server and the ComfyUI nodes.
 *
 * A Skill runs its steps in order. A step's input picture is the user's photo
 * (`from: "photo"`) or the previous step's result (`from: "previous"`).
 */
import { findModel, isVideoModel } from './models.js';

export interface SkillField {
    id: string;
    label: string;
    placeholder: string;
    /** Used when the field is left empty. Empty string = the field is required. */
    fallback: string;
}

export interface SkillStep {
    /** Model endpoint from models.ts. */
    model: string;
    /** Prompt template; {fieldId} is replaced by the user's text. */
    prompt: string;
    aspectRatio?: string;
    duration?: number;
    resolution?: string;
    /** Where this step's input picture comes from (photo models only). */
    from?: 'photo' | 'previous';
}

export interface Skill {
    id: string;
    name: string;
    description: string;
    /** "create" = Skills tab; "photo" = photo tools. */
    category: 'create' | 'photo';
    needsPhoto: boolean;
    fields: readonly SkillField[];
    steps: readonly SkillStep[];
}

export const SKILLS: readonly Skill[] = [
    // ---------------------------------------------------------- create
    {
        id: 'youtube-thumbnail', name: 'YouTube Thumbnail', category: 'create', needsPhoto: false,
        description: 'Bold 16:9 thumbnail with your headline in big readable letters.',
        fields: [
            { id: 'subject', label: 'What it shows', placeholder: 'a goat on a mountain peak at sunrise', fallback: '' },
            { id: 'headline', label: 'Headline text', placeholder: 'GREATEST OF ALL TIME', fallback: '' },
        ],
        steps: [{
            model: 'gpt-image-2-text-to-image', aspectRatio: '16:9',
            prompt: 'YouTube thumbnail, 16:9. {subject}, expressive and eye-catching, placed on the left. Large readable headline on the right reading "{headline}" in thick bold sans-serif with a dark outline. High contrast, vivid colors, dark vignette, clean composition.',
        }],
    },
    {
        id: 'instagram-post', name: 'Instagram Post', category: 'create', needsPhoto: false,
        description: 'Square, scroll-stopping post with room for a caption.',
        fields: [
            { id: 'subject', label: 'Scene', placeholder: 'fresh coffee and a notebook on a linen table', fallback: '' },
            { id: 'mood', label: 'Mood', placeholder: 'warm morning light', fallback: 'soft natural light' },
        ],
        steps: [{
            model: 'nano-banana-pro', aspectRatio: '1:1',
            prompt: 'Aesthetic Instagram post, square 1:1. {subject}. {mood}. Styled, uncluttered composition with breathing room for a caption, rich detail, magazine quality.',
        }],
    },
    {
        id: 'ad-creative', name: 'Ad Creative', category: 'create', needsPhoto: false,
        description: '4:5 product ad with space reserved for your headline.',
        fields: [
            { id: 'product', label: 'Product', placeholder: 'a matte black water bottle', fallback: '' },
            { id: 'headline', label: 'Headline', placeholder: 'STAY COLD 24H', fallback: '' },
        ],
        steps: [{
            model: 'nano-banana-pro', aspectRatio: '4:5',
            prompt: 'High-converting ad creative, 4:5 portrait. Product hero shot of {product} on a premium surface, crisp studio lighting, subtle reflections, shallow depth of field. Clean headline area at the top reading "{headline}".',
        }],
    },
    {
        id: 'logo', name: 'Logo', category: 'create', needsPhoto: false,
        description: 'Minimal, flat logo on white, centered and ready to use.',
        fields: [
            { id: 'name', label: 'Brand name', placeholder: 'GOAT CREATIONS', fallback: '' },
            { id: 'idea', label: 'Idea or style', placeholder: 'a mountain goat horn, gold', fallback: 'simple geometric mark' },
        ],
        steps: [{
            model: 'flux-2-pro', aspectRatio: '1:1',
            prompt: "Minimalist logo for a brand named '{name}'. {idea}. Flat vector style, one or two solid colors, clean geometry, perfectly centered on a plain white background, crisp edges, no mockup.",
        }],
    },
    {
        id: 'blog-header', name: 'Blog Header', category: 'create', needsPhoto: false,
        description: 'Wide editorial header image for an article or newsletter.',
        fields: [{ id: 'topic', label: 'Article topic', placeholder: 'how to start a small business', fallback: '' }],
        steps: [{
            model: 'nano-banana-pro', aspectRatio: '16:9',
            prompt: 'Editorial blog header illustration, wide 16:9, about: {topic}. Modern, clean, conceptual, balanced negative space, cohesive color palette, no text.',
        }],
    },
    {
        id: 'drone-video', name: 'Drone Shot Video', category: 'create', needsPhoto: false,
        description: 'Sweeping 5-second aerial video of any place you describe.',
        fields: [{ id: 'place', label: 'Place', placeholder: 'a misty mountain valley at dawn', fallback: '' }],
        steps: [{
            model: 'seedance-lite-t2v', aspectRatio: '16:9', duration: 5, resolution: '480p',
            prompt: 'Cinematic aerial drone shot slowly gliding forward over {place}, smooth stabilized motion, golden light, sweeping reveal, high detail.',
        }],
    },
    {
        id: 'action-figure', name: 'Action Figure', category: 'create', needsPhoto: true,
        description: 'Turn a person in your photo into a boxed collectible figure.',
        fields: [{ id: 'title', label: 'Name on the box', placeholder: 'THE GOAT', fallback: 'LIMITED EDITION' }],
        steps: [{
            model: 'nano-banana-edit', from: 'photo',
            prompt: 'Turn the person in this photo into a 6-inch collectible action figure inside a blister-pack box with the title "{title}" printed on the card, small accessories beside the figure. Keep the face exactly recognizable. Studio product-shot lighting.',
        }],
    },
    {
        id: 'product-ad-video', name: 'Product Ad Video', category: 'create', needsPhoto: true,
        description: 'Photo of a product in, polished commercial clip out (2 steps).',
        fields: [{ id: 'setting', label: 'Setting', placeholder: 'polished black stone with gold rim light', fallback: 'polished dark surface with dramatic rim light' }],
        steps: [
            {
                model: 'flux-2-pro-edit', from: 'photo',
                prompt: 'Re-stage this exact product on {setting}. Premium studio commercial look, keep the product shape, labels and colors unchanged.',
            },
            {
                model: 'wan2.5-image-to-video', from: 'previous', duration: 5, resolution: '720p',
                prompt: 'High-end product commercial: slow smooth camera arc around the product, soft particles drifting, premium lighting, no text.',
            },
        ],
    },

    // ---------------------------------------------------------- photo tools
    {
        id: 'animate-photo', name: 'Animate Photo', category: 'photo', needsPhoto: true,
        description: 'Bring a still photo to life as a 5-second video.',
        fields: [{ id: 'motion', label: 'What should move', placeholder: 'hair blowing in the wind, slow zoom in', fallback: 'gentle natural motion, slow cinematic push-in' }],
        steps: [{ model: 'seedance-lite-i2v', from: 'photo', duration: 5, resolution: '480p', prompt: '{motion}' }],
    },
    {
        id: 'restyle-photo', name: 'Edit with Words', category: 'photo', needsPhoto: true,
        description: 'Describe a change and the photo is edited to match.',
        fields: [{ id: 'change', label: 'Change', placeholder: 'make it a snowy winter evening', fallback: '' }],
        steps: [{ model: 'nano-banana-edit', from: 'photo', prompt: '{change}. Keep everything else in the photo the same.' }],
    },
    {
        id: 'upscale-photo', name: 'Upscale', category: 'photo', needsPhoto: true,
        description: 'Make a photo bigger and sharper.',
        fields: [],
        steps: [{ model: 'ai-image-upscale', from: 'photo', prompt: '' }],
    },
    {
        id: 'remove-background', name: 'Remove Background', category: 'photo', needsPhoto: true,
        description: 'Cut out the subject on a transparent background.',
        fields: [],
        steps: [{ model: 'ai-background-remover', from: 'photo', prompt: '' }],
    },
];

export function findSkill(id: string | undefined): Skill | undefined {
    return SKILLS.find((s) => s.id === id);
}

/** Fill a template's {fields}; empty fields use their fallback. Returns null + the missing field if required text is absent. */
export function renderPrompt(
    template: string,
    skill: Skill,
    inputs: Record<string, string | undefined>,
): { prompt: string; missing?: undefined } | { prompt?: undefined; missing: SkillField } {
    for (const field of skill.fields) {
        const value = (inputs[field.id] ?? '').trim();
        if (!value && !field.fallback && template.includes(`{${field.id}}`)) return { missing: field };
    }
    const prompt = template.replace(/\{([a-z_]+)\}/gi, (_, id: string) => {
        const field = skill.fields.find((f) => f.id === id);
        const value = (inputs[id] ?? '').trim().slice(0, 600);
        return value || field?.fallback || '';
    });
    return { prompt };
}

/** Output of a Skill: image or video (from its last step). */
export function skillOutput(skill: Skill): 'image' | 'video' {
    const last = findModel(skill.steps[skill.steps.length - 1].model);
    return last && isVideoModel(last) ? 'video' : 'image';
}

/** Credits a Skill costs: each image step costs `image`, each video step `video`. */
export function skillCredits(skill: Skill, cost: { image: number; video: number }): number {
    return skill.steps.reduce((sum, step) => {
        const spec = findModel(step.model);
        return sum + (spec && isVideoModel(spec) ? cost.video : cost.image);
    }, 0);
}
