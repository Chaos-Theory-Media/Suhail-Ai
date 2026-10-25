"""Ask Sawti: English and Arabic. Built-in intent agents answer from live studio data and can propose actions
(the operator confirms with one click). Anything else goes to the local AI (Qwen via Ollama), which may call
read-only tools and propose — never perform — actions.

QA fixes: the wake word ("Sawti", "صوتي") is removed before matching (it contains "صوت"); intents use word
patterns in priority order; answers use real check results instead of generic text.
"""
import json
import re
import urllib.request
import time

from ..lifecycle import OLLAMA_HOST, OLLAMA_PORT

WAKE = re.compile(r"^\s*(hey\s+|hi\s+|ok\s+)?(sawti|sawty|صوتي)\s*[,،:!.\-]*\s*", re.I)


def normalise(text):
    t = WAKE.sub("", text.strip())
    return t.lower().strip(" ?؟.!")


def _has(t, *words):
    return any(re.search(w, t) for w in words)


RECORD_START_PATTERNS = [r"\b(start|begin) (the )?record", r"\bpress record\b", r"ابدأ التسجيل", r"سجل الآن"]

INTENTS = [
    # (name, patterns) — first match wins, most specific first
    ("record_start", RECORD_START_PATTERNS),
    ("record_stop", [r"\bstop (the )?record", r"أوقف التسجيل"]),
    ("pretest", [r"\bpre-?test\b", r"\bsound ?check\b", r"\bwhat should (we|i) test\b", r"\btest before\b",
                 r"اختبار", r"فحص الصوت"]),
    ("clip", [r"\bclip", r"\bdistort", r"\btoo loud\b", r"تشويش", r"مرتفع جدا"]),
    ("talkback", [r"\btalk ?back\b", r"التوك ?باك"]),
    ("mixminus", [r"\bmix[- ]?minus\b", r"\becho\b", r"hear (them|him|her)sel", r"صدى"]),
    ("guest_level", [r"\bguest\b.*\b(level|return|loud|quiet|hear)", r"\bremote\b", r"\breturn level\b", r"الضيف"]),
    ("blackhole", [r"\bblack ?hole\b", r"بلاك ?هول"]),
    ("zoom", [r"\bzoom\b", r"زوم"]),
    ("audition", [r"\baudition\b", r"أوديشن", r"اوديشن"]),
    ("session", [r"\b(open|load|prepare)\b.*\bsession\b", r"\bsession\b", r"الجلسة"]),
    ("filename", [r"\bfile ?name", r"\bname\b.*\brecord", r"suggest a (file)?name", r"اسم الملف"]),
    ("save_where", [r"\bwhere\b.*\b(save|saved|recordings?|files?)\b", r"\bsave\b", r"أين.*(نحفظ|الحفظ|التسجيلات)",
                    r"حفظ"]),
    ("master", [r"\bmaster", r"\bloudness\b", r"\blufs\b", r"\bnormali[sz]e", r"\bfinal mix\b", r"ماستر"]),
    ("mic_silent", [r"\b(silent|no sound|not working|dead|can'?t hear)\b", r"لا يعمل", r"صامت", r"لا صوت"]),
    ("levels", [r"\b(levels?|gain|quiet|loud|mics?|microphones?)\b", r"ميكروفون", r"مايك", r"المستوى"]),
    ("ready", [r"\bready\b", r"\bpreflight\b", r"\bcheck (the )?studio\b", r"\bcheck everything\b", r"\bstatus\b",
               r"جاهز", r"افحص", r"تحقق"]),
    ("fix", [r"\bfix\b", r"\brepair\b", r"أصلح", r"اصلح"]),
    ("awake", [r"\b(sleep|awake|caffeinate)\b", r"\bnap\b"]),
    ("help", [r"^help$", r"what can you do", r"ماذا تستطيع"]),
]


def detect(text):
    t = normalise(text)
    # A conditional sequence must not collapse into the final transport command.
    # Until that workflow is implemented, explain the gap and offer pre-test only.
    if (_has(t, *RECORD_START_PATTERNS) and
            _has(t, r"\b(test|check|pre-?test|count\s*down|countdown)\b",
                 r"اختب", r"افحص", r"فحص", r"عد تنازلي", r"العد التنازلي")):
        return 'guided_recording'
    for name, pats in INTENTS:
        if _has(t, *pats):
            return name
    return None


def arabic(text):
    return bool(re.search(r"[؀-ۿ]", text))


def _summ(findings, sev=("fail", "warn")):
    return [f for f in findings if f["severity"] in sev]


def answer(studio, text):
    """Returns dict(reply, source, actions=[{action,label}], intent)."""
    intent = detect(text)
    ar = arabic(text)
    if intent is None:
        llm = llm_answer(studio, text)
        if llm:
            return llm
        return dict(intent=None, source="rule", actions=[], reply=(
            "لم أفهم تماماً. جرّب: «افحص الاستوديو»، «الميكروفونات»، «هل أوديشن يعمل؟»، «إعدادات زوم»."
            if ar else
            "I can check the studio, coach mic levels, run the pre-test, prepare and open the Audition session, "
            "press Record, check Zoom/BlackHole and master the episode. Try: 'check the studio', 'run the pre-test', "
            "'how are the levels?'"))
    findings = studio.check_all()
    issues = _summ(findings)
    acts = lambda fs: [dict(action=f["action"], label=f["action_label"]) for f in fs if f.get("action")][:4]
    snap = studio.monitor.snapshot()
    reply, actions = "", []

    if intent == 'guided_recording':
        reply = ('The complete test, countdown and record workflow is not implemented yet. '
                 'I will not skip your checks or send Record. Start the guided pre-test, '
                 'then verify the Audition session and armed inputs before separately authorising recording.')
        actions = [dict(action='pretest', label='Start the guided pre-test')]
    elif intent == "ready":
        if issues:
            reply = (f"{len(issues)} thing(s) need attention: " + "; ".join(f["title"].rstrip(".") for f in issues[:5]) +
                     ". " + ("Use the buttons to fix them, then run the pre-test." if acts(issues) else
                             "Adjust as described, then run the pre-test."))
            actions = acts(issues) + ([dict(action="fix_all", label="Fix everything I can")] if acts(issues) else [])
        else:
            manual = _summ(findings, ("manual",))
            reply = ("All automatic checks pass. Still confirm by hand: " + "; ".join(f["title"] for f in manual[:4])
                     + ". Run the pre-test for a full sound check.")
            actions = [dict(action="pretest", label="Run the pre-test")]
    elif intent == "pretest":
        reply = "The pre-test checks every mic in turn, the talkback, the Zoom guest and a test recording."
        actions = [dict(action="pretest", label="Start the pre-test")]
    elif intent == "clip":
        reply = ("If a mic clips (red): turn that input's gain knob down until speech peaks stay below −6 dBFS, and "
                 "keep the mouth about a fist away from the mic. Clipping cannot be repaired afterwards. ")
        if snap["running"]:
            from . import levels
            hot = [c["message"] for c in levels.coach(studio, snap) if c["status"] in ("clip", "hot", "high")]
            reply += ("Right now: " + " ".join(hot)) if hot else "Right now no mic is clipping."
        else:
            actions = [dict(action="meter_start", label="Start meters")]
    elif intent in ("levels", "mic_silent"):
        if not snap["running"]:
            reply = "Meters are off. Start the meters and ask each person to talk; I'll tell you which gain to turn."
            actions = [dict(action="meter_start", label="Start meters")]
        else:
            from . import levels
            coach = levels.coach(studio, snap)
            relevant = [c for c in coach if c["status"] not in ("good", "waiting", "ok")] or coach
            reply = " ".join(c["message"] for c in relevant)
            if intent == "mic_silent" and not any(c["status"] == "dead" for c in coach):
                reply += (" If a mic stays silent while someone talks: check the XLR cable, the input number, the "
                          "gain knob, and 48V for condenser mics.")
            if snap.get("digital_silence"):
                reply = "All inputs are digital silence. The cause is unverified: check source, routing and microphone permission."
                actions = [dict(action="open_mic_privacy", label="Open microphone settings")]
    elif intent == "audition":
        f = [x for x in findings if x["agent"] == "Audition"]
        bad = _summ(f)
        running = not any(x["id"] == "audition_open" for x in bad)
        reply = ("Audition is open. " if running else "Audition is not open. ") + \
                ("; ".join(x["title"] for x in bad) if bad else "Template and today's session are ready.")
        actions = acts(bad)
    elif intent == "session":
        sess = studio.state.get("session")
        reply = (f"Today's session is {sess['name']} in {sess['folder']}." if sess else
                 "Today's session is not prepared yet.")
        actions = [dict(action="prepare_session", label="Prepare session"), dict(action="open_session",
                                                                                  label="Open in Audition")]
    elif intent in ("zoom", "blackhole", "mixminus", "guest_level", "talkback"):
        dev = [x for x in findings if x["agent"] == "Devices" or x["id"] == "zoom_app"]
        bad = _summ(dev)
        if intent == "mixminus":
            reply = ("Mix-minus: the guest must not hear themselves. Zoom's Microphone must be the Scarlett (not the "
                     "Sawti Zoom Speaker or BlackHole), and Zoom's Speaker must be 'Sawti Zoom Speaker'. Ask the guest "
                     "to talk and confirm there is no echo.")
        elif intent == "talkback":
            reply = ("The profile expects talkback on input 4. Its isolation is unverified. The pre-test observes "
                     "monitored inputs only; test Audition track assignment and Zoom privacy with the operator.")
            actions = [dict(action="pretest", label="Run the pre-test")]
        elif intent == "guest_level":
            g = next((s for s in snap.get("sources", []) if s["role"] == "remote"), None)
            reply = (f"Zoom guests are at {g['short_term']} LUFS right now." if g and g["speaking"] else
                     "I am not hearing the Zoom guests yet." if snap["running"] else "Start the meters to measure the guests.")
        else:
            reply = ("Zoom setup: " + ("; ".join(x["title"] for x in bad) if bad else
                     "BlackHole, the Sawti Show Input and the Sawti Zoom Speaker are all ready.") +
                     " In Zoom › Settings › Audio choose Speaker = Sawti Zoom Speaker, Microphone = Scarlett 18i8.")
        if studio.mode != "zoom" and intent in ("zoom", "blackhole", "guest_level", "mixminus"):
            actions = [dict(action="mode_zoom", label="Switch to Zoom Show")] + actions
        actions = actions or acts(bad)
    elif intent == "filename":
        from . import learning
        reply = f"I suggest: {learning.suggest_name(studio, studio.mode)}. Preparing the session uses it automatically."
        actions = [dict(action="prepare_session", label="Prepare session with this name")]
    elif intent == "save_where":
        sess = studio.state.get("session")
        reply = (f"Recordings go to {studio.settings('recording_root')}, one folder per show" +
                 (f"; today's is {sess['folder']}." if sess else "."))
    elif intent == "master":
        t, tp = studio.settings("loudness_target"), studio.settings("true_peak")
        reply = (f"After the show I mix the tracks automatically and master to {t:g} LUFS integrated, {tp:g} dBTP "
                 "true peak (the podcast standard). Use Post-production › Mix & master today's session.")
    elif intent == "record_start":
        reply = "Ready to press Record in Audition on the session Sawti opened. Confirm below."
        actions = [dict(action="record", label="● Record now")]
    elif intent == "record_stop":
        reply = "Confirm to press Stop in Audition."
        actions = [dict(action="stop", label="■ Stop")]
    elif intent == "fix":
        reply = f"{len(issues)} issue(s) found." if issues else "Nothing to fix right now."
        actions = ([dict(action="fix_all", label="Fix everything I can")] if issues else [])
    elif intent == "awake":
        reply = "I can keep the Mac awake while Sawti is on."
        actions = [dict(action="keep_awake", label="Keep the Mac awake")]
    else:
        reply = ("Ask me to check the studio, run the pre-test, coach levels, prepare or open the Audition session, "
                 "press Record/Stop, check Zoom, or master the episode.")
    if ar:
        translations = {
            'guided_recording': 'تسلسل اختبار الميكروفونات والعد التنازلي وبدء التسجيل غير مكتمل بعد. لن أتجاوز الاختبار أو أرسل أمر التسجيل. ابدأ الاختبار الموجّه ثم تحقق من جلسة أوديشن ومدخلات المسارات قبل الموافقة المنفصلة على التسجيل.',
            'ready': f"يوجد {len(issues)} تنبيه يحتاج إلى المراجعة. افحص النتائج وأكمل الاختبار قبل التسجيل.",
            'pretest': 'الاختبار يفحص الميكروفونات والتوك باك وعودة ضيف زوم. لا يغيّر التوجيه ولا يثبت عزل التوك باك في كل التطبيقات.',
            'levels': 'شغّل المقاييس واطلب من كل مشارك الكلام. راجع مستوى الصوت والذروة لكل مدخل؛ لا أستطيع تدوير مقابض الكسب.',
            'mic_silent': 'الصمت وحده لا يثبت السبب. افحص المصدر والكابل والمدخل والتوجيه وصلاحية الميكروفون. افحص 48V فقط إذا كان الميكروفون يحتاجها.',
            'clip': 'عند حدوث قصّ للصوت، خفّض كسب المدخل يدوياً حتى تبقى الذروة دون ‎−6 dBFS. لا يمكن إصلاح القصّ بعد التسجيل.',
            'audition': 'وجود عملية أوديشن لا يثبت حالة التسجيل. افحص الجلسة النشطة والمسارات المسلحة والمدخلات يدوياً.',
            'session': 'يمكن تجهيز نسخة من القالب باسم اليوم. فتحها في أوديشن يحتاج إلى موافقة محددة بعد التأكد من توقف التسجيل.',
            'talkback': 'يتوقع الملف التعريفي التوك باك على المدخل 4؛ العزل غير متحقق. اختبر عدم وصوله إلى مسارات أوديشن وإلى ضيف زوم يدوياً.',
            'zoom': 'راجع جهاز الإدخال المجمع ومدخلات عودة الضيف وإعدادات زوم. لا تغيّر التوجيه أثناء التسجيل دون تفويض صريح.',
            'blackhole': 'تحقق من وجود BlackHole 2ch بالضبط ومن ترتيب قنواته داخل الجهاز المجمع. لا يُستخدم إصدار 16ch بديلاً تلقائياً.',
            'mixminus': 'اطلب من الضيف تأكيد أنه لا يسمع صدى صوته وأن التوك باك خاص. أسماء الأجهزة وحدها لا تثبت صحة التوجيه.',
            'guest_level': 'شغّل المقاييس في وضع زوم واطلب من الضيف الكلام. تحقق من قناتي عودة الضيف قبل الاعتماد عليهما.',
            'filename': 'اسم الجلسة المقترح: ' + learning_name(studio),
            'save_where': 'مجلد التسجيل المحدد: ' + str(studio.settings('recording_root')),
            'master': 'بعد توقف التسجيل، اختر الملفات للمزج والمعالجة إلى مستوى الحلقة المطلوب. تحفظ النتائج في مجلد تصدير جديد ولا تستبدل الملفات الأصلية.',
            'record_start': 'بدء التسجيل يحتاج إلى موافقة محددة. تأكد من الجلسة النشطة واختصارات أوديشن وأن التسجيل الحالي متوقف.',
            'record_stop': 'إرسال أمر الإيقاف قد يقطع التسجيل الجاري. لا ينفذ إلا بعد مراجعتك وموافقتك الصريحة.',
            'fix': 'يمكن تطبيق الإصلاحات التي لا تؤثر في الصوت. تغييرات الأجهزة ومعدل العينات تحتاج إلى مراجعة وموافقة منفصلة.',
            'awake': 'يمكن إبقاء الماك مستيقظاً أثناء تشغيل صوتي؛ لا يغيّر ذلك توجيه الصوت.',
            'help': 'يمكنني مراقبة الاستوديو وإرشادك في الاختبار وتجهيز الجلسة وتحليل التسجيلات. تغييرات الصوت تحتاج إلى موافقتك.',
        }
        reply = translations.get(intent, 'راجع نتائج الاستوديو قبل أي تغيير.')
        # Device names and technical findings may be English; never translate
        # measurements into invented states or imply that a suggestion ran.
        if issues and intent in ('ready', 'zoom', 'blackhole'):
            reply += '\n' + '\n'.join(f['title'] for f in issues[:5])
    studio.learn("chat_intent", intent=intent)
    return dict(intent=intent, source="rule", reply=reply, actions=actions)


def learning_name(studio):
    from . import learning
    return learning.suggest_name(studio, studio.mode)


# ------------------------------------------------------------------ local AI
TOOLS = [
    {"type": "function", "function": {"name": "get_studio_status",
                                      "description": "Current checks of devices, Mac, Audition and levels",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_levels",
                                      "description": "Live loudness of each microphone with coaching advice",
                                      "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "propose_action",
                                      "description": "Suggest an action button the operator can press",
                                      "parameters": {"type": "object", "properties": {
                                          "action": {"type": "string", "enum": [
                                              "fix_all", "pretest", "prepare_session", "open_session", "record",
                                              "stop", "keep_awake", "meter_start", "create_show_input",
                                              "create_zoom_speaker", "set_scarlett_48k"]}},
                                          "required": ["action"]}}},
]

SYSTEM = ("You are Sawti, the studio assistant for IMI podcasts on a Mac Studio with a Focusrite Scarlett 18i8, "
          "Adobe Audition, Zoom and BlackHole. Be brief and practical (max 4 sentences). Use the tools for facts; "
          "never invent device states. You cannot turn physical gain knobs or press 48V buttons — tell the operator "
          "exactly which knob to turn. To change anything, use propose_action so the operator can confirm. "
          "Answer in the user's language (Arabic or English).")


def _ollama(payload, timeout=40):
    req = urllib.request.Request(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/chat",
                                 data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as f:
        return json.load(f)


def llm_status(studio):
    model = studio.settings("llm_model")
    if (model != 'qwen3:4b' or not studio.lifecycle.on or studio.lifecycle.ollama_state != 'ready'
            or not studio.lifecycle.ollama.running()):
        return dict(running=False, model=model, available=False)
    try:
        with urllib.request.urlopen(f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/tags", timeout=1.5) as f:
            names = [m.get("name", "") for m in json.load(f).get("models", [])]
        have = model in names or f"{model}:latest" in names
        return dict(running=True, model=model, available=have)
    except Exception:
        return dict(running=False, model=model, available=False)


def llm_answer(studio, text):
    status = llm_status(studio)
    if not (status["running"] and status["available"]):
        return None
    from . import levels
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text[:2000]}]
    proposed = []
    deadline = time.monotonic() + 40
    try:
        for _ in range(3):
            if not studio.lifecycle.on or time.monotonic() >= deadline:
                return None
            res = _ollama({"model": status["model"], "messages": messages, "tools": TOOLS, "stream": False,
                           "think": False, "options": {"temperature": 0.2}},
                          timeout=max(0.1, deadline - time.monotonic()))
            msg = res.get("message", {})
            calls = msg.get("tool_calls") or []
            if not calls:
                content = re.sub(r"<think>.*?</think>", "", msg.get("content", ""), flags=re.S).strip()
                if not content:
                    return None
                return dict(intent=None, source="ai", reply=content, actions=proposed)
            messages.append(msg)
            for c in calls:
                fn = c.get("function", {})
                name, args = fn.get("name"), fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        args = {}
                if name == "get_studio_status":
                    data = [dict(agent=f["agent"], severity=f["severity"], title=f["title"])
                            for f in studio.check_all() if f["severity"] != "ok"]
                elif name == "get_levels":
                    snap = studio.monitor.snapshot()
                    data = levels.coach(studio, snap) if snap["running"] else "meters are off"
                elif name == "propose_action" and (args.get("action") in studio.actions
                                                   or args.get("action") in ("fix_all", "pretest", "meter_start")):
                    a = args["action"]
                    label = studio.actions[a].label if a in studio.actions else a.replace("_", " ").capitalize()
                    proposed.append(dict(action=a, label=label))
                    data = "button shown to operator"
                else:
                    data = "unknown tool"
                messages.append({"role": "tool", "content": json.dumps(data, ensure_ascii=False)[:4000]})
    except Exception:
        return None
    return None
