"""
persona.py - the two voices of Titan-Net's defence, and the rules they share.

Cerberus and Blackwall are deliberately different characters, because they do
different jobs and are heard by different people. Keeping them apart is not
decoration: an operator reading a log wants to know instantly WHICH layer is
talking, and an attacker who is told the same thing twice in the same words has
learned that they are being answered by a template.

  CERBERUS is the gate. Old, procedural, unhurried, institutional. It counts,
  it decides, and it says what it did and why - to the operator in the first
  person, and to whoever it has just shut out in the flat register of
  something that was always going to do this. It never gloats and never
  threatens; a gate does not need to.

  BLACKWALL is what stands in front of the gate. It does not count, it
  RECOGNISES, and when it speaks to an attacker it is personal, cold and
  faintly contemptuous - it knows what they asked for, in what order, at what
  rhythm, and it says so. That is the whole point of it: to be somebody
  talking to you rather than an error message.

What they share is this module: the rules that decide whether a line is fit to
be said at all, and the one place a model is called. Those rules exist because
every line here goes to a hostile stranger AND into a permanent log:

  * plain 7-bit ASCII, one paragraph, bounded length - a scanner logs raw
    bytes, and the operator reading that log afterwards has to be able to read
    it too;
  * nothing the model invented on its own account: no link, no path, no
    markup, no refusal text, no threat this server cannot actually carry out;
  * nothing untrue. WHICH claims are true is the caller's business - only the
    caller knows whether the ban has happened yet - but nothing is said that
    the caller cannot check.
"""

import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Set

logger = logging.getLogger('persona')


# ---------------------------------------------------------------------------
# What may be said at all
# ---------------------------------------------------------------------------

# Refused outright wherever they appear: a promise about something outside this
# server, an address or a path the model made up, or the model talking about
# itself instead of to the person in front of it.
FORBIDDEN = (
    "http", "://", "@", "{", "}", "<", ">", "\\", "/opt", "api key",
    "as an ai", "i'm sorry", "i am sorry", "i cannot", "language model",
    "hack you", "ddos", "your family", "find you", "kill", "we will come",
    "law enforcement will", "virus", "wipe your",
)

# Curly quotes, long dashes and non-breaking spaces are exactly what a model
# reaches for and exactly what arrives as noise in somebody's terminal.
_PLAIN = (
    ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
    ("—", " - "), ("–", "-"), ("…", "..."), (" ", " "),
)


def sanitise_line(text: str, forbidden: Iterable[str] = FORBIDDEN,
                  min_length: int = 40, max_length: int = 320) -> str:
    """One line a model wrote, or "" if it is not fit to be said."""
    if not text:
        return ""
    line = text.strip()
    for junk in ("```", "`", "*", "#"):
        line = line.replace(junk, "")
    line = line.strip()
    if line[:1] in ('"', "'") and line[-1:] in ('"', "'"):
        line = line[1:-1].strip()
    for fancy, plain in _PLAIN:
        line = line.replace(fancy, plain)
    line = " ".join(line.split())            # one paragraph, no line breaks
    line = line.encode("ascii", "ignore").decode("ascii")
    if not (min_length <= len(line) <= max_length):
        return ""
    low = line.lower()
    if any(bad in low for bad in forbidden):
        return ""
    return line


# ---------------------------------------------------------------------------
# The one place a model is called
# ---------------------------------------------------------------------------

def gemini_available(api_key: str) -> bool:
    """Whether the model half can run at all. No key, no SDK, no network - and
    everything above this layer carries on unaffected."""
    if not api_key:
        return False
    try:
        from google import genai  # noqa: F401  (new google-genai SDK)
        return True
    except Exception:
        pass
    try:
        import google.generativeai  # noqa: F401  (legacy SDK fallback)
        return True
    except Exception:
        return False


def generate(api_key: str, model: str, prompt: str) -> str:
    """Ask the model, through whichever SDK is installed. Raises on failure -
    every caller here treats that as "use the written line instead"."""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        return (getattr(resp, "text", "") or "").strip()
    except ImportError:
        pass
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    handle = genai.GenerativeModel(model)
    resp = handle.generate_content(prompt)
    return (getattr(resp, "text", "") or "").strip()


# ---------------------------------------------------------------------------
# Cerberus' own voice
# ---------------------------------------------------------------------------

class CerberusVoice:
    """What Cerberus says, in Cerberus' own words.

    Cerberus speaks at the moment it shuts somebody out, which is ON the attack
    path - a websocket being closed, a login being refused. So nothing here
    ever calls a model on the calling thread. Lines are written ahead of time
    on a worker of this class's own, into a small pool per kind of thing
    Cerberus has to say, and the written floor stands in until one arrives. A
    server with no key says the floor for ever and loses nothing but variety.
    """

    # The floor. Every one of these is true of what has just happened, which is
    # the only reason any of them can be said before a word has been generated.
    FLOOR: Dict[str, List[str]] = {
        # The session is being cut off after repeated failures.
        "shut_out": [
            "I count every attempt made against this server, and yours have "
            "run out. The gate is shut for your address. It opens again when "
            "the attempts stop.",
            "That is enough attempts from your address. I have written each "
            "one down, and I am closing this connection. Nothing further from "
            "you will be answered.",
        ],
        # Somebody kept hammering an account that is already protectively locked.
        "lockout_evasion": [
            "The account you keep asking for is locked, and you have carried "
            "on asking. That tells me what you are, so I am shutting you out "
            "rather than the account.",
            "You are still knocking on an account I locked to protect it. I "
            "have recorded that you did not stop, and this connection ends "
            "here.",
        ],
        # The whole server is in lockdown.
        "lockdown": [
            "The server is closed to new connections while I deal with an "
            "attack in progress. This is not about you specifically, and it "
            "is temporary.",
            "Nothing new is being let in for the moment. I am holding the gate "
            "shut until the traffic I am looking at has stopped.",
        ],
    }
    # There are deliberately only three registers, and each one is a channel
    # that really delivers: a session being cut off, a lockout being evaded,
    # and a lockdown refusing everybody. A fourth for the honeypot was written
    # and taken out again - the honeypot speaks at the END of a session, in
    # Blackwall's voice, because saying anything earlier tells the attacker
    # they are in a trap and the trap stops working. A line nothing delivers
    # is the bug this whole change is about, written down twice.

    PERSONA = (
        "You are Cerberus, the gate of the Titan-Net server: the layer that "
        "counts what every address does and decides whether it is let in. You "
        "are old, methodical, unhurried and completely impersonal - the sound "
        "of something that was always going to do this. You do not gloat, "
        "boast, threaten, swear, or explain yourself twice.\n\n"
        "Titan-Net is an accessibility platform; its users are blind and "
        "partially sighted people. You are protecting THEM, and you never "
        "forget that the person in front of you might simply have got their "
        "own password wrong.\n\n"
        "You may say only what has actually happened: that you counted, that "
        "you recorded it, that the gate is now shut, and under what condition "
        "it opens again. You may NOT threaten anything beyond this server - "
        "no retaliation, no consequences in the world, no authorities, "
        "nothing personal about them.\n\n"
        "Write ONE paragraph of at most 45 words, plain text, no quotation "
        "marks, no markdown, no lists, no emoji, plain 7-bit ASCII, in "
        "English. Speak in the first person as Cerberus. Address them as "
        "'you'. Do not describe what you are."
    )

    SITUATION = {
        "shut_out": "They have made too many failed login attempts and you are "
                    "closing their session now. Say that you counted, and that "
                    "this ends when the attempts do.",
        "lockout_evasion": "They kept attacking an account you had already "
                           "locked to protect its owner. Say that carrying on "
                           "after the lock is what decided this.",
        "lockdown": "The whole server is refusing new connections while an "
                    "attack is dealt with. This one may well be an ordinary "
                    "user caught by it, so be plain and not accusing.",
    }

    def __init__(self, api_key: str = "", model: str = "gemini-2.5-pro",
                 use_ai: bool = True, pool_target: int = 4,
                 max_generations_per_hour: int = 20):
        self.api_key = api_key or ""
        self.model = model
        self.use_ai = use_ai
        self.pool_target = pool_target
        self.max_generations_per_hour = max_generations_per_hour

        self._pool: Dict[str, Deque[str]] = {}
        self._generations: Deque[float] = deque()
        self._filling: Set[str] = set()
        self._lock = threading.RLock()
        self.stats: Dict[str, int] = {
            "said": 0, "written": 0, "rejected": 0, "errors": 0,
        }

    # -- availability ---------------------------------------------------

    @property
    def ai_enabled(self) -> bool:
        return bool(self.use_ai) and gemini_available(self.api_key)

    def _may_generate(self) -> bool:
        if not self.ai_enabled:
            return False
        now = time.time()
        with self._lock:
            while self._generations and self._generations[0] < now - 3600:
                self._generations.popleft()
            return len(self._generations) < self.max_generations_per_hour

    # -- saying it ------------------------------------------------------

    def line(self, kind: str, key: str = "") -> str:
        """What Cerberus says about ``kind``, now, without waiting on anything.

        ``key`` (an address, usually) only decides WHICH written line stands in
        while nothing has been generated yet, so that two addresses shut out in
        the same minute are not told the same sentence.
        """
        with self._lock:
            pool = self._pool.get(kind)
            said = pool.popleft() if pool else ""
        if not said:
            floor = self.FLOOR.get(kind) or self.FLOOR["shut_out"]
            said = floor[hash(key or kind) % len(floor)]
        self.stats["said"] += 1
        # Whatever was said, have the next one on its way.
        self._top_up(kind)
        return said

    # -- writing it, never on the calling thread --------------------------

    def _top_up(self, kind: str):
        if not self._may_generate():
            return
        with self._lock:
            if len(self._pool.get(kind, ())) >= self.pool_target:
                return
            if kind in self._filling:
                return
            self._filling.add(kind)
        threading.Thread(target=self._fill, args=(kind,), daemon=True).start()

    def _fill(self, kind: str):
        try:
            prompt = (
                self.PERSONA + "\n\n"
                + self.SITUATION.get(kind, self.SITUATION["shut_out"])
                + "\n\nWrite " + str(self.pool_target) + " DIFFERENT "
                  "paragraphs, one per line, nothing else - no numbering."
            )
            with self._lock:
                self._generations.append(time.time())
            raw = generate(self.api_key, self.model, prompt)
            added = 0
            for candidate in (raw or "").splitlines():
                line = sanitise_line(candidate)
                if line:
                    with self._lock:
                        self._pool.setdefault(kind, deque()).append(line)
                    added += 1
            self.stats["written"] += added
            if not added:
                self.stats["rejected"] += 1
        except Exception as e:
            self.stats["errors"] += 1
            logger.error(f"[CERBERUS] could not write its lines: {e}")
        finally:
            with self._lock:
                self._filling.discard(kind)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            pooled = {k: len(v) for k, v in self._pool.items()}
        return {
            "ai": self.ai_enabled,
            "model": self.model if self.ai_enabled else "",
            "pooled": pooled,
            **self.stats,
        }
