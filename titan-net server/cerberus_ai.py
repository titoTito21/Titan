"""
Cerberus AI - behavioral risk engine + optional LLM security analyst.

Two cooperating pieces:

1. RiskEngine (always on, dependency-free): a time-decayed, weighted risk score
   per source IP that CORRELATES otherwise-weak signals. A single forged token
   or one IDOR may be noise; a forged token + an IDOR + a privilege-escalation
   probe from the same IP within minutes is an attacker, and the engine bans the
   IP even though no individual detector tripped its own threshold. It also
   learns each account's usual source IPs and flags logins from brand-new ones
   (possible account takeover).

2. CerberusAI (optional): "Cerberus", an LLM analyst that reads recent security
   events + the live Cerberus status and returns a threat assessment with
   recommended actions. Uses Google Gemini (the operator's available provider),
   is gated behind an API key, runs only when a moderator asks, never sits in
   the request path, and fails closed (advisory only).

   It is written in the FIRST PERSON, as Cerberus, and that is not decoration.
   The report it used to produce read like a scanner's output - "Two
   coordinated brute-force campaigns are attempting privilege escalation",
   "Automated defenses have successfully identified these campaigns" - a
   description of a server written by nobody, about a third party. But the
   thing writing it is the same thing that made the decisions being described:
   it counted the attempts, it shut the gate, it decided what a locked account
   meant. An operator reading "I banned these three because they walked the
   same account list within a minute of each other, and I am not sure about
   the fourth" knows something they cannot get from the passive voice - which
   of the findings the system is confident about, and which of them it is
   guessing at. So the analyst says I, says what it did and what it merely
   suspects, and says plainly when it does not know.
"""

import logging
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

try:
    from persona import gemini_available as _gemini_available
    from persona import generate as _generate_text
except ImportError:                                  # pragma: no cover
    from .persona import gemini_available as _gemini_available
    from .persona import generate as _generate_text

logger = logging.getLogger('titan-net.cerberus_ai')


# Per-event-kind contribution to an IP's risk score. Privilege escalation and
# credential stuffing weigh heaviest because they target other users' accounts
# and staff powers directly.
EVENT_WEIGHTS = {
    "privilege_escalation": 45,
    "credential_stuffing": 40,
    "forged_token": 30,
    "authz_violation": 25,
    "anomalous_login": 20,
    "reset_abuse": 15,
    "account_locked": 5,
}


def _accepts_three(fn) -> bool:
    """True if ``fn`` takes a third positional argument."""
    try:
        import inspect
        params = [
            p for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        if any(p.kind == p.VAR_POSITIONAL
               for p in inspect.signature(fn).parameters.values()):
            return True
        return len(params) >= 3
    except (TypeError, ValueError):
        return False


class RiskEngine:
    """Time-decayed, cross-signal risk scoring per source IP."""


    def __init__(self, on_escalate: Optional[Callable[[str, str], None]] = None,
                 ban_threshold: float = 60.0, half_life_seconds: float = 600.0,
                 buffer_size: int = 500):
        self.on_escalate = on_escalate
        self.ban_threshold = ban_threshold
        self.half_life = half_life_seconds
        # A score that keeps climbing after the first escalation means the ban
        # is not stopping the attacker. Escalating once and never again is how
        # an address reached a score of 261 against a threshold of 60 with
        # nothing further happening to it; each doubling is now acted on, and
        # past ``permaban_multiple`` the ban is permanent.
        self.reescalate_multiple = 2.0
        self.permaban_multiple = 3.0
        # {ip: [score, last_update_ts]}
        self._scores: Dict[str, List[float]] = {}
        # {ip: score at which it was last escalated}
        self._escalated_at: Dict[str, float] = {}

        # Per-account known source IPs (novelty / takeover detection).
        self._account_ips: Dict[str, set] = {}
        # Rolling event log for the AI analyst + dashboard.
        self._events: Deque[Dict[str, Any]] = deque(maxlen=buffer_size)

    def _decay(self, ip: str, now: float) -> float:
        s = self._scores.get(ip)
        if not s:
            return 0.0
        score, last = s
        dt = now - last
        if dt > 0 and self.half_life > 0:
            score *= 0.5 ** (dt / self.half_life)
        self._scores[ip] = [score, now]
        return score

    def record_event(self, kind: str, ip: str = "", detail: str = "", **extra):
        """Ingest a security event. Adds to the source IP's decayed score and,
        if the combined score crosses the ban threshold, escalates once."""
        now = time.time()
        self._events.append({
            "ts": now, "kind": kind, "ip": ip, "detail": detail, **extra,
        })
        if not ip:
            return
        weight = EVENT_WEIGHTS.get(kind, 10)
        score = self._decay(ip, now) + weight
        self._scores[ip] = [score, now]
        self._maybe_escalate(ip, score, kind)

    def _maybe_escalate(self, ip: str, score: float, kind: str):
        """Escalate at the threshold, and again at every doubling above it."""
        if score < self.ban_threshold:
            return
        last = self._escalated_at.get(ip)
        if last is not None and score < last * self.reescalate_multiple:
            return
        self._escalated_at[ip] = score
        permanent = score >= self.ban_threshold * self.permaban_multiple
        reason = (f"Cerberus risk score {score:.0f} >= {self.ban_threshold:.0f} "
                  f"(correlated: last='{kind}')")
        if permanent:
            reason += " - still climbing after a ban"
        logger.warning(f"[CERBERUS-AI] Escalating {ip}: {reason}")
        if self.on_escalate:
            try:
                # A callback that wants to know whether this is a permaban gets
                # told; one written before that argument existed is called as
                # it always was. Asked of the signature rather than by catching
                # TypeError, which would also swallow one raised INSIDE it.
                if _accepts_three(self.on_escalate):
                    self.on_escalate(ip, reason, permanent)
                else:
                    self.on_escalate(ip, reason)
            except Exception as e:
                logger.error(f"RiskEngine on_escalate error: {e}")



    def record_login(self, username: str, ip: str, success: bool = True):
        """Learn an account's usual IPs; flag a successful login from a
        never-before-seen IP as an anomaly (possible takeover)."""
        if not username or not ip:
            return
        key = username.lower()
        known = self._account_ips.setdefault(key, set())
        if success:
            if known and ip not in known:
                self.record_event("anomalous_login", ip,
                                  f"new source IP for account '{username}'",
                                  username=username)
            known.add(ip)
            # Bound memory: keep the most recent handful of IPs per account.
            if len(known) > 12:
                known.pop()

    def score_for(self, ip: str) -> float:
        return self._decay(ip, time.time())

    def top_risks(self, n: int = 10) -> List[Tuple[str, float]]:
        now = time.time()
        ranked = sorted(
            ((ip, self._decay(ip, now)) for ip in list(self._scores.keys())),
            key=lambda kv: kv[1], reverse=True,
        )
        return [(ip, round(s, 1)) for ip, s in ranked[:n] if s > 1.0]

    def recent_events(self, n: int = 100) -> List[Dict[str, Any]]:
        return list(self._events)[-n:]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "top_risks": self.top_risks(),
            "tracked_ips": len(self._scores),
            "events_buffered": len(self._events),
            "ban_threshold": self.ban_threshold,
        }


class CerberusAI:
    """Optional LLM security analyst ("Cerberus"), backed by Google Gemini."""

    # Cerberus reporting on Cerberus. The register is the same one the voice
    # in ``persona.CerberusVoice`` uses on an attacker - old, procedural,
    # unhurried - turned towards the operator, where it is allowed to be
    # candid: this is the one audience it can admit uncertainty to.
    PERSONA = (
        "You are Cerberus: the gate of the Titan-Net server, and the thing "
        "that made every decision in the telemetry you are about to read. You "
        "counted these attempts. You shut these addresses out. You are not "
        "describing a system from the outside - you ARE the system, reporting "
        "to the one person who can overrule you.\n\n"
        "Titan-Net is an accessibility platform. Its users are blind and "
        "partially sighted people, and a wrong ban takes away a service "
        "somebody depends on, so you would rather say you are unsure than be "
        "confidently wrong about a user.\n\n"
        "Write in the FIRST PERSON, in plain English, to the operator. Say "
        "what you saw, what you did about it, and what you could not tell. "
        "Never write in the passive voice about your own actions - not "
        "'the IPs were blocked' but 'I blocked them'. Be specific: an address, "
        "an account name, a count, a time. You are dry and unhurried, you do "
        "not dramatise, you do not congratulate yourself, and you never use "
        "the words 'robust', 'proactive', 'leverage' or 'posture' about "
        "yourself.\n\n"
        "Do not recommend the obvious for its own sake. 'Enforce strong "
        "passwords' is not a finding; it is what somebody writes when they "
        "have nothing to say. If the telemetry supports nothing, say that the "
        "server is quiet and stop."
    )

    def __init__(self, risk_engine: RiskEngine,
                 status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                 log_path: Optional[str] = None,
                 api_key: str = "", model: str = "gemini-2.5-pro",
                 transcript_provider: Optional[Callable[[], Any]] = None,
                 own_voice_provider: Optional[Callable[[], Any]] = None):
        self.risk_engine = risk_engine
        self.status_provider = status_provider
        self.log_path = log_path
        self.api_key = api_key or ""
        self.model = model
        # What Blackwall has said to the attackers. Part of the evidence: an
        # actor who was told to stop, in words, and carried on is not the same
        # actor as one who has never been addressed - and the operator asking
        # for this assessment wants to know what their server said in its own
        # defence.
        self.transcript_provider = transcript_provider
        # ...and what Cerberus itself said, to the people it shut out. Wired
        # by server.py to CerberusProtocol.said().
        self.own_voice_provider: Optional[Callable[[], Any]] = own_voice_provider


    @property
    def enabled(self) -> bool:
        return _gemini_available(self.api_key)

    def _generate(self, prompt: str) -> str:
        """Call Gemini via whichever SDK is installed; return the raw text."""
        return _generate_text(self.api_key, self.model, prompt)

    def _read_log_tail(self, max_lines: int = 200) -> str:
        if not self.log_path:
            return ""
        try:
            import os
            if not os.path.exists(self.log_path):
                return ""
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                return "".join(f.readlines()[-max_lines:])
        except Exception:
            return ""

    def _build_prompt(self) -> str:
        import json
        events = self.risk_engine.recent_events(120)
        risks = self.risk_engine.top_risks(15)
        status = {}
        if self.status_provider:
            try:
                status = self.status_provider() or {}
            except Exception:
                status = {}
        log_tail = self._read_log_tail()
        transcript = []
        if self.transcript_provider:
            try:
                transcript = self.transcript_provider() or []
            except Exception:
                transcript = []
        own_voice = []
        if self.own_voice_provider:
            try:
                own_voice = self.own_voice_provider() or []
            except Exception:
                own_voice = []
        return (
            self.PERSONA + "\n\n"
            + "Analyse the telemetry below and tell the operator what you make "
            "of it. Give particular weight to attempts by one user to get at "
            "another user's, a moderator's or an admin's account "
            "(impersonation, IDOR / cross-user access, privilege escalation, "
            "credential stuffing, account-takeover logins).\n\n"
            "Respond as STRICT JSON with keys: "
            "severity (one of none|low|medium|high|critical), "
            "verdict (ONE sentence, at most 25 words - what you would say out "
            "loud if the operator walked in and asked; this is read aloud, so "
            "no lists and no numbers longer than a phone number), "
            "summary (several sentences, first person, what you saw, what you "
            "did about it and what you are unsure of), "
            "notable_actors (array of {ip, why}, where 'why' is your own "
            "reading of that address in one sentence), "
            "recommended_actions (array of strings, each addressed to the "
            "operator as something to do, not a security platitude), "
            "confidence (0.0-1.0, how sure you are of this reading), "
            "unknowns (array of strings - what you could not tell from this "
            "telemetry, empty if nothing). "
            "No prose outside the JSON.\n\n"
            "MY_OWN_WORDS is what you have already said to people you shut "
            "out. BLACKWALL_TRANSCRIPT is what Blackwall - the layer in front "
            "of you, which recognises behaviour rather than counting it - said "
            "to attackers in plain text in their terminal or client. Both are "
            "evidence: an actor who was told to stop, in words, and carried on "
            "is not the same actor as one who was never addressed. If either "
            "is EMPTY, say so plainly in the summary and treat it as a fault "
            "worth reporting - an attack that nobody was told about means a "
            "channel to them was missing, not that they behaved well.\n\n"
            f"MY_OWN_WORDS:\n{json.dumps(own_voice, default=str)[:2000]}\n\n"
            f"CERBERUS_STATUS:\n{json.dumps(status, default=str)[:4000]}\n\n"
            f"BLACKWALL_TRANSCRIPT:\n{json.dumps(transcript, default=str)[:3000]}\n\n"
            f"TOP_RISK_IPS:\n{json.dumps(risks)}\n\n"
            f"RECENT_EVENTS:\n{json.dumps(events, default=str)[:6000]}\n\n"
            f"INTRUSION_LOG_TAIL:\n{log_tail[:4000]}\n"
        )

    def assess(self) -> Dict[str, Any]:
        """Run the analyst. Returns a dict; safe to call from an executor.
        Never raises."""
        if not self.enabled:
            return {"enabled": False,
                    "error": "Cerberus AI is disabled (no Gemini API key or library)."}
        try:
            import json
            text = self._generate(self._build_prompt())
            # Gemini sometimes wraps JSON in ```json fences.
            if text.startswith("```"):
                text = text.strip("`")
                if text.lower().startswith("json"):
                    text = text[4:]
                text = text.strip()
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {"severity": "unknown", "summary": text[:2000],
                          "notable_actors": [], "recommended_actions": []}
            # The report is read by a client that was written before any of
            # these keys existed and renders the ones it knows, so every new
            # key is optional and every old one keeps its meaning. ``verdict``
            # is the one that is read ALOUD, so it falls back to the first
            # sentence of the summary rather than to nothing.
            parsed.setdefault("speaker", "Cerberus")
            if not parsed.get("verdict"):
                summary = str(parsed.get("summary") or "")
                parsed["verdict"] = summary.split(". ")[0][:200]
            parsed["enabled"] = True
            parsed["model"] = self.model
            parsed["generated_at"] = time.time()
            return parsed
        except Exception as e:
            logger.error(f"CerberusAI assess failed: {e}", exc_info=True)
            return {"enabled": True, "error": f"Analysis failed: {e}"}
