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
   events + the live Cerberus status and returns a human-readable threat
   assessment with recommended actions. Uses Google Gemini (the operator's
   available provider), is gated behind an API key, runs only when a moderator
   asks, never sits in the request path, and fails closed (advisory only).
"""

import logging
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

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


class RiskEngine:
    """Time-decayed, cross-signal risk scoring per source IP."""

    def __init__(self, on_escalate: Optional[Callable[[str, str], None]] = None,
                 ban_threshold: float = 60.0, half_life_seconds: float = 600.0,
                 buffer_size: int = 500):
        self.on_escalate = on_escalate
        self.ban_threshold = ban_threshold
        self.half_life = half_life_seconds
        # {ip: [score, last_update_ts]}
        self._scores: Dict[str, List[float]] = {}
        self._escalated: set = set()
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
        if score >= self.ban_threshold and ip not in self._escalated:
            self._escalated.add(ip)
            reason = (f"Cerberus risk score {score:.0f} >= {self.ban_threshold:.0f} "
                      f"(correlated: last='{kind}')")
            logger.warning(f"[CERBERUS-AI] Escalating {ip}: {reason}")
            if self.on_escalate:
                try:
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

    def __init__(self, risk_engine: RiskEngine,
                 status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                 log_path: Optional[str] = None,
                 api_key: str = "", model: str = "gemini-2.5-pro"):
        self.risk_engine = risk_engine
        self.status_provider = status_provider
        self.log_path = log_path
        self.api_key = api_key or ""
        self.model = model

    @property
    def enabled(self) -> bool:
        if not self.api_key:
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

    def _generate(self, prompt: str) -> str:
        """Call Gemini via whichever SDK is installed; return the raw text."""
        # Preferred: new google-genai SDK (matches the rest of Titan-Net).
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(model=self.model, contents=prompt)
            return (getattr(resp, "text", "") or "").strip()
        except ImportError:
            pass
        # Fallback: legacy google-generativeai SDK.
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        resp = model.generate_content(prompt)
        return (getattr(resp, "text", "") or "").strip()

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
        return (
            "You are Cerberus, the security analyst for the Titan-Net server. "
            "Analyze the telemetry below and produce a concise threat assessment. "
            "Focus on attempts by one user to break into another user, moderator, "
            "or admin account (impersonation, IDOR / cross-user access, privilege "
            "escalation, credential stuffing, account-takeover logins). "
            "Respond as STRICT JSON with keys: "
            "severity (one of none|low|medium|high|critical), "
            "summary (string), notable_actors (array of {ip, why}), "
            "recommended_actions (array of strings). No prose outside the JSON.\n\n"
            f"CERBERUS_STATUS:\n{json.dumps(status, default=str)[:4000]}\n\n"
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
            parsed["enabled"] = True
            parsed["model"] = self.model
            parsed["generated_at"] = time.time()
            return parsed
        except Exception as e:
            logger.error(f"CerberusAI assess failed: {e}", exc_info=True)
            return {"enabled": True, "error": f"Analysis failed: {e}"}
