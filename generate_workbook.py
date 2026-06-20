#!/usr/bin/env python3
"""
IELTS Workbook Generator — Lexilink Ideation
=============================================
Drop any file into the input/ folder (vocabulary list, reading passage,
or listening script), then run:

    python3 generate_workbook.py

Optional arguments:
    --units  9-10          override auto-detected unit numbers
    --level  2             1=Beginner  2=Foundation(default)  3=Academic
    --model  claude-opus-4-5   override Claude model (default: claude-opus-4-5)

Requirements:
    pip install anthropic pdfplumber
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import os, sys, json, re, glob, argparse, random
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"

# ─── Level labels ────────────────────────────────────────────────────────────

LEVEL_LABELS = {
    1: "Level 1 — Beginner",
    2: "Level 2 — Foundation",
    3: "Level 3 — Academic",
}

# ─── Auto-detect next unit pair ──────────────────────────────────────────────

def get_next_unit_pair():
    existing = sorted(glob.glob(str(BASE_DIR / "IELTS_Workbook_Units*.html")))
    if not existing:
        return 9, 10
    last_b = 0
    for f in existing:
        m = re.search(r"Units(\d+)-(\d+)", f)
        if m:
            last_b = max(last_b, int(m.group(2)))
    return last_b + 1, last_b + 2

# ─── Read input file ─────────────────────────────────────────────────────────

def read_input():
    files = sorted(
        [f for f in INPUT_DIR.iterdir() if f.is_file() and not f.name.startswith(".")],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if not files:
        sys.exit(f"❌  No files found in {INPUT_DIR}. Drop a .txt or .pdf there first.")

    path = files[0]
    print(f"📄  Input file: {path.name}")

    if path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            sys.exit("❌  pdfplumber not installed. Run: pip install pdfplumber")
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")

    return text.strip(), path.name

# ─── Call Claude API ─────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """\
You are an expert IELTS vocabulary curriculum designer for a senior high school \
workbook targeting Chinese learners (A2 → IELTS Band 6+).

Below is source material (a vocabulary list, reading passage, or listening script).
From it, identify TWO distinct IELTS topic themes and select 10 words for each theme.
Prioritise words that recur in IELTS Cambridge reading/writing tasks.

SOURCE MATERIAL (first 7000 chars):
{source}

LEVEL: {level_label}

Return ONLY valid JSON — no markdown fences, no explanation — matching this schema exactly:

{{
  "unit_a": {{
    "topic_en": "Topic Name",
    "topic_cn": "中文主题",
    "story_title": "Character's Story Title",
    "write_prompt_en": "Writing prompt in English. Use at least 5 words from today's unit.",
    "write_prompt_cn": "写作提示中文版。尽量用5个今天学过的单词。",
    "speak_hints": "Phrase one… | Phrase two… | Phrase three…",
    "words": [
      {{"w": "word", "p": "n./v./adj./adv.", "cn": "中文释义(≤8字)", "m": "Clear English definition.", "eg": "Natural example sentence at B1-B2 level."}}
    ],
    "story": [
      ["Paragraph text with ", {{"h": "word"}}, " embedded naturally, etc."]
    ],
    "tf": [{{"q": "Statement about the story?", "a": true}}],
    "mc": [{{"q": "Question?", "o": ["Option A", "Option B", "Option C", "Option D"], "a": 0}}],
    "match": {{
      "words": ["w1","w2","w3","w4","w5"],
      "defs":  ["def for w3","def for w1","def for w4","def for w5","def for w2"],
      "correct": [1, 4, 0, 2, 3]
    }},
    "fib": {{
      "chips": ["w1","w2","w3","w4","w5"],
      "rows": [{{"pre": "Sentence start ", "suf": " sentence end.", "ans": "w1"}}]
    }},
    "speak": ["Question 1?", "Question 2?", "Question 3?", "Question 4?", "Question 5?"],
    "rev": [["word","中文"]],
    "col": [["collocation phrase","中文搭配"]]
  }},
  "unit_b": {{ ...same structure... }}
}}

STRICT RULES:
• Each unit has EXACTLY 10 words, EXACTLY 5 tf, EXACTLY 5 mc, EXACTLY 5 match pairs, \
EXACTLY 5 fib rows, EXACTLY 5 speak questions, 10 rev pairs, 10 col pairs.
• Story: 4–5 natural paragraphs; ALL 10 words must appear, marked as {{"h":"word"}} in the array.
• match.correct[i] = index in match.defs that is the correct definition for match.words[i]. \
  Defs must NOT be in word order (pre-shuffle them so it's a real matching challenge).
• fib rows must NOT use the same word as the speak hints or story title.
• Chinese definitions ≤ 8 characters.
• unit_a and unit_b must cover DIFFERENT topics and use completely different word sets.
"""

def call_api(source_text: str, level: int, model: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()

    prompt = PROMPT_TEMPLATE.format(
        source=source_text[:7000],
        level_label=LEVEL_LABELS[level],
    )

    print(f"🤖  Calling {model} to generate content…")
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if the model adds them anyway
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"❌  JSON parse error: {e}\n\nRaw response:\n{raw[:500]}")

# ─── HTML builder ────────────────────────────────────────────────────────────

def esc(s: str) -> str:
    """Escape & and < > for HTML attributes / display text."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def speak_hints_html(hints_str: str) -> str:
    parts = [p.strip() for p in hints_str.split("|")]
    joined = " &nbsp;|&nbsp; ".join(f"<strong>{esc(p)}</strong>" for p in parts)
    return f'Useful phrases: {joined}'

def build_html(data: dict, unit_a: int, unit_b: int, level: int) -> str:
    ua = data["unit_a"]
    ub = data["unit_b"]

    level_label = LEVEL_LABELS[level]
    pair_str    = f"Units {unit_a}–{unit_b}"   # "Units 9–10"
    pair_dash   = f"Units{unit_a}-{unit_b}"               # "Units9-10"

    topics_en = f"{esc(ua['topic_en'])} &nbsp;&middot;&nbsp; {esc(ub['topic_en'])}"
    topics_cn = f"{ua['topic_cn']} · {ub['topic_cn']}"

    # Serialize the JS data array
    js_units = []
    for u in (ua, ub):
        # Shuffle the word-bank chips so they don't appear in answer order
        shuffled_chips = u["fib"]["chips"][:]
        random.shuffle(shuffled_chips)
        fib_shuffled = {**u["fib"], "chips": shuffled_chips}
        js_units.append({
            "words":  u["words"],
            "story":  u["story"],
            "tf":     u["tf"],
            "mc":     u["mc"],
            "match":  u["match"],
            "fib":    fib_shuffled,
            "speak":  u["speak"],
            "rev":    u["rev"],
            "col":    u["col"],
        })
    data_js = json.dumps(js_units, ensure_ascii=False, indent=2)

    html = HTML_TEMPLATE
    html = html.replace("%%TITLE%%",          f"IELTS Vocabulary Workbook — {pair_str} — Lexilink Ideation IELTS Studio")
    html = html.replace("%%PAIR_STR%%",       pair_str)
    html = html.replace("%%TOPICS_EN%%",      topics_en)
    html = html.replace("%%TOPICS_CN%%",      topics_cn)
    html = html.replace("%%LEVEL_LABEL%%",    level_label)
    html = html.replace("%%UNIT_A_NUM%%",     str(unit_a))
    html = html.replace("%%UNIT_A_TOPIC_EN%%", esc(ua["topic_en"]))
    html = html.replace("%%UNIT_A_TOPIC_CN%%", ua["topic_cn"])
    html = html.replace("%%UNIT_B_NUM%%",     str(unit_b))
    html = html.replace("%%UNIT_B_TOPIC_EN%%", esc(ub["topic_en"]))
    html = html.replace("%%UNIT_B_TOPIC_CN%%", ub["topic_cn"])
    html = html.replace("%%STORY_TITLE_A%%",  esc(ua["story_title"]))
    html = html.replace("%%STORY_TITLE_B%%",  esc(ub["story_title"]))
    html = html.replace("%%WRITE_EN_A%%",     esc(ua["write_prompt_en"]))
    html = html.replace("%%WRITE_CN_A%%",     esc(ua["write_prompt_cn"]))
    html = html.replace("%%WRITE_EN_B%%",     esc(ub["write_prompt_en"]))
    html = html.replace("%%WRITE_CN_B%%",     esc(ub["write_prompt_cn"]))
    html = html.replace("%%SPEAK_HINTS_A%%",  speak_hints_html(ua["speak_hints"]))
    html = html.replace("%%SPEAK_HINTS_B%%",  speak_hints_html(ub["speak_hints"]))
    html = html.replace("%%DATA_JS%%",        data_js)

    return html

# ─── HTML template ───────────────────────────────────────────────────────────
# Placeholders: %%TITLE%% %%PAIR_STR%% %%TOPICS_EN%% %%TOPICS_CN%%
#   %%LEVEL_LABEL%% %%UNIT_A_NUM%% %%UNIT_A_TOPIC_EN%% %%UNIT_A_TOPIC_CN%%
#   %%UNIT_B_NUM%% %%UNIT_B_TOPIC_EN%% %%UNIT_B_TOPIC_CN%%
#   %%STORY_TITLE_A%% %%STORY_TITLE_B%%
#   %%WRITE_EN_A%% %%WRITE_CN_A%% %%WRITE_EN_B%% %%WRITE_CN_B%%
#   %%SPEAK_HINTS_A%% %%SPEAK_HINTS_B%%
#   %%DATA_JS%%

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%%</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Noto+Sans+SC:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Inter','Noto Sans SC',system-ui,sans-serif;background:#F3F7F8;color:#1C2B33;line-height:1.6}
:root{--teal:#1A7A8A;--teal-dk:#115966;--teal-lt:#D6EEF1;--teal-pl:#EEF8FA;--gold:#C9930A;--gold-lt:#FDF3D8;--gold-pl:#FFFBF0;--sf:#FFFFFF;--bg:#F3F7F8;--bd:#DDE5E8;--tx:#1C2B33;--mu:#5A7280;--ok-bg:#E1F5EE;--ok:#0F6E56;--er-bg:#FCEBEB;--er:#A32D2D}
.page{max-width:860px;margin:0 auto;padding:0 1rem 4rem}
.topbar{background:var(--teal);color:#fff;padding:.6rem 1.5rem;font-size:12px;letter-spacing:.06em;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(26,122,138,.18)}
.topbar-left{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap;min-width:0}
.topbar-logo{font-weight:600;letter-spacing:.08em}
.topbar-home{font-size:12px;color:#fff;opacity:.85;text-decoration:none;border:1px solid rgba(255,255,255,.35);border-radius:20px;padding:.25rem .8rem;transition:all .15s;display:flex;align-items:center;gap:.35rem;flex-shrink:0;white-space:nowrap}
.topbar-home:hover{opacity:1;background:rgba(255,255,255,.15)}
.cover{background:var(--teal);color:#fff;padding:3rem 2rem 2.5rem;text-align:center;border-radius:0 0 20px 20px;margin-bottom:2rem}
.cover-eyebrow{font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;opacity:.7;margin-bottom:.75rem}
.cover-title{font-size:clamp(22px,5vw,36px);font-weight:600;line-height:1.2;margin-bottom:.5rem}
.cover-units{font-size:18px;font-weight:600;color:#FFD97D;margin-bottom:.4rem}
.cover-sub{font-size:15px;opacity:.8;margin-bottom:1.75rem}
.cover-badges{display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap;margin-bottom:1.5rem}
.badge{display:inline-block;padding:.3rem .8rem;border-radius:20px;font-size:12px;font-weight:500;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25)}
.cover-tip{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);border-radius:12px;padding:1rem 1.25rem;max-width:500px;margin:0 auto;font-size:13px;text-align:left;line-height:1.6}
.cover-tip strong{display:block;margin-bottom:.3rem}
.unit-nav{display:flex;gap:.5rem;margin-bottom:1.5rem;flex-wrap:wrap}
.unit-btn{flex:1;min-width:140px;padding:.7rem 1rem;border-radius:10px;border:1.5px solid var(--bd);background:var(--sf);font-size:14px;font-weight:500;cursor:pointer;color:var(--mu);transition:all .18s;text-align:center}
.unit-btn:hover{border-color:var(--teal);color:var(--teal)}
.unit-btn.active{background:var(--teal);color:#fff;border-color:var(--teal)}
.unit-panel{display:none}
.unit-panel.active{display:block}
.unit-hdr{background:linear-gradient(135deg,var(--teal) 0%,var(--teal-dk) 100%);color:#fff;border-radius:14px;padding:1.5rem 1.75rem;margin-bottom:1.25rem;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.75rem}
.unit-hdr-title{font-size:20px;font-weight:600}
.unit-hdr-meta{font-size:13px;opacity:.75;margin-top:.2rem}
.unit-level{font-size:11px;background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.3);padding:.25rem .7rem;border-radius:20px}
.part-nav{display:flex;gap:.4rem;margin-bottom:1.25rem;flex-wrap:wrap}
.part-btn{padding:.38rem .85rem;border-radius:20px;border:1px solid var(--bd);background:var(--sf);font-size:13px;cursor:pointer;color:var(--mu);transition:all .15s;white-space:nowrap}
.part-btn:hover{background:var(--teal-pl);color:var(--teal);border-color:var(--teal-lt)}
.part-btn.active{background:var(--gold);color:#fff;border-color:var(--gold)}
.part-panel{display:none}
.part-panel.active{display:block}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:14px;padding:1.25rem 1.5rem;margin-bottom:1rem;box-shadow:0 1px 4px rgba(0,0,0,.04)}
.card-title{font-size:14px;font-weight:600;color:var(--teal);margin-bottom:1rem}
.vi{border:1px solid var(--bd);border-radius:10px;overflow:hidden;margin-bottom:.5rem;transition:box-shadow .15s}
.vi:hover{box-shadow:0 2px 8px rgba(26,122,138,.1)}
.vh{display:flex;align-items:center;gap:.75rem;padding:.65rem 1rem;background:var(--bg);cursor:pointer;user-select:none}
.vh:hover{background:var(--teal-pl)}
.vw{font-size:15px;font-weight:600;color:var(--teal);min-width:120px}
.vp{font-size:11px;color:var(--mu);background:var(--sf);border:1px solid var(--bd);border-radius:20px;padding:.1rem .45rem;flex-shrink:0}
.vc{font-size:13px;color:var(--mu);flex:1}
.vt{font-size:11px;color:var(--mu);margin-left:auto;flex-shrink:0}
.vb{display:none;padding:.75rem 1rem;border-top:1px solid var(--bd)}
.vb.open{display:block}
.vm{font-size:13px;color:var(--mu);margin-bottom:.5rem}
.ve{font-size:14px;font-style:italic;padding:.5rem .75rem;background:var(--teal-pl);border-left:3px solid var(--teal);border-radius:0 8px 8px 0;color:var(--tx)}
.story-box{background:var(--gold-pl);border:1px solid #E8D08A;border-radius:12px;padding:1.5rem}
.story-title{font-size:16px;font-weight:600;color:var(--gold);margin-bottom:1rem}
.story-text{font-size:14px;line-height:1.9;color:var(--tx)}
.hw{font-weight:600;color:var(--teal);background:var(--teal-lt);padding:.05rem .3rem;border-radius:4px}
.tf-row{display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;padding:.6rem 0;border-bottom:1px solid var(--bd)}
.tf-row:last-child{border-bottom:none}
.tf-q{font-size:14px;flex:1;min-width:200px}
.tf-btns{display:flex;gap:.35rem;flex-shrink:0}
.tf-btn{padding:.28rem .7rem;border-radius:6px;border:1px solid var(--bd);background:var(--sf);font-size:13px;font-weight:500;cursor:pointer;transition:all .15s}
.tf-btn:hover{background:var(--bg)}
.tf-btn.correct{background:var(--ok-bg);border-color:var(--ok);color:var(--ok)}
.tf-btn.wrong{background:var(--er-bg);border-color:var(--er);color:var(--er)}
.tf-btn:disabled{pointer-events:none;opacity:.55}
.tf-res{font-size:12px;font-weight:500;flex-shrink:0}
.mc-block{margin-bottom:1rem;padding-bottom:1rem;border-bottom:1px solid var(--bd)}
.mc-block:last-child{border-bottom:none;padding-bottom:0;margin-bottom:0}
.mc-q{font-size:14px;font-weight:500;margin-bottom:.5rem}
.mc-opts{display:grid;grid-template-columns:1fr 1fr;gap:.35rem}
@media(max-width:500px){.mc-opts{grid-template-columns:1fr}}
.mc-opt{padding:.45rem .75rem;border-radius:8px;border:1px solid var(--bd);background:var(--sf);font-size:13px;cursor:pointer;text-align:left;transition:all .15s;color:var(--tx)}
.mc-opt:hover:not(:disabled){background:var(--teal-pl);border-color:var(--teal-lt)}
.mc-opt.correct{background:var(--ok-bg);border-color:var(--ok);color:var(--ok)}
.mc-opt.wrong{background:var(--er-bg);border-color:var(--er);color:var(--er)}
.mc-opt:disabled{pointer-events:none}
.score-bar{display:flex;align-items:center;gap:.75rem;padding:.75rem 1rem;background:var(--bg);border-radius:8px;margin-top:.75rem;border:1px solid var(--bd)}
.score-bar.good{background:var(--ok-bg);border-color:var(--ok)}
.score-n{font-size:20px;font-weight:600;color:var(--teal)}
.score-l{font-size:13px;color:var(--mu)}
.match-grid{display:grid;grid-template-columns:1fr 1fr;gap:.5rem;margin-top:.75rem}
@media(max-width:500px){.match-grid{grid-template-columns:1fr}}
.mw{padding:.5rem .75rem;background:var(--teal-pl);border:1px solid var(--teal-lt);border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;color:var(--teal);transition:all .15s;text-align:left;width:100%}
.mw:hover:not(:disabled){background:var(--teal-lt)}
.mw.sel{background:var(--teal);color:#fff;border-color:var(--teal)}
.mw.done{background:var(--ok-bg);border-color:var(--ok);color:var(--ok);pointer-events:none}
.md{padding:.5rem .75rem;background:var(--sf);border:1px solid var(--bd);border-radius:8px;font-size:13px;cursor:pointer;color:var(--tx);transition:all .15s;text-align:left;width:100%}
.md:hover:not(.done){background:var(--gold-pl);border-color:#E8D08A}
.md.done{background:var(--ok-bg);border-color:var(--ok);color:var(--ok);pointer-events:none}
.md.err{background:var(--er-bg);border-color:var(--er)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.75rem;padding:.6rem .75rem;background:var(--teal-pl);border-radius:8px;border:1px solid var(--teal-lt)}
.chip{display:inline-block;padding:.22rem .6rem;background:var(--sf);color:var(--teal);border-radius:20px;font-size:12px;font-weight:500;cursor:pointer;border:1px solid var(--teal-lt);transition:all .15s}
.chip:hover{background:var(--teal);color:#fff}
.chip.used{opacity:.3;pointer-events:none}
.fib-row{font-size:14px;display:flex;flex-wrap:wrap;align-items:center;gap:.3rem;padding:.4rem 0;border-bottom:1px solid var(--bd)}
.fib-row:last-child{border-bottom:none}
.fib-n{font-weight:500;color:var(--mu);min-width:1.4rem;flex-shrink:0}
.fib-i{border:none;border-bottom:2px solid var(--bd);background:transparent;font-size:14px;color:var(--tx);padding:.1rem .2rem;width:120px;outline:none;font-family:inherit;transition:border-color .15s}
.fib-i:focus{border-color:var(--teal)}
.fib-i.correct{border-color:var(--ok);color:var(--ok)}
.fib-i.wrong{border-color:var(--er);color:var(--er)}
.btn{padding:.45rem 1.1rem;border-radius:8px;font-size:13px;font-weight:500;cursor:pointer;transition:all .15s;font-family:inherit}
.btn-p{background:var(--teal);color:#fff;border:1px solid var(--teal)}
.btn-p:hover{background:var(--teal-dk)}
.btn-g{background:var(--sf);color:var(--mu);border:1px solid var(--bd)}
.btn-g:hover{background:var(--bg)}
.btn-row{display:flex;gap:.5rem;margin-top:.75rem;flex-wrap:wrap}
.speak-card{padding:.75rem 1rem;background:var(--bg);border-radius:8px;margin-bottom:.5rem;font-size:14px;border-left:3px solid var(--teal);display:flex;gap:.6rem;color:var(--tx)}
.speak-n{font-weight:600;color:var(--teal);min-width:1.4rem;flex-shrink:0}
.hint{font-size:12px;color:var(--mu);background:var(--gold-pl);border:1px solid #E8D08A;border-radius:8px;padding:.6rem .85rem;margin-top:.75rem;line-height:1.6}
.hint strong{color:var(--gold);font-weight:600}
.wp{font-size:14px;color:var(--tx);margin-bottom:.4rem}
.wp-cn{font-size:13px;color:var(--mu);margin-bottom:.75rem}
.wa{width:100%;border:1px solid var(--bd);border-radius:8px;padding:.75rem;font-size:14px;font-family:inherit;color:var(--tx);background:var(--sf);resize:vertical;min-height:130px;outline:none;transition:border-color .15s;line-height:1.7}
.wa:focus{border-color:var(--teal)}
.wc{font-size:12px;color:var(--mu);margin-top:.3rem;text-align:right}
.rev-cols{display:grid;grid-template-columns:1fr 1fr;gap:1.25rem}
@media(max-width:560px){.rev-cols{grid-template-columns:1fr}}
.rev-col-lbl{font-size:13px;font-weight:600;margin-bottom:.6rem}
.ri{display:flex;justify-content:space-between;align-items:baseline;gap:.5rem;padding:.35rem 0;border-bottom:1px solid var(--bd);font-size:13px}
.ri:last-child{border-bottom:none}
.r-en{font-weight:500;color:var(--tx)}
.r-cn{color:var(--mu);font-size:12px}
.ci{padding:.35rem 0;border-bottom:1px solid var(--bd);font-size:13px}
.ci:last-child{border-bottom:none}
.c-en{font-weight:500;color:var(--teal)}
.c-cn{color:var(--mu);font-size:12px}
</style>
</head>
<body>
<div class="topbar">
  <div class="topbar-left">
    <span class="topbar-logo">Lexilink Ideation IELTS Studio</span>
    <span>IELTS Vocabulary Workbook &mdash; %%PAIR_STR%%</span>
  </div>
  <a class="topbar-home" href="index.html">&larr; Home &#39064;&#39029;</a>
</div>
<div class="cover">
  <div class="cover-eyebrow">Lexilink Ideation IELTS Studio</div>
  <div class="cover-title">IELTS Vocabulary Workbook</div>
  <div class="cover-units">%%PAIR_STR%%</div>
  <div class="cover-sub">%%TOPICS_EN%% &nbsp;|&nbsp; %%TOPICS_CN%%</div>
  <div class="cover-badges">
    <span class="badge">%%LEVEL_LABEL%%</span>
    <span class="badge">20 target words</span>
    <span class="badge">Interactive exercises</span>
  </div>
  <div class="cover-tip"><strong>How to use</strong>Study vocabulary &rarr; Read the story &rarr; Complete the exercises. Click any word card to see its meaning. Answers are checked instantly.</div>
</div>

<div class="page">
  <div class="unit-nav">
    <button class="unit-btn active" onclick="sU(0)">Unit %%UNIT_A_NUM%% &mdash; %%UNIT_A_TOPIC_EN%%</button>
    <button class="unit-btn" onclick="sU(1)">Unit %%UNIT_B_NUM%% &mdash; %%UNIT_B_TOPIC_EN%%</button>
  </div>

  <!-- UNIT A -->
  <div class="unit-panel active" id="unit0">
    <div class="unit-hdr">
      <div>
        <div class="unit-hdr-title">Unit %%UNIT_A_NUM%% &nbsp;&middot;&nbsp; %%UNIT_A_TOPIC_EN%% &nbsp; %%UNIT_A_TOPIC_CN%%</div>
        <div class="unit-hdr-meta">10 target words &nbsp;&middot;&nbsp; 7 parts</div>
      </div>
      <span class="unit-level">%%LEVEL_LABEL%%</span>
    </div>
    <div class="part-nav" id="pn0">
      <button class="part-btn active" onclick="sP(0,0)">1 &middot; Vocabulary</button>
      <button class="part-btn" onclick="sP(0,1)">2 &middot; Story</button>
      <button class="part-btn" onclick="sP(0,2)">3 &middot; Comprehension</button>
      <button class="part-btn" onclick="sP(0,3)">4 &middot; Practice</button>
      <button class="part-btn" onclick="sP(0,4)">5 &middot; Speaking</button>
      <button class="part-btn" onclick="sP(0,5)">6 &middot; Writing</button>
      <button class="part-btn" onclick="sP(0,6)">7 &middot; Review</button>
    </div>
    <div class="part-panel active" id="u0p0"><div class="card"><div class="card-title">Click any word to expand its meaning</div><div id="vg0"></div></div></div>
    <div class="part-panel" id="u0p1"><div class="card"><div class="card-title">Mini story &mdash; target words are highlighted</div><div class="story-box"><div class="story-title">%%STORY_TITLE_A%%</div><div class="story-text" id="st0"></div></div></div></div>
    <div class="part-panel" id="u0p2">
      <div class="card"><div class="card-title">Section A &mdash; True or False &nbsp; &#21028;&#26029;&#23545;&#38ai;</div><div id="tf0"></div></div>
      <div class="card"><div class="card-title">Section B &mdash; Multiple Choice &nbsp; &#36873;&#25321;&#39064;</div><div id="mc0"></div></div>
    </div>
    <div class="part-panel" id="u0p3">
      <div class="card"><div class="card-title">Activity A &mdash; Match words with meanings</div><p style="font-size:13px;color:var(--mu);margin-bottom:.25rem">Click a word on the left, then click its matching meaning on the right.</p><div id="match0"></div><div id="match0-r"></div></div>
      <div class="card"><div class="card-title">Activity B &mdash; Fill in the blanks</div><p style="font-size:13px;color:var(--mu);margin-bottom:.75rem">Click a word from the box or type your answer.</p><div class="chips" id="chips0"></div><div id="fib0"></div><div class="btn-row"><button class="btn btn-p" onclick="chkFib(0)">Check answers</button><button class="btn btn-g" onclick="rstFib(0)">Reset</button></div><div id="fib0-s"></div></div>
    </div>
    <div class="part-panel" id="u0p4"><div class="card"><div class="card-title">Speaking practice &mdash; answer aloud</div><div id="spk0"></div><div class="hint">%%SPEAK_HINTS_A%%</div></div></div>
    <div class="part-panel" id="u0p5"><div class="card"><div class="card-title">Writing practice</div><p class="wp">%%WRITE_EN_A%%</p><p class="wp-cn">%%WRITE_CN_A%%</p><textarea class="wa" id="wr0" placeholder="Start writing here&hellip;"></textarea><div class="wc" id="wc0">0 words</div></div></div>
    <div class="part-panel" id="u0p6"><div class="card"><div class="rev-cols"><div><div class="rev-col-lbl" style="color:var(--teal)">Today's words &#20170;&#26085;&#21333;&#35789;</div><div id="rev0"></div></div><div><div class="rev-col-lbl" style="color:var(--gold)">Collocations &#24120;&#35265;&#25442;&#35774;</div><div id="col0"></div></div></div></div></div>
  </div>

  <!-- UNIT B -->
  <div class="unit-panel" id="unit1">
    <div class="unit-hdr">
      <div>
        <div class="unit-hdr-title">Unit %%UNIT_B_NUM%% &nbsp;&middot;&nbsp; %%UNIT_B_TOPIC_EN%% &nbsp; %%UNIT_B_TOPIC_CN%%</div>
        <div class="unit-hdr-meta">10 target words &nbsp;&middot;&nbsp; 7 parts</div>
      </div>
      <span class="unit-level">%%LEVEL_LABEL%%</span>
    </div>
    <div class="part-nav" id="pn1">
      <button class="part-btn active" onclick="sP(1,0)">1 &middot; Vocabulary</button>
      <button class="part-btn" onclick="sP(1,1)">2 &middot; Story</button>
      <button class="part-btn" onclick="sP(1,2)">3 &middot; Comprehension</button>
      <button class="part-btn" onclick="sP(1,3)">4 &middot; Practice</button>
      <button class="part-btn" onclick="sP(1,4)">5 &middot; Speaking</button>
      <button class="part-btn" onclick="sP(1,5)">6 &middot; Writing</button>
      <button class="part-btn" onclick="sP(1,6)">7 &middot; Review</button>
    </div>
    <div class="part-panel active" id="u1p0"><div class="card"><div class="card-title">Click any word to expand its meaning</div><div id="vg1"></div></div></div>
    <div class="part-panel" id="u1p1"><div class="card"><div class="card-title">Mini story &mdash; target words are highlighted</div><div class="story-box"><div class="story-title">%%STORY_TITLE_B%%</div><div class="story-text" id="st1"></div></div></div></div>
    <div class="part-panel" id="u1p2">
      <div class="card"><div class="card-title">Section A &mdash; True or False &nbsp; &#21028;&#26029;&#23545;&#38ai;</div><div id="tf1"></div></div>
      <div class="card"><div class="card-title">Section B &mdash; Multiple Choice &nbsp; &#36873;&#25321;&#39064;</div><div id="mc1"></div></div>
    </div>
    <div class="part-panel" id="u1p3">
      <div class="card"><div class="card-title">Activity A &mdash; Match words with meanings</div><p style="font-size:13px;color:var(--mu);margin-bottom:.25rem">Click a word on the left, then click its matching meaning on the right.</p><div id="match1"></div><div id="match1-r"></div></div>
      <div class="card"><div class="card-title">Activity B &mdash; Fill in the blanks</div><p style="font-size:13px;color:var(--mu);margin-bottom:.75rem">Click a word from the box or type your answer.</p><div class="chips" id="chips1"></div><div id="fib1"></div><div class="btn-row"><button class="btn btn-p" onclick="chkFib(1)">Check answers</button><button class="btn btn-g" onclick="rstFib(1)">Reset</button></div><div id="fib1-s"></div></div>
    </div>
    <div class="part-panel" id="u1p4"><div class="card"><div class="card-title">Speaking practice &mdash; answer aloud</div><div id="spk1"></div><div class="hint">%%SPEAK_HINTS_B%%</div></div></div>
    <div class="part-panel" id="u1p5"><div class="card"><div class="card-title">Writing practice</div><p class="wp">%%WRITE_EN_B%%</p><p class="wp-cn">%%WRITE_CN_B%%</p><textarea class="wa" id="wr1" placeholder="Start writing here&hellip;"></textarea><div class="wc" id="wc1">0 words</div></div></div>
    <div class="part-panel" id="u1p6"><div class="card"><div class="rev-cols"><div><div class="rev-col-lbl" style="color:var(--teal)">Today's words &#20170;&#26085;&#21333;&#35789;</div><div id="rev1"></div></div><div><div class="rev-col-lbl" style="color:var(--gold)">Collocations &#24120;&#35265;&#25442;&#35774;</div><div id="col1"></div></div></div></div></div>
  </div>
</div>

<script>
const D=%%DATA_JS%%;

const MS=[{sel:null,done:[]},{sel:null,done:[]}];
const FI=[[],[]];
let SH=[null,null];

function sU(u){
  document.querySelectorAll('.unit-btn').forEach((b,i)=>b.classList.toggle('active',i===u));
  document.querySelectorAll('.unit-panel').forEach((p,i)=>p.classList.toggle('active',i===u));
}
function sP(u,p){
  document.querySelectorAll(`#pn${u} .part-btn`).forEach((b,i)=>b.classList.toggle('active',i===p));
  for(let i=0;i<7;i++){const e=document.getElementById(`u${u}p${i}`);if(e)e.classList.toggle('active',i===p);}
}

function bVocab(u){
  const g=document.getElementById('vg'+u);if(g.children.length)return;
  D[u].words.forEach((w,i)=>{
    const d=document.createElement('div');d.className='vi';
    d.innerHTML=`<div class="vh" onclick="tV(${u},${i})"><span class="vw">${w.w}</span><span class="vp">${w.p}</span><span class="vc">${w.cn}</span><span class="vt" id="vt${u}${i}">+ more</span></div><div class="vb" id="vb${u}${i}"><div class="vm">${w.m}</div><div class="ve">"${w.eg}"</div></div>`;
    g.appendChild(d);
  });
}
function tV(u,i){
  const b=document.getElementById(`vb${u}${i}`),t=document.getElementById(`vt${u}${i}`);
  const o=b.classList.toggle('open');t.textContent=o?'- less':'+ more';
}

function bStory(u){
  const el=document.getElementById('st'+u);if(el.innerHTML)return;
  let h='';
  D[u].story.forEach(para=>{
    if(h)h+='<br><br>';
    para.forEach(s=>{if(typeof s==='string')h+=s;else h+=`<span class="hw">${s.h}</span>`;});
  });
  el.innerHTML=h;
}

function bTF(u){
  const el=document.getElementById('tf'+u);if(el.innerHTML)return;
  D[u].tf.forEach((x,i)=>{
    const r=document.createElement('div');r.className='tf-row';
    r.innerHTML=`<span class="tf-q">${i+1}. ${x.q}</span><div class="tf-btns"><button class="tf-btn" id="tT${u}${i}" onclick="dTF(${u},${i},true)">T</button><button class="tf-btn" id="tF${u}${i}" onclick="dTF(${u},${i},false)">F</button></div><span class="tf-res" id="tR${u}${i}"></span>`;
    el.appendChild(r);
  });
}
function dTF(u,i,v){
  const c=D[u].tf[i].a;
  const tB=document.getElementById(`tT${u}${i}`),fB=document.getElementById(`tF${u}${i}`),r=document.getElementById(`tR${u}${i}`);
  tB.disabled=fB.disabled=true;
  if(v===c){(v?tB:fB).classList.add('correct');r.textContent='✓ Correct';r.style.color='var(--ok)';}
  else{(v?tB:fB).classList.add('wrong');(c?tB:fB).classList.add('correct');r.textContent='✗ Incorrect';r.style.color='var(--er)';}
}

function bMC(u){
  const el=document.getElementById('mc'+u);if(el.innerHTML)return;
  D[u].mc.forEach((x,qi)=>{
    const b=document.createElement('div');b.className='mc-block';
    b.innerHTML=`<div class="mc-q">${qi+1}. ${x.q}</div><div class="mc-opts">${x.o.map((o,oi)=>`<button class="mc-opt" id="mc${u}${qi}${oi}" onclick="dMC(${u},${qi},${oi})">${String.fromCharCode(65+oi)}. ${o}</button>`).join('')}</div>`;
    el.appendChild(b);
  });
}
function dMC(u,qi,oi){
  const c=D[u].mc[qi].a;
  for(let i=0;i<4;i++){const b=document.getElementById(`mc${u}${qi}${i}`);if(b){b.disabled=true;if(i===c)b.classList.add('correct');else if(i===oi)b.classList.add('wrong');}}
}

function bMatch(u){
  const el=document.getElementById('match'+u);if(el.innerHTML)return;
  const m=D[u].match;
  SH[u]=m.defs;
  const g=document.createElement('div');g.className='match-grid';
  m.words.forEach((w,i)=>{
    const wb=document.createElement('button');wb.className='mw';wb.id=`mw${u}${i}`;wb.textContent=w;wb.onclick=()=>pW(u,i);g.appendChild(wb);
    const db=document.createElement('button');db.className='md';db.id=`md${u}${i}`;db.textContent=m.defs[i];db.onclick=()=>pD(u,i);g.appendChild(db);
  });
  el.appendChild(g);
}
function pW(u,i){
  if(document.getElementById(`mw${u}${i}`).classList.contains('done'))return;
  document.querySelectorAll(`[id^="mw${u}"]`).forEach(b=>{if(!b.classList.contains('done'))b.classList.remove('sel');});
  document.getElementById(`mw${u}${i}`).classList.add('sel');
  MS[u].sel=i;
}
function pD(u,di){
  if(document.getElementById(`md${u}${di}`).classList.contains('done'))return;
  document.querySelectorAll(`[id^="md${u}"]`).forEach(b=>{if(!b.classList.contains('done'))b.classList.remove('sel','err');});
  document.getElementById(`md${u}${di}`).classList.add('sel');
  if(MS[u].sel===null)return;
  const wi=MS[u].sel;
  const correct_di=D[u].match.correct[wi];
  const wB=document.getElementById(`mw${u}${wi}`),dB=document.getElementById(`md${u}${di}`);
  if(di===correct_di){
    wB.classList.remove('sel');wB.classList.add('done');
    dB.classList.remove('sel');dB.classList.add('done');
    MS[u].done.push(wi);
    if(MS[u].done.length===D[u].match.words.length){
      document.getElementById(`match${u}-r`).innerHTML=`<div class="score-bar good" style="margin-top:.75rem"><span class="score-n">5/5</span><span class="score-l">All matched correctly!</span></div>`;
    }
  } else {
    dB.classList.add('err');
    setTimeout(()=>{if(dB)dB.classList.remove('err','sel');},700);
    wB.classList.remove('sel');
  }
  MS[u].sel=null;
}

function bFib(u){
  const ce=document.getElementById('chips'+u),fe=document.getElementById('fib'+u);
  if(ce.innerHTML)return;
  D[u].fib.chips.forEach(c=>{
    const s=document.createElement('span');s.className='chip';s.id=`ch${u}${c}`;s.textContent=c;
    s.onclick=()=>{const active=document.activeElement;if(active&&active.classList.contains('fib-i')&&!active.value){active.value=c;s.classList.add('used');}};
    ce.appendChild(s);
  });
  D[u].fib.rows.forEach((r,i)=>{
    const row=document.createElement('div');row.className='fib-row';
    row.innerHTML=`<span class="fib-n">${i+1}.</span><span>${r.pre}</span><input class="fib-i" id="fi${u}${i}" autocomplete="off" placeholder="&hellip;"/><span>${r.suf}</span>`;
    fe.appendChild(row);
    FI[u].push(document.getElementById(`fi${u}${i}`));
  });
}
function chkFib(u){
  let ok=0;const n=D[u].fib.rows.length;
  D[u].fib.rows.forEach((r,i)=>{
    const inp=FI[u][i];const v=inp.value.trim().toLowerCase();const a=r.ans.toLowerCase();
    inp.classList.remove('correct','wrong');
    if(v===a||v===a+'s'||v===a+'d'||v===a+'ed'){inp.classList.add('correct');ok++;}else inp.classList.add('wrong');
  });
  document.getElementById(`fib${u}-s`).innerHTML=`<div class="score-bar${ok===n?' good':''}" style="margin-top:.5rem"><span class="score-n">${ok}/${n}</span><span class="score-l">${ok===n?'Perfect! All correct!':ok>n/2?'Good effort! Check the red ones.':'Keep trying!'}</span></div>`;
}
function rstFib(u){
  D[u].fib.rows.forEach((_,i)=>{const inp=FI[u][i];inp.value='';inp.classList.remove('correct','wrong');});
  D[u].fib.chips.forEach(c=>{const ch=document.getElementById(`ch${u}${c}`);if(ch)ch.classList.remove('used');});
  document.getElementById(`fib${u}-s`).innerHTML='';
}

function bSpeak(u){
  const el=document.getElementById('spk'+u);if(el.innerHTML)return;
  D[u].speak.forEach((q,i)=>{
    const d=document.createElement('div');d.className='speak-card';
    d.innerHTML=`<span class="speak-n">${i+1}.</span><span>${q}</span>`;
    el.appendChild(d);
  });
}

function bRev(u){
  const re=document.getElementById('rev'+u),co=document.getElementById('col'+u);if(re.innerHTML)return;
  D[u].rev.forEach(([en,cn])=>{const d=document.createElement('div');d.className='ri';d.innerHTML=`<span class="r-en">${en}</span><span class="r-cn">${cn}</span>`;re.appendChild(d);});
  D[u].col.forEach(([en,cn])=>{const d=document.createElement('div');d.className='ci';d.innerHTML=`<div class="c-en">${en}</div><div class="c-cn">${cn}</div>`;co.appendChild(d);});
}

function setupWC(u){
  const ta=document.getElementById('wr'+u),wc=document.getElementById('wc'+u);
  ta.addEventListener('input',()=>{const n=ta.value.trim().split(/\s+/).filter(w=>w).length;wc.textContent=n+' word'+(n!==1?'s':'');});
}

[0,1].forEach(u=>{bVocab(u);bStory(u);bTF(u);bMC(u);bMatch(u);bFib(u);bSpeak(u);bRev(u);setupWC(u);});
</script>
</body>
</html>"""

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate IELTS Workbook unit pair HTML")
    parser.add_argument("--units", help="e.g. 9-10 (default: auto-detect)")
    parser.add_argument("--level", type=int, default=2, choices=[1, 2, 3])
    parser.add_argument("--model", default="claude-opus-4-5")
    args = parser.parse_args()

    # Resolve unit numbers
    if args.units:
        m = re.match(r"(\d+)[-–](\d+)", args.units)
        if not m:
            sys.exit("❌  --units must be in the form 9-10")
        unit_a, unit_b = int(m.group(1)), int(m.group(2))
    else:
        unit_a, unit_b = get_next_unit_pair()

    print(f"🎯  Generating Units {unit_a}–{unit_b}  (Level {args.level})")

    # Read input
    source_text, source_name = read_input()

    # Call API
    data = call_api(source_text, args.level, args.model)

    # Build HTML
    html = build_html(data, unit_a, unit_b, args.level)

    # Save
    out_name = f"IELTS_Workbook_Units{unit_a}-{unit_b}.html"
    out_path = BASE_DIR / out_name
    out_path.write_text(html, encoding="utf-8")
    print(f"✅  Saved: {out_name}")
    print(f"    Topics: {data['unit_a']['topic_en']} · {data['unit_b']['topic_en']}")
    print(f"\nNext steps:")
    print(f"  1. Open {out_name} in your browser to review")
    print(f"  2. Update index.html to mark Units {unit_a}–{unit_b} as available")
    print(f"  3. git add {out_name} && git commit -m 'Add Units {unit_a}-{unit_b}' && git push")

if __name__ == "__main__":
    main()
