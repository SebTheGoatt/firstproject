"""The Field Notebook: the printable PDF in the paid Field Kit (US Letter, 28 pages, prints fine in black and white).

Pages: cover, how to use it, one guide page per paragraph, a blank order (3 pages), pocket cards, 12 weekly reviews,
a 90-day review and the four example orders from src/examples.json.
"""
from datetime import date, timedelta

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

W, H = letter
M = 0.75 * inch
INK, OLIVE, BRASS, MUTED, LINE = (HexColor(c) for c in ("#1d231e", "#4b5a2a", "#94721f", "#5a6458", "#b9bfae"))
DISPLAY, BODY, BOLD, MONO, MONO_B = "Helvetica-Bold", "Helvetica", "Helvetica-Bold", "Courier", "Courier-Bold"

GUIDES = [
    ("1", "Where you stand", "Situation",
     "Ground truth first. A plan built on how you wish things were falls apart on day three. Write what's true today, "
     "with numbers where you have them.",
     ["What is the honest picture today? (weight, balance, hours, how long it's been like this)",
      "What's working against you? Habits, triggers, people, schedule, money. In an order this is the enemy.",
      "What's on your side? People, skills, savings, benefits, past wins.",
      "Time and terrain: when do you actually have free time, where will you do the work, what's coming up?"],
     "Things are bad with money.",
     "$6,400 on one card at 24% APR. $110 a month goes to interest. Stuck at this balance for a year.",
     "Name the enemy as habits and situations, not as yourself. You can plan around a habit."),
    ("2", "The mission", "Mission",
     "One sentence: who, what, when, where and why. If you can't say it in one breath, it's two missions. Pick one.",
     ["Who: usually \"I\". Sometimes \"we\" (you and your spouse).",
      "What: a result you can check. A number, a finish line, a yes or no.",
      "When: a date on the calendar.",
      "Where: the conditions you'll do it in.",
      "Why: in order to... This is the part you'll read on a hard day."],
     "Get healthier this year.",
     "I will lose 20 lb and run a 5K without stopping by 28 FEB, at the park and at home, in order to keep up with my son.",
     "Read your mission out loud. If it sounds like a wish, add a number and a date."),
    ("3", "How you'll do it", "Execution",
     "Intent is what done looks like, so you can adapt when the plan breaks. Phases keep it from feeling like one hill. "
     "Tasks are small enough to do on a bad day.",
     ["What done looks like: if everything else went wrong, what must still be true?",
      "Three phases with dates: set up and get a first win, build the routine, finish and make it permanent.",
      "Daily and weekly tasks: each one small enough to do when you're tired.",
      "If-then plans: decide now, while you're calm, what you'll do when something goes wrong."],
     "Work out more and eat better.",
     "If I sleep through the alarm, then 15 minutes at lunch. If I blow a meal, the next one is normal. No 'starting Monday'.",
     "Plans don't survive first contact. Intent does. Write it so a friend could carry on without you."),
    ("4", "What keeps you going", "Sustainment",
     "Most plans don't fail on effort. They run out of fuel, money or support around week three.",
     ["Fuel: sleep, food, water, energy. What drains you?",
      "Supply: what it costs, what you need, what you'll cut to make room.",
      "Support: who you can call. Doctor, counselor, chaplain, a group, a friend."],
     "I'll push through.",
     "In bed by 10:30, tired me spends money. Cut streaming ($32) and the gym I don't use ($45). Free credit counseling call if stuck.",
     "If things get heavy, you don't have to carry it alone. In the US, call or text 988. Veterans press 1."),
    ("5", "Who's in charge, and check-ins", "Command and signal",
     "You're in command. Pick a second in command who'll ask how it's going, and set the time you'll report.",
     ["Second in command: one person, and how you'll reach them.",
      "Check-ins: a daily one (2 minutes) and a weekly one (the review pages in this notebook).",
      "Warning signs: what you'll notice before it falls apart.",
      "Challenge and password: the question you'll ask yourself on a hard day, and the answer you've already decided."],
     "I'll hold myself accountable.",
     "Marcus, text every Sunday with the balance. Challenge: Why am I doing this? Password: So my family never pays a bank for my bad week.",
     "Tell your second in command the warning signs too. They'll often see them before you do."),
]


class Notebook:
    def __init__(self, path):
        self.c = Canvas(path, pagesize=letter)
        self.c.setTitle("The Five-Paragraph Plan: Field Notebook")
        self.c.setAuthor("The Five-Paragraph Plan")
        self.page = 0

    def new_page(self, folio=True):
        if self.page:
            self.c.showPage()
        self.page += 1
        if folio and self.page > 1:
            self.c.setFont(MONO, 8)
            self.c.setFillColor(MUTED)
            self.c.drawString(M, 0.45 * inch, "THE FIVE-PARAGRAPH PLAN · FIELD NOTEBOOK")
            self.c.drawRightString(W - M, 0.45 * inch, str(self.page))
        self.c.setFillColor(INK)

    def head(self, eyebrow, title, y=H - M):
        c = self.c
        c.setFont(MONO_B, 9)
        c.setFillColor(BRASS)
        c.drawString(M, y, eyebrow.upper())
        c.setFont(DISPLAY, 26)
        c.setFillColor(INK)
        c.drawString(M, y - 30, title)
        c.setStrokeColor(INK)
        c.setLineWidth(1.5)
        c.line(M, y - 42, W - M, y - 42)
        return y - 66

    def text(self, s, y, font=BODY, size=10.5, width=None, color=INK, lead=1.4, x=M):
        width = width or (W - x - M)
        self.c.setFont(font, size)
        self.c.setFillColor(color)
        for ln in simpleSplit(s, font, size, width):
            self.c.drawString(x, y, ln)
            y -= size * lead
        return y

    def bullets(self, items, y, size=10.5, x=M):
        for it in items:
            self.c.setFillColor(OLIVE)
            self.c.rect(x, y + 2, 4, 4, stroke=0, fill=1)
            y = self.text(it, y, size=size, x=x + 12) - 4
        return y

    def label(self, s, y, x=M):
        self.c.setFont(BOLD, 10)
        self.c.setFillColor(INK)
        self.c.drawString(x, y, s)
        return y - 6

    def lines(self, y, n, x=M, x2=None, gap=22):
        x2 = x2 or W - M
        self.c.setStrokeColor(LINE)
        self.c.setLineWidth(0.6)
        for _ in range(n):
            y -= gap
            self.c.line(x, y, x2, y)
        return y - 12

    def field(self, title, hint, y, n):
        y = self.label(title, y)
        if hint:
            y = self.text(hint, y - 8, size=8.5, color=MUTED) + 8
        return self.lines(y, n)


def cover(nb):
    nb.new_page(folio=False)
    c = nb.c
    c.setFillColor(INK)
    c.rect(0, H - 3.1 * inch, W, 3.1 * inch, stroke=0, fill=1)
    c.setFillColor(HexColor("#d4b25a"))
    c.setFont(MONO_B, 10)
    c.drawString(M, H - 1.0 * inch, "FIELD NOTEBOOK")
    c.setFillColor(HexColor("#fbfbf6"))
    c.setFont(DISPLAY, 44)
    c.drawString(M, H - 1.75 * inch, "THE FIVE-PARAGRAPH")
    c.drawString(M, H - 2.4 * inch, "PLAN")
    y = H - 4.0 * inch
    y = nb.text("The planning format the military uses for every operation, for the mission that matters to you.",
                y, size=13, width=5.6 * inch)
    y -= 40
    for lab in ("OPERATION", "ISSUED", "MY SECOND IN COMMAND"):
        c.setFont(MONO_B, 10)
        c.setFillColor(MUTED)
        c.drawString(M, y, lab)
        c.setStrokeColor(INK)
        c.setLineWidth(0.8)
        c.line(M + 1.9 * inch, y - 2, W - M, y - 2)
        y -= 40
    y -= 30
    for n, t, mil in [(g[0], g[1], g[2]) for g in GUIDES]:
        c.setFont(DISPLAY, 20)
        c.setFillColor(OLIVE)
        c.drawString(M, y, n)
        c.setFont(BOLD, 12)
        c.setFillColor(INK)
        c.drawString(M + 28, y + 2, t)
        c.setFont(MONO, 9)
        c.setFillColor(MUTED)
        c.drawString(M + 28 + c.stringWidth(t, BOLD, 12) + 10, y + 2, mil.upper())
        y -= 30


def how_to(nb):
    nb.new_page()
    y = nb.head("Start here", "How to use this notebook")
    steps = [
        ("Write your order (about 20 minutes).", "Use the planner app or the blank order on pages 8-10. Read the "
         "guide page for each paragraph first. Pages 25-28 show four finished orders."),
        ("Pick a second in command.", "Send them your mission sentence and your check-in time. One person is enough."),
        ("Cut out your pocket card (page 11).", "Keep it in your wallet, or screenshot the one in the app for your "
         "lock screen."),
        ("Do the weekly review every week.", "Twelve review pages, five minutes each. No blame: what was supposed to "
         "happen, what happened, why, and what you'll keep or change."),
        ("At 90 days, review and issue the next order.", "Page 24. Most missions take more than one order. That's "
         "normal, not failure."),
    ]
    for i, (a, b) in enumerate(steps, 1):
        nb.c.setFont(DISPLAY, 18)
        nb.c.setFillColor(OLIVE)
        nb.c.drawString(M, y - 2, str(i))
        y = nb.text(a, y, font=BOLD, size=12, x=M + 28)
        y = nb.text(b, y - 2, x=M + 28) - 14
    y -= 10
    nb.c.setStrokeColor(OLIVE)
    nb.c.setLineWidth(2)
    nb.c.line(M, y + 12, M, y - 52)
    y = nb.text("Why five paragraphs?", y, font=BOLD, x=M + 14)
    nb.text("Because they cover the reasons plans fail: wrong picture of the situation, a fuzzy goal, no way to adapt, "
            "running out of fuel, and nobody checking in. Answer all five and you've closed every gap.", y - 2,
            x=M + 14)


def guide(nb, g):
    n, title, mil, why, qs, weak, strong, tip = g
    nb.new_page()
    y = nb.head(f"Paragraph {n} · {mil}", title)
    y = nb.text(why, y, size=12, width=W - 2 * M) - 14
    y = nb.label("Answer these", y) - 10
    y = nb.bullets(qs, y) - 14
    for lab, body, col in (("WEAK", weak, MUTED), ("STRONG", strong, OLIVE)):
        nb.c.setFont(MONO_B, 9)
        nb.c.setFillColor(col)
        nb.c.drawString(M, y, lab)
        y = nb.text(body, y, font=MONO, size=10, x=M + 60) - 12
    y -= 8
    nb.c.setFillColor(HexColor("#f1f2ea"))
    box = simpleSplit(tip, BODY, 10.5, W - 2 * M - 24)
    hgt = 16 + len(box) * 14.7
    nb.c.rect(M, y - hgt + 12, W - 2 * M, hgt, stroke=0, fill=1)
    nb.text(tip, y - 4, x=M + 12, width=W - 2 * M - 24)


def blank_order(nb):
    nb.new_page()
    y = nb.head("Blank order · page 1 of 3", "Operation ____________________")
    y = nb.label("1. SITUATION", y) - 4
    y = nb.field("a. The honest picture today", "", y, 3)
    y = nb.field("b. Working against me", "One per line.", y, 4)
    y = nb.field("c. On my side", "One per line.", y, 4)
    y = nb.field("d. Time and terrain", "", y, 3)

    nb.new_page()
    y = nb.head("Blank order · page 2 of 3", "Mission and execution")
    y = nb.label("2. MISSION", y) - 14
    for lab in ("Who", "will (what)", "by (when)", "where", "in order to (why)"):
        nb.c.setFont(MONO, 10)
        nb.c.setFillColor(MUTED)
        nb.c.drawString(M, y, lab)
        nb.c.setStrokeColor(LINE)
        nb.c.line(M + 1.5 * inch, y - 2, W - M, y - 2)
        y -= 26
    y -= 8
    y = nb.label("3. EXECUTION", y) - 4
    y = nb.field("a. What done looks like", "", y, 3)
    for i, hint in enumerate(("Set up, first win", "Build the routine", "Finish, make it permanent"), 1):
        nb.c.setFont(BOLD, 10)
        nb.c.setFillColor(INK)
        nb.c.drawString(M, y - 16, f"Phase {i}")
        nb.c.setFont(BODY, 8.5)
        nb.c.setFillColor(MUTED)
        nb.c.drawString(M + 50, y - 16, hint)
        nb.c.setStrokeColor(LINE)
        nb.c.line(M + 170, y - 18, W - M, y - 18)
        y -= 28
    y = nb.field("c. Daily and weekly tasks", "Small enough for a bad day.", y - 8, 4)

    nb.new_page()
    y = nb.head("Blank order · page 3 of 3", "Keep going, check in")
    y = nb.field("3d. If this happens, then I will", "", y, 3)
    y = nb.label("4. SUSTAINMENT", y) - 4
    y = nb.field("a. Fuel: sleep, food, energy", "", y, 2)
    y = nb.field("b. Supply: money, tools, time", "", y, 2)
    y = nb.field("c. Support: health and the people behind me", "", y, 2)
    y = nb.label("5. COMMAND AND SIGNAL", y) - 4
    y = nb.field("a. Second in command and how I'll reach them", "", y, 1)
    y = nb.field("b. Check-ins", "", y, 1)
    y = nb.field("c. Warning signs", "", y, 2)
    nb.field("d. Challenge / password", "", y, 1)


def pocket_cards(nb):
    nb.new_page()
    y = nb.head("Cut along the dotted lines", "Pocket cards")
    cw, ch = 3.5 * inch, 2.0 * inch
    gx = (W - 2 * M - 2 * cw)
    c = nb.c
    for row in range(3):
        for col in range(2):
            x = M + col * (cw + gx)
            top = y - row * (ch + 0.3 * inch)
            c.setDash(3, 3)
            c.setStrokeColor(MUTED)
            c.rect(x, top - ch, cw, ch, stroke=1, fill=0)
            c.setDash()
            yy = top - 18
            for lab, n in (("OPERATION", 1), ("MISSION", 2), ("DONE LOOKS LIKE", 1), ("CHALLENGE / PASSWORD", 1)):
                c.setFont(MONO_B, 6.5)
                c.setFillColor(OLIVE)
                c.drawString(x + 10, yy, lab)
                c.setStrokeColor(LINE)
                for _ in range(n):
                    yy -= 13
                    c.line(x + 10, yy, x + cw - 10, yy)
                yy -= 11


def weekly(nb, week):
    nb.new_page()
    y = nb.head(f"Weekly review · week {week} of 12", "After action review")
    c = nb.c
    c.setFont(MONO, 9)
    c.setFillColor(MUTED)
    c.drawString(M, y + 8, "Dates ____________ to ____________          Five minutes. No blame.")
    y -= 14
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    col0, cw = M + 2.6 * inch, (W - M - (M + 2.6 * inch)) / 7
    c.setFont(MONO_B, 8)
    c.setFillColor(INK)
    c.drawString(M, y, "DAILY TASKS")
    for i, d in enumerate(days):
        c.drawCentredString(col0 + cw * i + cw / 2, y, d)
    c.setStrokeColor(LINE)
    for r in range(4):
        yy = y - 22 - r * 22
        c.line(M, yy - 4, col0 - 10, yy - 4)
        for i in range(7):
            c.rect(col0 + cw * i + cw / 2 - 6, yy - 4, 12, 12, stroke=1, fill=0)
    y = y - 22 * 4 - 26
    for q, n in (("1. What was supposed to happen?", 2), ("2. What actually happened?", 3),
                 ("3. Why was there a difference?", 3), ("4. What do I keep, and what do I change next week?", 3),
                 ("Warning signs I saw this week", 1), ("Message to my second in command", 2)):
        y = nb.field(q, "", y, n)


def ninety(nb):
    nb.new_page()
    y = nb.head("Day 90", "Review the operation, issue the next order")
    for q, n in (("Did I accomplish the mission? Where does it stand, in numbers?", 3),
                 ("What worked that I'll keep for good?", 3), ("What didn't work, and why?", 3),
                 ("What did I learn about the enemy (my habits and triggers)?", 3),
                 ("Thank my second in command: what did they do that helped?", 2),
                 ("Next mission, in one sentence", 2)):
        y = nb.field(q, "", y, n)


def example(nb, key, ex, title):
    nb.new_page()
    y = nb.head(f"Finished order · {title}", f"Operation {ex['op_name']}")
    when = (date.today() + timedelta(days=ex["mis_when_days"])).strftime("%d %b %Y").upper()
    mission = (f"{ex['mis_who']} will {ex['mis_what']} by {when}, {ex['mis_where']}, in order to {ex['mis_why']}.")
    parts = [
        ("1. SITUATION", None),
        ("a. Ground truth. " + ex["sit_ground"], None),
        ("b. Working against me.", ex["sit_against"]),
        ("c. On my side.", ex["sit_for"]),
        ("d. Time and terrain. " + ex["sit_terrain"], None),
        ("2. MISSION", None), (mission, None),
        ("3. EXECUTION", None),
        ("a. Intent. " + ex["exe_intent"], None),
        ("b. Phases.", "\n".join([ex["exe_p1"], ex["exe_p2"], ex["exe_p3"]])),
        ("c. Tasks.", ex["exe_daily"]),
        ("d. If-then.", ex["exe_ifthen"]),
        ("4. SUSTAINMENT", None),
        ("a. Fuel. " + ex["sus_fuel"], None), ("b. Supply. " + ex["sus_supply"], None),
        ("c. Support. " + ex["sus_support"], None),
        ("5. COMMAND AND SIGNAL", None),
        ("a. Second in command. " + ex["cmd_partner"], None), ("b. Check-ins. " + ex["cmd_checkin"], None),
        ("c. Warning signs.", ex["cmd_signals"]),
        (f"d. Challenge / password. {ex['cmd_challenge']} / {ex['cmd_password']}", None),
    ]
    for head, sub in parts:
        is_para = head[0].isdigit() and head.isupper()
        if is_para:
            y -= 4
        y = nb.text(head.replace("–", "-"), y, font=MONO_B if is_para else MONO, size=8.8, lead=1.32)
        if sub:
            for ln in sub.split("\n"):
                y = nb.text("- " + ln.replace("–", "-"), y, font=MONO, size=8.8, lead=1.32, x=M + 16)


def build(path, examples):
    nb = Notebook(path)
    cover(nb)
    how_to(nb)
    for g in GUIDES:
        guide(nb, g)
    blank_order(nb)
    pocket_cards(nb)
    for w in range(1, 13):
        weekly(nb, w)
    ninety(nb)
    titles = {"debt": "Get out of debt", "fit": "Get back in shape", "career": "Leave the service, land a job",
              "parent": "Be a present parent"}
    for key, ex in examples.items():
        example(nb, key, ex, titles.get(key, key))
    nb.c.save()
    return nb.page
