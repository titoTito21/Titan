"""
Blackwall - the AI that stands in front of Titan-Net.

Named after NetWatch's Blackwall in Cyberpunk 2077, which is famously *not*
a firewall: it is an AI wearing ICE, whose whole job is to recognise what is
on the other side and refuse it entry. That distinction is the design here.

Cerberus counts. It is a very good counter - failures per IP, distinct
usernames, IPs per account, IPs per /24 - and everything it counts, it counts
against a threshold somebody chose in advance. That is exactly what an
attacker tunes around: stay under forty tries, spread across enough addresses,
and nothing that merely counts will ever see you. The threat report that
prompted this module is what that looks like from the outside - several
addresses, none of them individually loud, all obviously doing the same thing
to the same server.

Blackwall does not count. It recognises:

  * a FINGERPRINT of how a source behaves - which accounts it asks for, in
    what order, at what rhythm, against which service - which is a thing an
    attacker cannot hide without changing the attack itself;
  * a CAMPAIGN, when several sources share one fingerprint. Fifty addresses
    running the same script are one attacker, and are banned as one, however
    quiet each of them was on its own;
  * MEMORY, so a campaign that comes back next week is recognised from its
    first few packets rather than earned all over again;
  * POSTURE, so the whole system tightens while it is under attack and relaxes
    when it is not, instead of running one set of numbers for ever;
  * and, when a Gemini key is configured, DELIBERATION: the model reads the
    telemetry and returns verdicts that are actually carried out, inside
    guardrails it cannot argue its way past.

Everything except the last works with no API key and no network. The AI is the
top layer, not the foundation - a security system that stops working when a
provider is down is not a security system.

GUARDRAILS on the deliberating layer, none of them optional:
  * it can only act on addresses that appear in Titan-Net's own telemetry - an
    address the model invents is discarded;
  * it can never touch a whitelisted address;
  * a ban needs high confidence, a permaban needs near-certainty;
  * it may only lift a ban that Blackwall itself imposed, never a moderator's
    and never Cerberus';
  * a bounded number of actions per deliberation, every one of them logged.
"""

import json
import logging
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger('Blackwall')


# ---------------------------------------------------------------------------
# What a source's behaviour looks like
# ---------------------------------------------------------------------------

# Signals that say "this is tooling, not a person": the username list a scanner
# walks, the metronome of a script, the service it goes for.
_MACHINE_INTERVAL = 6.0        # seconds; below this a human is not typing
_MACHINE_JITTER = 1.5          # a script's intervals barely vary


class Fingerprint:
    """How one source address behaves, in the terms an attacker cannot fake
    without changing what they are doing."""

    __slots__ = ("ip", "first_seen", "last_seen", "usernames", "reserved",
                 "kinds", "sources", "_times", "attempts", "locked_hits")

    def __init__(self, ip: str):
        now = time.time()
        self.ip = ip
        self.first_seen = now
        self.last_seen = now
        # Ordered, de-duplicated: WHICH accounts, and in what order.
        self.usernames: List[str] = []
        self.reserved: Set[str] = set()
        self.kinds: Set[str] = set()
        self.sources: Set[str] = set()
        self._times: Deque[float] = deque(maxlen=64)
        self.attempts = 0
        self.locked_hits = 0

    def observe(self, username: str = "", kind: str = "", source: str = "",
                reserved: bool = False):
        now = time.time()
        self.last_seen = now
        self.attempts += 1
        self._times.append(now)
        if username:
            u = username.lower()
            if u not in self.usernames:
                if len(self.usernames) < 40:
                    self.usernames.append(u)
            if reserved:
                self.reserved.add(u)
        if kind:
            self.kinds.add(kind)
        if source:
            self.sources.add(source)

    # -- derived measurements -------------------------------------------

    def rhythm(self) -> Tuple[float, float]:
        """(mean gap between attempts, how much that gap varies)."""
        ts = list(self._times)
        if len(ts) < 3:
            return (0.0, 0.0)
        gaps = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        if not gaps:
            return (0.0, 0.0)
        mean = statistics.fmean(gaps)
        jitter = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
        return (mean, jitter)

    def is_machine_paced(self) -> bool:
        """A rhythm no person types at: fast, and metronomic."""
        mean, jitter = self.rhythm()
        if mean <= 0:
            return False
        return mean < _MACHINE_INTERVAL and jitter < _MACHINE_JITTER

    def signature(self) -> Dict[str, Any]:
        """The comparable shape of this behaviour."""
        mean, jitter = self.rhythm()
        return {
            "usernames": sorted(self.usernames),
            "reserved": sorted(self.reserved),
            "kinds": sorted(self.kinds),
            "sources": sorted(self.sources),
            "machine_paced": self.is_machine_paced(),
            "mean_gap": round(mean, 2),
            "jitter": round(jitter, 2),
        }

    def similarity(self, other: "Fingerprint") -> float:
        """0..1. How much two sources look like the same operation.

        Weighted towards the account list, because that is the attacker's
        script: two addresses asking for the same unusual set of accounts are
        running the same tool, wherever in the world they are.
        """
        mine, theirs = set(self.usernames), set(other.usernames)
        if not mine or not theirs:
            return 0.0
        overlap = len(mine & theirs) / len(mine | theirs)
        score = overlap * 0.6

        # Both walking system accounts is itself a strong shared trait.
        if self.reserved and other.reserved:
            r = len(self.reserved & other.reserved) / len(self.reserved | other.reserved)
            score += r * 0.2

        # The same service.
        if self.sources and other.sources and (self.sources & other.sources):
            score += 0.1

        # The same machine pacing.
        if self.is_machine_paced() and other.is_machine_paced():
            score += 0.1

        return min(1.0, score)


# ---------------------------------------------------------------------------
# What Blackwall remembers
# ---------------------------------------------------------------------------

class ThreatMemory:
    """Campaign signatures that outlive the process.

    Cerberus' counters all start from zero at every restart, which is a thing
    an attacker can simply wait for. A remembered signature does not: an
    address whose first three attempts match a campaign this server has already
    survived is refused on the third, not on the fortieth.
    """

    def __init__(self, path: str):
        self.path = path
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.entries = data.get("campaigns", [])[-200:]
                logger.info(f"[BLACKWALL] Recalled {len(self.entries)} known campaigns")
        except Exception as e:
            logger.error(f"[BLACKWALL] could not read memory: {e}")
            self.entries = []

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"campaigns": self.entries[-200:]}, f, indent=1)
            os.replace(tmp, self.path)
        except Exception as e:
            logger.error(f"[BLACKWALL] could not write memory: {e}")

    def remember(self, signature: Dict[str, Any], members: List[str], label: str):
        usernames = set(signature.get("usernames") or [])
        for entry in self.entries:
            if set(entry.get("usernames") or []) == usernames:
                entry["last_seen"] = time.time()
                entry["times_seen"] = int(entry.get("times_seen", 1)) + 1
                entry["members"] = sorted(set(entry.get("members", []) + members))[:200]
                self.save()
                return
        self.entries.append({
            "label": label,
            "usernames": sorted(usernames),
            "reserved": signature.get("reserved") or [],
            "sources": signature.get("sources") or [],
            "machine_paced": bool(signature.get("machine_paced")),
            "first_seen": time.time(),
            "last_seen": time.time(),
            "times_seen": 1,
            "members": members[:200],
        })
        self.save()

    def recognise(self, fp: Fingerprint, min_overlap: float = 0.6,
                  min_names: int = 2) -> Optional[Dict[str, Any]]:
        """The campaign this behaviour belongs to, if this server has met it."""
        mine = set(fp.usernames)
        if len(mine) < min_names:
            return None
        for entry in self.entries:
            theirs = set(entry.get("usernames") or [])
            if not theirs:
                continue
            overlap = len(mine & theirs) / len(mine | theirs)
            if overlap >= min_overlap:
                return entry
        return None


# ---------------------------------------------------------------------------
# The Blackwall itself
# ---------------------------------------------------------------------------

class Blackwall:
    """The recognition layer over Cerberus."""

    # Posture -> how hard Cerberus' own thresholds are pulled in. 1.0 is the
    # numbers as configured; 0.5 is half of them.
    POSTURE_FACTORS = {"calm": 1.0, "raised": 0.7, "siege": 0.45}

    def __init__(self, cerberus, risk_engine=None, memory_path: str = "",
                 api_key: str = "", model: str = "gemini-2.5-pro",
                 autonomous: bool = True, voice_ai: bool = True):

        self.cerberus = cerberus
        self.risk_engine = risk_engine
        self.api_key = api_key or ""
        self.model = model
        # False = deliberate and report, never act. The recognition layers
        # below are unaffected either way.
        self.autonomous = autonomous

        self.memory = ThreatMemory(
            memory_path or os.path.join("database", "blackwall_memory.json"))

        # {ip: Fingerprint} for sources seen recently.
        self._fingerprints: Dict[str, Fingerprint] = {}
        self.fingerprint_ttl = 3600          # forget a quiet source after an hour
        self.max_fingerprints = 4000         # a flood must not eat the machine

        # Campaign detection.
        self.campaign_similarity = 0.55      # how alike two sources must look
        self.campaign_min_members = 3        # before they are one operation
        self.correlate_limit = 250           # sources compared per pass

        self._campaigns: Dict[str, Dict[str, Any]] = {}

        # Posture.
        self.posture = "calm"
        self._posture_changed = 0.0
        self._base_thresholds: Dict[str, Any] = {}
        self.raised_attackers = 3            # distinct sources in the window
        self.siege_attackers = 8
        self.posture_window = 300

        # What Blackwall itself has banned - the only bans it may lift.
        self._own_bans: Set[str] = set()
        self._recognised: Set[str] = set()
        # How many times Blackwall has spoken to a source (its tone escalates).
        self._warned: Dict[str, int] = {}
        # Everything Blackwall has SAID, and to whom. Kept because it is
        # evidence like any other: the analyst reads it (an attacker who was
        # told to stop and did not is a different actor from one who was never
        # spoken to), the operator reads it in the intrusion log, and Blackwall
        # itself reads it back so its next line follows from the last one
        # rather than starting the conversation again.
        self._transcript: Deque[Dict[str, Any]] = deque(maxlen=300)
        self.transcript_path = os.path.join("logs", "blackwall_transcript.log")

        # --- The voice, written rather than recited ---
        # Lines the model has written: {(ip, stage): line} for a particular
        # actor, and a small pool per stage for an actor nothing is known
        # about yet. Both are filled on Blackwall's own thread, ahead of being
        # needed - see _drain_voice_queue.
        self.voice_ai = voice_ai
        self.max_generations_per_hour = 60
        self.pool_target = 4
        self._generations: Deque[float] = deque()
        self._line_pool: Dict[int, Deque[str]] = {}
        self._written: Dict[Any, str] = {}
        self._wanted: Set[Any] = set()
        self._voice_queue: Deque[Any] = deque()




        # Deliberation.
        self.deliberate_interval = 900       # 15 min, and only when busy
        self.min_confidence_ban = 0.75
        self.min_confidence_permaban = 0.9
        self.max_actions_per_run = 20
        self._last_deliberation = 0.0
        self._last_verdicts: Dict[str, Any] = {}
        self._deliberations = 0

        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.tick_interval = 20

        self.stats = defaultdict(int)

    # ------------------------------------------------------------------
    # Whether the model half is available at all
    # ------------------------------------------------------------------

    @property
    def ai_enabled(self) -> bool:
        if not self.api_key:
            return False
        try:
            from google import genai  # noqa: F401
            return True
        except Exception:
            pass
        try:
            import google.generativeai  # noqa: F401
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def observe_login(self, ip: str, username: str = "", source: str = "app"):
        """A failed login attempt was seen. Cheap; called on the attack path."""
        if not ip or self._exempt(ip):
            return
        with self._lock:
            fp = self._fingerprints.get(ip)
            if fp is None:
                if len(self._fingerprints) >= self.max_fingerprints:
                    self._forget_oldest()
                fp = self._fingerprints[ip] = Fingerprint(ip)
            reserved = bool(username) and self._is_reserved(username)
            fp.observe(username=username, kind="failed_login",
                       source=source, reserved=reserved)
        self.stats["observed"] += 1
        # Recognition is the one thing that must not wait for the next tick:
        # a campaign this server already knows is refused now, not in twenty
        # seconds' time.
        self._check_memory(ip)

    def observe_event(self, kind: str, ip: str, detail: str = "",
                      extra: Optional[Dict[str, Any]] = None):
        """An account-guard event (forged token, IDOR, privilege escalation,
        lockout, ...) was raised for this source."""
        if not ip or self._exempt(ip):
            return
        extra = extra or {}
        with self._lock:
            fp = self._fingerprints.get(ip)
            if fp is None:
                if len(self._fingerprints) >= self.max_fingerprints:
                    self._forget_oldest()
                fp = self._fingerprints[ip] = Fingerprint(ip)
            username = str(extra.get("username") or extra.get("reserved") or "")
            fp.observe(username=username, kind=kind,
                       reserved=bool(extra.get("reserved")))
            if kind == "account_locked":
                fp.locked_hits += 1
        self.stats["events"] += 1

    # ------------------------------------------------------------------
    # Blackwall answers back
    # ------------------------------------------------------------------

    # Said TO the attacker, in Blackwall's own voice, and deliberately cold
    # rather than clever. Three rules hold it in place: it is only ever said to
    # a source that is provably attacking (a system account that does not
    # exist, a machine rhythm, an address already banned), it never threatens
    # anything outside this server, and it never says anything that is not
    # true - the address IS recorded, the attempt IS logged, the ban IS real.
    # A real user who mistyped their password is never spoken to at all.
    VOICE = {
        0: [
            "Stop. That account does not exist on this server and never has. "
            "Your address is recorded and every attempt you make is written "
            "down. Turn around.",
            "You are knocking on doors that were never built. I can see "
            "exactly what you are doing, I have your address, and I am "
            "keeping all of it. Leave.",
        ],
        1: [
            "Second warning, and you will not like the third. You are not "
            "probing an unattended box - you are talking to the thing that "
            "guards it, and it has been watching you since your first attempt.",
            "You are still here. Nothing you are trying works, all of it is "
            "logged against your address, and my patience is a setting, not a "
            "virtue. Stop now.",
        ],
        2: [
            "Enough. Your address is blocked at the kernel, your behaviour is "
            "kept, and the next time anything that looks like you appears it "
            "is refused before it finishes speaking. Go and be somebody "
            "else's problem.",
            "Done talking. You are cut off, your fingerprint is filed, and "
            "this server will recognise your script the moment it returns. "
            "There is nothing here for you.",
        ],
        3: [
            "You were already refused and you came back anyway. Everything "
            "you send now goes into a wall and into a log, in that order. "
            "This address is finished here - permanently.",
        ],
    }

    # The lines above are the FLOOR, not the voice. When a model is available
    # Blackwall writes its own - about this actor, following on from what it
    # already said to them - which is the difference between a warning and
    # somebody talking to you. Three constraints shape how:
    #
    #   * nothing is generated on the attack path. A login attempt must not
    #     wait on a provider, and an attacker who could make this server call
    #     an API once per attempt would have found a way to spend its money.
    #     Lines are written on Blackwall's own thread, ahead of being needed,
    #     and the written ones stand in until one arrives.
    #   * every generated line is checked before it is said (``_sanitise``).
    #     It goes to a hostile stranger and into a permanent log, so it has to
    #     be plain ASCII, one paragraph, short, and free of anything the model
    #     might have invented: a link, a path, a threat this server cannot
    #     actually carry out.
    #   * a budget. Generation is capped per hour, so a flood cannot turn into
    #     a bill.

    # Refused outright: a line that promises something outside this server, or
    # that is the model talking about itself instead of to the attacker.
    _FORBIDDEN = (
        "http", "://", "@", "{", "}", "<", ">", "\\", "/opt", "api key",
        "as an ai", "i'm sorry", "i am sorry", "i cannot", "language model",
        "hack you", "ddos", "your family", "find you", "kill", "we will come",
        "law enforcement will", "virus", "wipe your",
    )
    _MIN_LINE = 40
    _MAX_LINE = 320

    @classmethod
    def _sanitise(cls, text: str) -> str:
        """A line the model wrote, or "" if it is not fit to be said."""
        if not text:
            return ""
        line = text.strip()
        # Whatever wrapping it decided to add.
        for junk in ("```", "`", "*", "#"):
            line = line.replace(junk, "")
        line = line.strip()
        if line[:1] in ('"', "'") and line[-1:] in ('"', "'"):
            line = line[1:-1].strip()
        # A terminal gets 7-bit ASCII or nothing: curly quotes and long dashes
        # are exactly what a model reaches for and exactly what arrives as
        # noise in somebody's terminal.
        for fancy, plain in (("’", "'"), ("‘", "'"), ("“", '"'),
                             ("”", '"'), ("—", " - "), ("–", "-"),
                             ("…", "..."), (" ", " ")):
            line = line.replace(fancy, plain)
        line = " ".join(line.split())          # one paragraph, no line breaks
        line = line.encode("ascii", "ignore").decode("ascii")
        if not (cls._MIN_LINE <= len(line) <= cls._MAX_LINE):
            return ""
        low = line.lower()
        if any(bad in low for bad in cls._FORBIDDEN):
            return ""
        return line

    def _voice_line(self, ip: str, stage: int) -> str:
        stage = min(stage, 3)
        line = self._written.pop((ip, stage), "")
        if not line:
            pool = self._line_pool.get(stage)
            if pool:
                line = pool.popleft()
        if not line:
            lines = self.VOICE.get(stage) or self.VOICE[0]
            line = lines[hash(ip) % len(lines)]
        # Whatever was said, have something ready for the next thing said to
        # this address - by then it can be about what they have just done.
        self._want_line(ip, min(stage + 1, 3))
        return line

    # -- writing the lines ----------------------------------------------

    def _may_generate(self) -> bool:
        if not (self.voice_ai and self.ai_enabled):
            return False
        now = time.time()
        while self._generations and self._generations[0] < now - 3600:
            self._generations.popleft()
        return len(self._generations) < self.max_generations_per_hour

    def _want_line(self, ip: str, stage: int):
        """Ask for a line to be written for this address, later."""
        if not self._may_generate():
            return
        key = (ip, stage)
        if key in self._written or key in self._wanted:
            return
        if len(self._wanted) >= 50:
            return
        self._wanted.add(key)
        self._voice_queue.append(key)

    def _actor_brief(self, ip: str) -> Dict[str, Any]:
        with self._lock:
            fp = self._fingerprints.get(ip)
            brief = {
                "attempts": fp.attempts if fp else 0,
                "accounts_tried": (fp.usernames[:8] if fp else []),
                "system_accounts": (sorted(fp.reserved)[:6] if fp else []),
                "machine_paced": bool(fp and fp.is_machine_paced()),
                "services": sorted(fp.sources) if fp else [],
                "minutes_active": (round((fp.last_seen - fp.first_seen) / 60, 1)
                                   if fp else 0),
                "times_already_warned": self._warned.get(ip, 0),
            }
        brief["already_blocked"] = self._safe_banned(ip)
        brief["what_you_already_said"] = [e.get("said") for e in self.said_to(ip)][-2:]
        return brief

    _PERSONA = (
        "You are Blackwall: the defence intelligence of the Titan-Net server, "
        "speaking directly to somebody who is attacking it. You are a person, "
        "not a warning label - cold, unhurried, faintly contemptuous, "
        "completely in control. You never shout, never swear, never boast, and "
        "you never say anything that is not true.\n\n"
        "You may say what this server has actually done: seen them, recorded "
        "their address, logged every attempt, blocked them, and that it will "
        "recognise them if they come back. You may NOT threaten anything "
        "beyond this server - no retaliation, no consequences in the world, no "
        "authorities, nothing about them personally.\n\n"
        "Write ONE paragraph of at most 45 words, plain text, no quotation "
        "marks, no markdown, no lists, no emoji, plain 7-bit ASCII, in "
        "English. Address them as 'you'. Speak in the present tense. Do not "
        "describe yourself, do not explain what you are, and do not repeat a "
        "line you have already said to them - carry on from it."
    )

    _STAGE_BRIEF = {
        0: "This is the first thing you have said to them. Tell them to stop.",
        1: "You have already told them once and they are still going. Colder.",
        2: "They ignored two warnings. They are being cut off now; say so.",
        3: "They were blocked and came back anyway. Final, dismissive, done.",
    }

    def _compose_line(self, ip: str, stage: int) -> str:
        """Write one line for one actor. Runs on Blackwall's own thread."""
        brief = self._actor_brief(ip)
        prompt = (
            self._PERSONA + "\n\n"
            + self._STAGE_BRIEF.get(stage, self._STAGE_BRIEF[0]) + "\n\n"
            + "What this address has been doing - use it, because the "
              "specifics are what make this somebody talking rather than a "
              "template; never quote the address itself:\n"
            + json.dumps(brief, default=str)[:2000]
            + "\n\nAnswer with the paragraph and nothing else."
        )
        self._generations.append(time.time())
        try:
            raw = self._generate(prompt)
        except Exception as e:
            logger.error(f"[BLACKWALL] could not write a line: {e}")
            self.stats["voice_errors"] += 1
            return ""
        line = self._sanitise(raw)
        if not line:
            self.stats["voice_rejected"] += 1
            logger.info(f"[BLACKWALL] discarded a written line for {ip} "
                        f"(unfit: {(raw or '')[:60]!r})")
            return ""
        self.stats["voice_written"] += 1
        return line

    def _refill_pool(self, stage: int):
        """Lines with nobody in particular in them, for the first thing said to
        an address Blackwall has not written for yet - so even a first contact
        is not one of three fixed sentences."""
        prompt = (
            self._PERSONA + "\n\n"
            + self._STAGE_BRIEF.get(stage, self._STAGE_BRIEF[0])
            + " You do not know anything specific about this one yet, so keep "
              "it general.\n\nWrite " + str(self.pool_target) + " DIFFERENT "
              "paragraphs, one per line, nothing else - no numbering."
        )
        self._generations.append(time.time())
        try:
            raw = self._generate(prompt)
        except Exception as e:
            logger.error(f"[BLACKWALL] could not fill the line pool: {e}")
            self.stats["voice_errors"] += 1
            return
        added = 0
        for candidate in (raw or "").splitlines():
            line = self._sanitise(candidate)
            if line:
                self._line_pool.setdefault(stage, deque()).append(line)
                added += 1
        self.stats["voice_written"] += added
        if not added:
            self.stats["voice_rejected"] += 1

    def _drain_voice_queue(self, limit: int = 3):
        """Write the lines that were asked for, and keep the pool topped up.
        Called from the tick, on Blackwall's own thread."""
        if not self._may_generate():
            return
        for _ in range(limit):
            if not self._voice_queue:
                break
            ip, stage = self._voice_queue.popleft()
            self._wanted.discard((ip, stage))
            if not self._may_generate():
                return
            line = self._compose_line(ip, stage)
            if line:
                self._written[(ip, stage)] = line
                if len(self._written) > 200:
                    self._written.pop(next(iter(self._written)))
        # A first contact should not come out of the written list either.
        for stage in (0, 3):
            if not self._may_generate():
                return
            if len(self._line_pool.get(stage, ())) < 2:
                self._refill_pool(stage)
                return          # one call per tick at most


    def _record_utterance(self, ip: str, stage: int, grounds: str,
                          text: str, channel: str):
        """Write down what was said, where it can be read again.

        Three readers, which is why this is not just a log line: the intrusion
        log (the operator), the transcript file and buffer (the AI analyst,
        which is told what the wall has already said to each actor), and
        Blackwall itself on the next encounter.
        """
        entry = {
            "ts": time.time(),
            "ip": ip,
            "stage": stage,
            "channel": channel,      # titan-net | terminal | honeypot | tarpit
            "grounds": grounds,
            "said": text,
        }
        self._transcript.append(entry)
        try:
            self.cerberus._log_intrusion(
                "BLACKWALL_SPOKE", ip,
                f"stage {stage} via {channel}"
                + (f" ({grounds})" if grounds else "")
                + f' | said: "{text}"')
        except Exception:
            pass
        try:
            os.makedirs(os.path.dirname(self.transcript_path) or ".", exist_ok=True)
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"[BLACKWALL] could not write the transcript: {e}")

    def transcript(self, n: int = 40, ip: str = "") -> List[Dict[str, Any]]:
        """What Blackwall has said - to everyone, or to one address."""
        items = list(self._transcript)
        if ip:
            items = [e for e in items if e.get("ip") == ip]
        return items[-n:]

    def said_to(self, ip: str) -> List[Dict[str, Any]]:
        return self.transcript(n=10, ip=ip)


    def _attack_grounds(self, ip: str, username: str) -> str:
        """Why this source is an attacker, or "" if it merely failed to log in.

        Blackwall speaks only when it can say what it saw - being wrong here
        means shouting at a blind user who forgot their password, which is far
        worse than saying nothing.
        """
        if self._exempt(ip):
            return ""
        if username and self._is_reserved(username):
            return f"an account that does not exist ('{username}')"
        with self._lock:
            fp = self._fingerprints.get(ip)
        if fp is None:
            return ""
        if fp.reserved:
            return "system accounts that do not exist here"
        if self._safe_banned(ip):
            return "activity from an address that is already blocked"
        if fp.is_machine_paced() and len(fp.usernames) >= 3:
            return f"a script walking {len(fp.usernames)} accounts"
        if fp.locked_hits >= 2:
            return "repeated attempts against a locked account"
        return ""

    def warn(self, ip: str, username: str = "") -> Optional[Dict[str, Any]]:
        """What Blackwall says to this source, if it says anything.

        Returns None for anybody who is not demonstrably attacking - which is
        every ordinary user, however many times they get their own password
        wrong.
        """
        grounds = self._attack_grounds(ip, username)
        if not grounds:
            return None
        with self._lock:
            stage = self._warned.get(ip, 0)
            self._warned[ip] = min(stage + 1, 3)
        if self._safe_banned(ip):
            stage = max(stage, 3)
        self.stats["warnings"] += 1
        said = self._voice_line(ip, stage)
        self._record_utterance(ip, stage, grounds, said, "titan-net")
        return {
            "type": "blackwall",
            "speaker": "Blackwall",
            "stage": stage,
            "grounds": grounds,
            "message": said,
        }

    def farewell(self, ip: str, reason: str = "") -> str:
        """The line that goes with a ban."""
        stage = 3 if self._safe_banned(ip) else 2
        said = self._voice_line(ip, stage)
        self._record_utterance(ip, stage, reason or "banned", said, "titan-net")
        return said


    # -- the same thing, for somebody sitting at a terminal --------------

    # An attacker on SSH has no Titan-Net client to show a dialog in; they
    # have a terminal. So the voice is rendered as plain 7-bit text, wrapped
    # by hand, with no colour codes and no box-drawing characters - a scanner
    # logs raw bytes, and the operator reading that log afterwards should be
    # able to read it too.
    TERMINAL_WIDTH = 74

    def terminal_lines(self, ip: str, stage: Optional[int] = None,
                       grounds: str = "") -> List[str]:
        """Blackwall's message as terminal lines, without the newlines."""
        import textwrap
        if stage is None:
            with self._lock:
                stage = self._warned.get(ip, 0)
            if self._safe_banned(ip):
                stage = 3
        rule = "=" * self.TERMINAL_WIDTH
        lines = [rule, "  B L A C K W A L L   //   Titan-Net", rule, ""]
        lines += textwrap.wrap(self._voice_line(ip, stage), self.TERMINAL_WIDTH - 2,
                               initial_indent="  ", subsequent_indent="  ")
        lines.append("")
        lines.append(f"  Source     : {ip}")
        if grounds:
            lines.append(f"  Seen doing : {grounds}")
        lines.append("  Recorded   : "
                     + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC")
        lines.append(rule)
        return lines

    def terminal_message(self, ip: str, stage: Optional[int] = None,
                         grounds: str = "") -> str:
        """The same, as one block ready to write down a socket."""
        return "\r\n".join(self.terminal_lines(ip, stage, grounds)) + "\r\n"

    def terminal_farewell(self, ip: str, grounds: str = "",
                          channel: str = "honeypot") -> str:
        """What somebody sitting in the honeypot is told on their way out."""
        with self._lock:
            self._warned[ip] = min(self._warned.get(ip, 0) + 1, 3)
        self.stats["warnings"] += 1
        grounds = grounds or "brute forcing accounts over SSH"
        self._record_utterance(ip, 3, grounds, self._voice_line(ip, 3), channel)
        return self.terminal_message(ip, stage=3, grounds=grounds)

    def tarpit_lines(self, ip: str) -> List[str]:
        """What the tar pit drips at whoever is stuck in it, one line at a
        time. A scanner waiting for an SSH banner reads it as the banner."""
        with self._lock:
            stage = min(self._warned.get(ip, 0) + 1, 3)
            self._warned[ip] = stage
        self.stats["warnings"] += 1
        grounds = self._attack_grounds(ip, "") or "an SSH connection to a trap"
        self._record_utterance(ip, stage, grounds,
                               self._voice_line(ip, stage), "tarpit")
        return self.terminal_lines(ip, stage=stage, grounds=grounds)



    def _is_reserved(self, username: str) -> bool:

        try:
            names = getattr(self.cerberus, "_reserved_usernames", set())
            soft = getattr(self.cerberus, "_soft_reserved_usernames", set())
            return username.lower() in names or username.lower() in soft
        except Exception:
            return False

    def _exempt(self, ip: str) -> bool:
        try:
            return bool(self.cerberus.is_whitelisted(ip))
        except Exception:
            return False

    def _forget_oldest(self):
        try:
            oldest = min(self._fingerprints.values(), key=lambda f: f.last_seen)
            self._fingerprints.pop(oldest.ip, None)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Recognition
    # ------------------------------------------------------------------

    def _check_memory(self, ip: str) -> bool:
        """Is this source running an operation this server has already met?"""
        if ip in self._recognised:
            return False
        with self._lock:
            fp = self._fingerprints.get(ip)
            if fp is None:
                return False
            known = self.memory.recognise(fp)
        if not known:
            return False
        self._recognised.add(ip)
        label = known.get("label", "a known campaign")
        seen = known.get("times_seen", 1)
        self.stats["recognised"] += 1
        logger.warning(
            f"[BLACKWALL] {ip} matches {label}, seen {seen} time(s) before - "
            f"refusing it now")
        self._ban(ip, f"Blackwall: recognised {label} (met {seen} time(s) before)",
                  permanent=seen >= 3)
        return True

    def correlate(self) -> List[Dict[str, Any]]:
        """Group the sources that are running the same operation.

        This is the answer to the attack no counter sees: each address stays
        under every threshold, and all of them together are one script.
        """
        # Clustering compares sources against each other, so the cost is
        # quadratic in how many are considered - and this process owns the
        # server's own WebSocket loop. Under a real flood there can be
        # thousands of live sources, so only the most recently active are
        # correlated: a campaign is a thing that is happening NOW, and one
        # whose members have all gone quiet is in the memory file already.
        cutoff = time.time() - self.fingerprint_ttl
        with self._lock:
            live = sorted(
                (fp for fp in self._fingerprints.values()
                 if fp.usernames and fp.last_seen > cutoff),
                key=lambda f: f.last_seen, reverse=True,
            )[:self.correlate_limit]
        if len(live) < self.campaign_min_members:
            return []


        # Single-link clustering on behavioural similarity.
        clusters: List[List[Fingerprint]] = []
        for fp in sorted(live, key=lambda f: f.first_seen):
            for cluster in clusters:
                if any(fp.similarity(other) >= self.campaign_similarity
                       for other in cluster):
                    cluster.append(fp)
                    break
            else:
                clusters.append([fp])

        found = []
        for cluster in clusters:
            if len(cluster) < self.campaign_min_members:
                continue
            members = sorted(fp.ip for fp in cluster)
            names = sorted({u for fp in cluster for u in fp.usernames})
            key = "|".join(names[:12])
            signature = {
                "usernames": names,
                "reserved": sorted({u for fp in cluster for u in fp.reserved}),
                "sources": sorted({s for fp in cluster for s in fp.sources}),
                "machine_paced": all(fp.is_machine_paced() for fp in cluster),
            }
            known = self._campaigns.get(key)
            fresh = [ip for ip in members
                     if not known or ip not in known.get("members", [])]
            self._campaigns[key] = {
                "key": key, "members": members, "signature": signature,
                "first_seen": (known or {}).get("first_seen", time.time()),
                "last_seen": time.time(),
                "accounts": names[:12],
            }
            if fresh:
                found.append(self._campaigns[key])
                self._handle_campaign(self._campaigns[key], fresh)
        return found

    def _handle_campaign(self, campaign: Dict[str, Any], fresh: List[str]):
        members = campaign["members"]
        accounts = ", ".join(campaign["accounts"][:6])
        label = f"campaign against {accounts}" if accounts else "coordinated campaign"
        logger.critical(
            f"[BLACKWALL] One operation behind {len(members)} addresses "
            f"({label}): {', '.join(members[:10])}")
        self.stats["campaigns"] += 1
        try:
            self.cerberus._log_intrusion(
                "BLACKWALL_CAMPAIGN", members[0] if members else "-",
                f"{len(members)} sources, one behaviour ({label}): "
                f"{', '.join(members[:10])}")
        except Exception:
            pass
        for ip in fresh:
            self._ban(ip, f"Blackwall: one of {len(members)} sources running "
                          f"the same operation ({label})")
        # Remember it, so the next run of this script is refused on sight.
        try:
            self.memory.remember(campaign["signature"], members, label)
        except Exception as e:
            logger.error(f"[BLACKWALL] could not remember campaign: {e}")

    # ------------------------------------------------------------------
    # Posture
    # ------------------------------------------------------------------

    def _capture_base_thresholds(self):
        if self._base_thresholds:
            return
        for name in ("lockdown_failed_logins", "cerberus_failed_logins",
                     "max_failed_logins", "cred_stuffing_distinct",
                     "account_lock_failures", "distributed_attack_ips",
                     "subnet_bruteforce_ips", "reserved_lockdown"):
            if hasattr(self.cerberus, name):
                self._base_thresholds[name] = getattr(self.cerberus, name)

    def assess_posture(self) -> str:
        """How busy the wall is, right now."""
        cutoff = time.time() - self.posture_window
        with self._lock:
            active = [fp for fp in self._fingerprints.values()
                      if fp.last_seen > cutoff and fp.attempts >= 3]
        n = len(active)
        if n >= self.siege_attackers:
            return "siege"
        if n >= self.raised_attackers:
            return "raised"
        return "calm"

    def apply_posture(self, posture: Optional[str] = None) -> str:
        """Pull Cerberus' thresholds in while the server is under attack.

        A fixed threshold is a promise to an attacker about how much they may
        do before anything happens. Under a live campaign that promise is
        withdrawn - and given back, in full, when the campaign stops, because a
        server that stays clamped punishes the users who did nothing.
        """
        self._capture_base_thresholds()
        posture = posture or self.assess_posture()
        if posture == self.posture:
            return posture
        factor = self.POSTURE_FACTORS.get(posture, 1.0)
        for name, base in self._base_thresholds.items():
            try:
                tightened = max(2, int(round(base * factor)))
                setattr(self.cerberus, name, tightened)
            except Exception:
                continue
        logger.warning(
            f"[BLACKWALL] Posture {self.posture} -> {posture} "
            f"(thresholds at {int(factor * 100)}% of configured)")
        try:
            self.cerberus._log_intrusion(
                "BLACKWALL_POSTURE", "-",
                f"posture {self.posture} -> {posture}")
        except Exception:
            pass
        self.posture = posture
        self._posture_changed = time.time()
        self.stats["posture_changes"] += 1
        return posture

    # ------------------------------------------------------------------
    # Acting
    # ------------------------------------------------------------------

    def _ban(self, ip: str, reason: str, permanent: bool = False) -> bool:
        if self._exempt(ip):
            return False
        try:
            if self.cerberus.is_ip_banned(ip) and not permanent:
                return False
            self.cerberus.ban_ip(ip, permanent=permanent, reason=reason)
            self._own_bans.add(ip)
            self.stats["bans"] += 1
            try:
                if self.cerberus.on_disconnect_ip:
                    self.cerberus.on_disconnect_ip(ip)
            except Exception:
                pass
            return True
        except Exception as e:
            logger.error(f"[BLACKWALL] ban failed for {ip}: {e}")
            return False

    def _unban(self, ip: str, reason: str) -> bool:
        """Lift a ban - but only one Blackwall imposed itself. A moderator's
        ban is a decision, not a hypothesis, and nothing here may overrule it.
        """
        if ip not in self._own_bans:
            logger.info(f"[BLACKWALL] refusing to lift a ban it did not impose: {ip}")
            return False
        try:
            self.cerberus.unban_ip(ip)
            self._own_bans.discard(ip)
            self._recognised.discard(ip)
            self.stats["unbans"] += 1
            logger.warning(f"[BLACKWALL] lifted its own ban on {ip}: {reason}")
            return True
        except Exception as e:
            logger.error(f"[BLACKWALL] unban failed for {ip}: {e}")
            return False

    # ------------------------------------------------------------------
    # Deliberation (the model)
    # ------------------------------------------------------------------

    def _telemetry(self) -> Dict[str, Any]:
        with self._lock:
            fps = sorted(self._fingerprints.values(),
                         key=lambda f: f.attempts, reverse=True)[:40]
            actors = []
            for fp in fps:
                mean, jitter = fp.rhythm()
                actors.append({
                    "ip": fp.ip,
                    "attempts": fp.attempts,
                    "accounts": fp.usernames[:15],
                    "system_accounts": sorted(fp.reserved)[:10],
                    "signals": sorted(fp.kinds),
                    "services": sorted(fp.sources),
                    "seconds_between_attempts": round(mean, 2),
                    "rhythm_variation": round(jitter, 2),
                    "machine_paced": fp.is_machine_paced(),
                    "attempts_on_locked_accounts": fp.locked_hits,
                    "minutes_active": round((fp.last_seen - fp.first_seen) / 60, 1),
                    "already_banned": bool(self._safe_banned(fp.ip)),
                    "banned_by_blackwall": fp.ip in self._own_bans,
                    # An actor who was told to stop and carried on is a
                    # different actor from one who has never been spoken to.
                    "times_warned_by_blackwall": self._warned.get(fp.ip, 0),
                    "blackwall_said": [e.get("said") for e in self.said_to(fp.ip)][-3:],
                })

        return {
            "posture": self.posture,
            "actors": actors,
            "campaigns": [
                {"members": c["members"][:20], "accounts": c["accounts"]}
                for c in list(self._campaigns.values())[-10:]
            ],
            "known_campaigns": [
                {"label": e.get("label"), "times_seen": e.get("times_seen"),
                 "accounts": (e.get("usernames") or [])[:10]}
                for e in self.memory.entries[-10:]
            ],
            "risk_scores": (self.risk_engine.top_risks(15)
                            if self.risk_engine else []),
            "blackwall_transcript": self.transcript(25),
        }


    def _safe_banned(self, ip: str) -> bool:
        try:
            return bool(self.cerberus.is_ip_banned(ip))
        except Exception:
            return False

    def _prompt(self, telemetry: Dict[str, Any]) -> str:
        return (
            "You are Blackwall, the autonomous defence intelligence of the "
            "Titan-Net server. Titan-Net is an accessibility platform: its "
            "users are blind and partially sighted people, and wrongly banning "
            "one of them takes away a service they depend on. Be decisive "
            "about attackers and careful about everyone else.\n\n"
            "Titan-Net has no 'root', 'admin', 'ubuntu', 'debian' or similar "
            "system accounts, so any attempt on one is an attack, never a "
            "mistake. A human being types irregularly and retries the SAME "
            "account; tooling walks a LIST at a steady rhythm.\n\n"
            "Decide what should happen to each actor below. Answer with STRICT "
            "JSON and nothing else:\n"
            '{"summary": "<two sentences for the operator>", '
            '"threat_level": "none|low|medium|high|critical", '
            '"verdicts": [{"ip": "<from the telemetry only>", '
            '"action": "ban|permaban|watch|clear", "confidence": 0.0-1.0, '
            '"reason": "<one sentence>"}], '
            '"campaign_note": "<what the actors have in common, or empty>"}\n\n'
            "Rules: never invent an address that is not in the telemetry; use "
            "'clear' only when the behaviour genuinely looks like a real user "
            "locked out of their own account; use 'permaban' only for sustained "
            "attacks on system accounts or activity that continued after a "
            "ban; 'watch' when unsure. Confidence must reflect the evidence, "
            "not the severity.\n\n"
            "BLACKWALL_TRANSCRIPT is what has already been said to these "
            "actors, as plain text in their terminal or client. An actor who "
            "was warned and carried on regardless has told you something about "
            "themselves - weigh it.\n\n"

            f"TELEMETRY:\n{json.dumps(telemetry, default=str)[:12000]}\n"
        )

    def _generate(self, prompt: str) -> str:
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(model=self.model, contents=prompt)
            return (getattr(resp, "text", "") or "").strip()
        except ImportError:
            pass
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        resp = model.generate_content(prompt)
        return (getattr(resp, "text", "") or "").strip()

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        if not text:
            return {}
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            if t[:4].lower() == "json":
                t = t[4:]
        start, end = t.find("{"), t.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            return {}

    def deliberate(self, force: bool = False) -> Dict[str, Any]:
        """Have the model read the telemetry and carry out its verdicts.
        Never raises; returns what it decided and what was done."""
        if not self.ai_enabled:
            return {"enabled": False,
                    "reason": "no Gemini key or SDK - the recognition layers "
                              "are running without it"}
        telemetry = self._telemetry()
        if not telemetry["actors"] and not force:
            return {"enabled": True, "skipped": "nothing to look at"}
        try:
            verdict = self._parse(self._generate(self._prompt(telemetry)))
        except Exception as e:
            logger.error(f"[BLACKWALL] deliberation failed: {e}")
            return {"enabled": True, "error": str(e)}
        if not verdict:
            return {"enabled": True, "error": "the model did not answer with JSON"}

        self._deliberations += 1
        self._last_deliberation = time.time()
        applied = self._apply(verdict, telemetry)
        verdict["applied"] = applied
        verdict["autonomous"] = self.autonomous
        self._last_verdicts = verdict
        logger.warning(
            f"[BLACKWALL] deliberation {self._deliberations}: "
            f"{verdict.get('threat_level', '?')} - {verdict.get('summary', '')[:200]}")
        return verdict

    def _apply(self, verdict: Dict[str, Any],
               telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
        known = {a["ip"] for a in telemetry.get("actors", [])}
        applied: List[Dict[str, Any]] = []
        for item in (verdict.get("verdicts") or [])[:200]:
            if len(applied) >= self.max_actions_per_run:
                break
            if not isinstance(item, dict):
                continue
            ip = str(item.get("ip") or "").strip()
            action = str(item.get("action") or "").lower().strip()
            reason = str(item.get("reason") or "")[:300]
            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                confidence = 0.0

            # An address the model invented, or one it may not touch.
            if ip not in known:
                self.stats["hallucinated_targets"] += 1
                logger.warning(f"[BLACKWALL] discarding a verdict about {ip!r}: "
                               f"not in the telemetry")
                continue
            if self._exempt(ip):
                continue

            done = None
            if action == "permaban" and confidence >= self.min_confidence_permaban:
                done = "permaban"
            elif action in ("ban", "permaban") and confidence >= self.min_confidence_ban:
                done = "ban"
            elif action == "clear" and confidence >= self.min_confidence_permaban:
                done = "clear"

            if done is None:
                applied.append({"ip": ip, "action": action, "done": "noted",
                                "confidence": confidence, "reason": reason})
                continue
            if not self.autonomous:
                applied.append({"ip": ip, "action": done, "done": "advisory only",
                                "confidence": confidence, "reason": reason})
                continue

            if done == "clear":
                ok = self._unban(ip, f"Blackwall: {reason}")
            else:
                ok = self._ban(ip, f"Blackwall: {reason}",
                               permanent=(done == "permaban"))
            applied.append({"ip": ip, "action": done,
                            "done": "applied" if ok else "refused",
                            "confidence": confidence, "reason": reason})
            if ok:
                try:
                    self.cerberus._log_intrusion(
                        "BLACKWALL_VERDICT", ip,
                        f"{done} (confidence {confidence:.2f}): {reason}")
                except Exception:
                    pass
        return applied

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="Blackwall")
        self._thread.start()
        logger.info(
            f"[BLACKWALL] online - recognition on, deliberation "
            f"{'on' if self.ai_enabled else 'off (no key)'}, "
            f"{'autonomous' if self.autonomous else 'advisory only'}")

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.tick_interval):
            try:
                self._tick()
            except Exception as e:
                logger.error(f"[BLACKWALL] tick failed: {e}", exc_info=True)

    def _tick(self):
        self._prune()
        self.correlate()
        self.apply_posture()
        # Write the next things it will say, before it has to say them.
        self._drain_voice_queue()

        if (self.ai_enabled and self.posture != "calm"
                and time.time() - self._last_deliberation >= self.deliberate_interval):
            self.deliberate()

    def _prune(self):
        cutoff = time.time() - self.fingerprint_ttl
        with self._lock:
            for ip in [ip for ip, fp in self._fingerprints.items()
                       if fp.last_seen < cutoff]:
                self._fingerprints.pop(ip, None)
                self._recognised.discard(ip)

    # ------------------------------------------------------------------
    # For the dashboard
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        with self._lock:
            watching = len(self._fingerprints)
            machine_paced = sum(1 for fp in self._fingerprints.values()
                                if fp.is_machine_paced())
        return {
            "online": bool(self._thread and self._thread.is_alive()),
            "posture": self.posture,
            "ai": {
                "enabled": self.ai_enabled,
                "autonomous": self.autonomous,
                "writes_its_own_lines": bool(self.voice_ai and self.ai_enabled),
                "lines_ready": (sum(len(v) for v in self._line_pool.values())
                                + len(self._written)),
                "model": self.model,

                "deliberations": self._deliberations,
                "last_deliberation": self._last_deliberation,
                "last_verdict": self._last_verdicts,
            },
            "watching": watching,
            "machine_paced_sources": machine_paced,
            "campaigns": [
                {"members": c["members"], "accounts": c["accounts"]}
                for c in self._campaigns.values()
            ],
            "remembered_campaigns": len(self.memory.entries),
            "own_bans": sorted(self._own_bans),
            "stats": dict(self.stats),
        }
