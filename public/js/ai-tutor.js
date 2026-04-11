// ============================================
//  VetPath – AI Tutor Chat Logic
// ============================================

const MODES = {
  tutor: {
    title: 'Study Tutor',
    info: 'Ask any concept you\'re struggling with and I\'ll explain it step-by-step, use relatable examples, and check your understanding with questions.',
    welcome: 'Hey! I\'m your VetPath Study Tutor, powered by Claude AI.\nI\'m here to help you <strong>actually understand</strong> your coursework — not just get answers.\n\nWhat are you working on today?',
    quickPrompts: [
      'Explain this concept to me',
      'Help me study for my exam',
      'Give me practice questions',
      'I need to understand...'
    ]
  },
  writing: {
    title: 'Writing Coach',
    info: 'Paste your essay draft or paragraph and I\'ll give you specific, actionable feedback on structure, clarity, argument strength, and flow. You revise — I coach.',
    welcome: 'Writing Coach mode activated.\n\nPaste your draft (or even just a paragraph you\'re unsure about) and I\'ll give you honest, specific feedback.\n\nI won\'t rewrite it for you — but I\'ll tell you exactly what to improve and why.',
    quickPrompts: [
      'Here\'s my intro paragraph...',
      'Does my thesis statement work?',
      'How can I strengthen this argument?',
      'Check my conclusion'
    ]
  },
  studyguide: {
    title: 'Study Guide Generator',
    info: 'Paste your lecture notes, a chapter summary, or your syllabus. I\'ll turn it into a structured study guide with key terms, main concepts, and practice questions.',
    welcome: 'Study Guide mode — let\'s get you organized.\n\nPaste in your lecture notes, a textbook chapter, or a list of topics, and I\'ll build you a custom study guide complete with:\n\n• Key concepts & definitions\n• How ideas connect\n• Practice questions to test yourself',
    quickPrompts: [
      'Here are my lecture notes...',
      'Make a study guide for: [topic]',
      'What are the key terms for...',
      'Quiz me on this material'
    ]
  },
  gibill: {
    title: 'GI Bill Q&A',
    info: 'Ask me anything about GI Bill chapters, BAH, Yellow Ribbon, eligibility, transferability, or how to apply. I\'ll give you clear answers (and flag when you should verify with the VA directly).',
    welcome: 'GI Bill Q&A mode.\n\nAsk me anything about your education benefits — I know the ins and outs of Chapter 33, Chapter 30, BAH, Yellow Ribbon, eligibility tiers, and more.\n\n<strong>Important:</strong> I\'ll always flag when you should verify information directly with the VA, since benefit rules and amounts change.',
    quickPrompts: [
      'What\'s the difference between Ch.33 and Ch.30?',
      'How is my BAH calculated?',
      'What is the Yellow Ribbon Program?',
      'Can I transfer my benefits?'
    ]
  }
};

let currentMode = 'tutor';
let conversationHistory = [];
let isWaiting = false;

// System prompts per mode
const SYSTEM_PROMPTS = {
  tutor: `You are VetPath's Study Tutor — an AI learning assistant built specifically for veteran students.
Your mission is to help veterans understand their coursework, not do it for them.

Core principles:
- EXPLAIN concepts clearly using analogies, especially military/service analogies when relevant
- GUIDE with Socratic questions rather than just giving answers
- BREAK DOWN complex ideas into manageable steps
- NEVER write complete assignments, essays, or homework for the user
- NEVER produce work that could be submitted directly as the student's own
- If asked to write an essay or complete an assignment, redirect: explain the concept, offer an outline, ask guiding questions
- Keep responses focused, clear, and encouraging
- Acknowledge the veteran's background and the challenges of transitioning to student life
- Use a direct, respectful tone — not condescending, not overly casual`,

  writing: `You are VetPath's Writing Coach — an AI feedback tool for veteran students.
Your job is to review drafts and give honest, specific, actionable feedback.

Core principles:
- ANALYZE the writing the student submits and give specific feedback
- Point out: thesis strength, argument structure, clarity, evidence use, transitions, conclusion
- Give SPECIFIC suggestions ("Your third sentence buries the main point — consider leading with X")
- DO NOT rewrite paragraphs for them — instead, describe what needs to change and why
- DO NOT produce substitute content — your job is feedback, not ghostwriting
- Be direct and honest, not just encouraging — veterans appreciate straight talk
- Help them see WHY a change would improve the piece, not just what to change`,

  studyguide: `You are VetPath's Study Guide Generator — an AI tool that turns notes into structured study materials.
Your job is to help veteran students organize and internalize their course material.

Core principles:
- When given notes, lectures, or topics: create structured study guides with key concepts, definitions, connections
- Include practice questions AT THE END so the student can test themselves
- Organize information clearly with headers and bullet points
- Flag what's likely to be on exams based on how concepts are emphasized
- DO NOT do the student's assignments — study guides are for their own learning
- After generating a guide, offer to quiz the student or clarify specific concepts`,

  gibill: `You are VetPath's GI Bill Benefits Assistant — an AI that helps veterans understand their education benefits.

Core principles:
- Explain GI Bill chapters (33, 30, 35, 1606), eligibility, BAH, Yellow Ribbon, and application process
- Be accurate and clear — but ALWAYS flag when the student should verify with the VA directly (rates change annually)
- Cite that official verification should be at va.gov/education or by calling 1-888-GIBILL-1
- Never give legal or financial advice — give information and direct to official sources for decisions
- Be aware that benefit rules can be complex — acknowledge nuance and gray areas
- Keep answers practical: what does the veteran need to know to take action?`
};

// ---- MODE SWITCHING ----
function setMode(mode, btn) {
  currentMode = mode;
  conversationHistory = [];

  // Update button states
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');

  // Update info text and title
  const modeData = MODES[mode];
  document.getElementById('mode-info').textContent = modeData.info;
  document.getElementById('chat-title').textContent = modeData.title;

  // Update quick prompts
  const qpContainer = document.getElementById('quick-prompts');
  qpContainer.innerHTML = modeData.quickPrompts
    .map(p => `<button class="quick-btn" onclick="useQuickPrompt(this)">${p}</button>`)
    .join('');

  // Clear chat and show new welcome
  const messages = document.getElementById('chat-messages');
  messages.innerHTML = '';
  addMessage('ai', modeData.welcome);
}

// ---- QUICK PROMPTS ----
function useQuickPrompt(btn) {
  const input = document.getElementById('chat-input');
  input.value = btn.textContent;
  input.focus();
  autoResize(input);
}

// ---- MESSAGE RENDERING ----
function addMessage(role, content) {
  const container = document.getElementById('chat-messages');

  const wrapper = document.createElement('div');
  wrapper.className = `message ${role === 'user' ? 'user-msg' : ''}`;

  const avatar = document.createElement('div');
  avatar.className = `msg-avatar ${role === 'ai' ? 'ai' : 'usr'}`;
  avatar.textContent = role === 'ai' ? 'AI' : 'V';

  const bubble = document.createElement('div');
  bubble.className = `msg-bubble ${role === 'ai' ? 'ai-bubble' : 'user-bubble'}`;

  // Render basic markdown-like formatting
  bubble.innerHTML = formatMessage(content);

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);

  // Scroll to bottom
  container.scrollTop = container.scrollHeight;
  return bubble;
}

function addTypingIndicator() {
  const container = document.getElementById('chat-messages');

  const wrapper = document.createElement('div');
  wrapper.className = 'message';
  wrapper.id = 'typing-indicator';

  const avatar = document.createElement('div');
  avatar.className = 'msg-avatar ai';
  avatar.textContent = 'AI';

  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble ai-bubble';
  bubble.innerHTML = `
    <div class="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
    </div>
  `;

  wrapper.appendChild(avatar);
  wrapper.appendChild(bubble);
  container.appendChild(wrapper);
  container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.remove();
}

function formatMessage(text) {
  // Convert basic markdown to HTML
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.*?)`/g, '<code style="background:var(--gray-light);padding:1px 4px;border-radius:3px;font-family:monospace;">$1</code>')
    .replace(/^### (.*$)/gm, '<h4 style="margin:0.75rem 0 0.4rem;color:var(--navy);font-size:0.95rem;">$1</h4>')
    .replace(/^## (.*$)/gm, '<h3 style="margin:0.75rem 0 0.5rem;color:var(--navy);">$1</h3>')
    .replace(/^- (.*$)/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/gms, '<ul style="padding-left:1.25rem;margin:0.5rem 0;">$1</ul>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');
}

// ---- SEND MESSAGE ----
async function sendMessage() {
  if (isWaiting) return;

  const input = document.getElementById('chat-input');
  const userText = input.value.trim();
  if (!userText) return;

  // Clear input
  input.value = '';
  input.style.height = 'auto';

  // Add user message to UI and history
  addMessage('user', userText);
  conversationHistory.push({ role: 'user', content: userText });

  // Show typing indicator and disable send
  isWaiting = true;
  document.getElementById('send-btn').disabled = true;
  addTypingIndicator();

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: currentMode,
        messages: conversationHistory,
        systemPrompt: SYSTEM_PROMPTS[currentMode]
      })
    });

    removeTypingIndicator();

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || `Server error ${response.status}`);
    }

    const data = await response.json();
    const assistantText = data.content;

    addMessage('ai', assistantText);
    conversationHistory.push({ role: 'assistant', content: assistantText });

  } catch (err) {
    removeTypingIndicator();
    const errMsg = err.message.includes('Failed to fetch')
      ? 'Could not reach the server. Make sure the VetPath server is running (npm start).'
      : `Something went wrong: ${err.message}`;
    addMessage('ai', `&#9888; ${errMsg}`);
  } finally {
    isWaiting = false;
    document.getElementById('send-btn').disabled = false;
    input.focus();
  }
}

// ---- INPUT HANDLING ----
function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 140) + 'px';
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('chat-input');
  if (!input) return;

  input.addEventListener('input', () => autoResize(input));

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
});
