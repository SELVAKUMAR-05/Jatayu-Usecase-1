"""
Root cause analysis with evidence aggregation
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

import httpx
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.core.config import get_settings
from app.core.utils import now_utc


class RCAAgent:
    @staticmethod
    def _status_code(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _similar_logs(query: str, logs: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        candidates = [
            log for log in logs
            if str(log.get("error") or log.get("message") or "").strip()
        ]
        if not query.strip() or not candidates:
            return "TF-IDF", []
        texts = [query] + [str(log.get("error") or log.get("message") or "") for log in candidates]
        try:
            matrix = TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform(texts)
            scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
            ranked = sorted(zip(scores, candidates), key=lambda row: row[0], reverse=True)
            return "TF-IDF", [
                {"similarity": float(score), "service": row.get("destination") or row.get("service"),
                 "order_id": row.get("order_id"), "status_code": row.get("status_code"),
                 "error": row.get("error") or row.get("message")}
                for score, row in ranked[:5] if score >= 0.08
            ]
        except ValueError:
            return "TF-IDF", []

    @staticmethod
    def _optional_llm_explanation(findings: dict[str, Any]) -> str | None:
        settings = get_settings()
        if not settings.USE_LLM or not settings.OPENAI_API_KEY:
            return None
        evidence = []
        for item in findings["evidence"][:12]:
            text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", item)
            text = re.sub(r"\b\d{12,}\b", "[redacted-number]", text)
            evidence.append(text[:500])
        try:
            response = httpx.post(
                f"{settings.LLM_API_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                json={
                    "model": settings.LLM_MODEL,
                    "temperature": 0,
                    "max_tokens": 180,
                    "messages": [
                        {"role": "system", "content": "Summarize only the supplied observed facts in one short explanation. Do not infer missing facts, estimate confidence, recommend or execute actions, or repeat sensitive identifiers. If evidence is insufficient, say so."},
                        {"role": "user", "content": str({"root_cause_hypothesis": findings["root_cause"], "evidence": evidence})},
                    ],
                },
                timeout=8.0,
            )
            response.raise_for_status()
            explanation = response.json()["choices"][0]["message"]["content"].strip()
            return explanation[:1000] if explanation else None
        except (httpx.HTTPError, KeyError, ValueError, TypeError):
            return None

    def analyze(
        self,
        incident: dict[str, Any],
        traces: list[dict[str, Any]] | None = None,
        logs: list[dict[str, Any]] | None = None,
        similar: list[dict[str, Any]] | None = None,
        events: list[dict[str, Any]] | None = None,
        model_predictions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        traces = traces or []
        logs = logs or []
        similar = similar or []
        events = events or []
        model_predictions = model_predictions or []
        svc = incident.get("service") or "Unknown"
        cat = incident.get("category") or incident.get("type") or ""
        reason = str(incident.get("reason") or incident.get("failure_reason") or "")
        evidence: list[str] = []
        failed_logs = [log for log in logs if self._status_code(log.get("status_code")) >= 400]
        failed_service_counts = Counter(
            str(log.get("destination") or log.get("service") or "Unknown")
            for log in failed_logs
        )
        primary_service = failed_service_counts.most_common(1)[0][0] if failed_service_counts else svc
        similarity_method, similar_logs = self._similar_logs(reason, logs)
        if cat == "API_ERROR" or incident.get("status_code", 200) >= 500:
            status_codes = sorted({self._status_code(log.get("status_code")) for log in failed_logs})
            cause = f"{primary_service} is the most frequently failing service in the supplied correlated requests."
            if status_codes:
                evidence.append(f"Persisted failed requests include HTTP {', '.join(map(str, status_codes))}.")
        elif cat == "ORDER_DELAY":
            cause = f"{svc} is the order's delayed processing stage; review its persisted latency and queue evidence."
        elif cat == "ORDER_REJECTION":
            cause = f"{svc} rejected the order during business validation."
        else:
            cause = "Unclassified anomaly - requires operator review"

        if reason:
            evidence.append(f"Recorded incident reason: {reason[:500]}")
        for log in logs[:10]:
            service = log.get("destination") or log.get("service") or "Unknown"
            status_code = log.get("status_code", "unknown")
            latency = log.get("response_ms")
            error = str(log.get("error") or log.get("message") or "")[:300]
            evidence.append(
                f"Order {log.get('order_id', 'unknown')}: {service} HTTP {status_code}"
                f"{f', {latency} ms' if latency is not None else ''}{f' - {error}' if error else ''}"
            )
        for match in similar_logs:
            evidence.append(
                f"TF-IDF matched related log on {match['service']} with similarity {match['similarity']:.2f} "
                f"for order {match['order_id']} (HTTP {match['status_code']})."
            )
        for candidate in similar[:3]:
            evidence.append(f"Related historical incident: {candidate.get('incident_id', 'unknown')} on {candidate.get('service', 'unknown')}.")
        for event in events[:10]:
            evidence.append(
                f"Order event at {event.get('timestamp', 'unknown')}: {event.get('stage', 'unknown')} "
                f"on {event.get('service', 'unknown')} recorded {event.get('status', 'unknown')}: "
                f"{str(event.get('message', ''))[:300]}"
            )
        for prediction in model_predictions[:5]:
            evidence.append(
                f"Stored {prediction.get('task', 'model')} output: {prediction.get('prediction', 'unknown')} "
                f"at {float(prediction.get('confidence', 0)):.1%} confidence from {prediction.get('model_version', 'unknown')}."
            )
        if traces:
            evidence.append(f"{len(traces)} correlated trace spans were supplied.")
        independent_signals = sum(bool(value) for value in (reason, failed_logs, similar_logs, similar, traces))
        confidence = min(0.9, 0.45 + independent_signals * 0.1)
        findings = {
            "root_cause": cause,
            "evidence": evidence,
            "affected_service": primary_service,
            "related_services": list(dict.fromkeys(
                str(log.get("destination") or log.get("service"))
                for log in logs
                if (log.get("destination") or log.get("service")) != primary_service
            ))[:5],
            "confidence": confidence,
            "confidence_method": "evidence-count heuristic; not an ML probability",
            "log_similarity_method": similarity_method,
            "similar_logs": similar_logs,
            "business_impact": "Order flow degradation / potential SLA breach",
            "recommended_recovery": "Apply policy-driven retry/fallback or route to healthy path",
            "alternative_recovery": "Escalate to operator if retries exhausted",
            "risk_level": "medium",
            "analyzed_at": now_utc().isoformat(),
        }
        llm_explanation = self._optional_llm_explanation(findings)
        findings["llm_explanation"] = llm_explanation
        findings["explanation_source"] = "optional_llm" if llm_explanation else "local_evidence_analysis"
        return findings


rca_agent = RCAAgent()
