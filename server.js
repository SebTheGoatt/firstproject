// ============================================
//  VetPath – Express Server
//  Proxies requests to Anthropic Claude API
// ============================================

require('dotenv').config();

const express   = require('express');
const cors      = require('cors');
const Anthropic = require('@anthropic-ai/sdk');
const path      = require('path');

const app  = express();
const PORT = process.env.PORT || 3000;

// ---- MIDDLEWARE ----
app.use(cors());
app.use(express.json({ limit: '1mb' }));
app.use(express.static(path.join(__dirname, 'public')));

// ---- ANTHROPIC CLIENT ----
const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

// ---- CHAT ENDPOINT ----
app.post('/api/chat', async (req, res) => {
  const { messages, systemPrompt, mode } = req.body;

  // Basic validation
  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'messages array is required' });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return res.status(500).json({
      error: 'ANTHROPIC_API_KEY is not configured. Copy .env.example to .env and add your key.'
    });
  }

  // Sanitize messages — only allow role/content strings
  const sanitizedMessages = messages
    .filter(m => m.role && typeof m.content === 'string' && m.content.trim())
    .map(m => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content.slice(0, 8000) // cap per-message length
    }));

  if (sanitizedMessages.length === 0) {
    return res.status(400).json({ error: 'No valid messages provided' });
  }

  // Default system prompt if none provided
  const system = (typeof systemPrompt === 'string' && systemPrompt.trim())
    ? systemPrompt
    : `You are VetPath's AI Study Tutor — a helpful learning assistant for veteran students.
       Help them understand concepts, improve their writing, and navigate GI Bill benefits.
       Never write complete assignments for users. Teach, explain, and guide.`;

  try {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 1024,
      system,
      messages: sanitizedMessages,
    });

    const content = response.content[0]?.text ?? '';
    res.json({ content, mode: mode || 'tutor' });

  } catch (err) {
    console.error('[Claude API Error]', err.message);

    if (err.status === 401) {
      return res.status(401).json({ error: 'Invalid Anthropic API key. Check your .env file.' });
    }
    if (err.status === 429) {
      return res.status(429).json({ error: 'Rate limit reached. Please wait a moment and try again.' });
    }
    res.status(500).json({ error: 'AI service error. Please try again.' });
  }
});

// ---- HEALTH CHECK ----
app.get('/api/health', (req, res) => {
  res.json({
    status: 'ok',
    apiKeyConfigured: !!process.env.ANTHROPIC_API_KEY,
    timestamp: new Date().toISOString()
  });
});

// ---- SPA FALLBACK ----
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// ---- START ----
app.listen(PORT, () => {
  console.log(`\n  VetPath server running at http://localhost:${PORT}`);
  if (!process.env.ANTHROPIC_API_KEY) {
    console.warn('\n  WARNING: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.\n');
  } else {
    console.log('  Claude AI: connected\n');
  }
});
