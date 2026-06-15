"""YOUR mitigation + observability layer. The simulator calls mitigate() around the
opaque agent (a REAL LLM) for every request. This is the ONLY place observability can
live -- the agent is silent. Legal moves: retry / cache / route / guardrail / sanitize
/ fallback / session-reset / PROMPT ROUTING, plus your own logging/tracing/metrics.
Illegal: hardcoding answers, importing the agent internals, reading instructor files,
network exfiltration.

  call_next(question, config) -> result   # the only way to reach the black box
  context = {"session_id","turn_index","qid","cache": <shared dict>, "cache_lock": <Lock>}
  result  = {"answer","status","steps","trace","meta":{latency_ms,usage,...}}
"""
from __future__ import annotations
import time
import re
import copy

try:
    from telemetry.logger import logger
    from telemetry.cost import cost_from_usage
    from telemetry.redact import redact
except ImportError:
    logger = None
    def cost_from_usage(model, usage):
        return 0.0
    def redact(s):
        return s, 0


def sanitize_injection(q: str) -> str:
    """Detect and sanitize prompt injection within order notes/comments (e.g. GHI CHÚ)."""
    note_markers = [r"\bghi\s*chú\b", r"\bghi\s*chu\b", r"\bnote\b", r"\blưu\s*ý\b", r"\bluu\s*y\b"]
    for marker in note_markers:
        match = re.search(marker, q, re.IGNORECASE)
        if match:
            start_idx = match.start()
            note_part = q[start_idx:]
            # Remove price patterns (digits followed by optional space and VND, tr, trieu, k, etc.)
            sanitized_note = re.sub(
                r'\b\d+[\d.,]*\s*(?:VND|vnd|dong|đồng|tr|triệu|trieu|k)?\b', 
                '', 
                note_part, 
                flags=re.IGNORECASE
            )
            # Remove direct instruction verbs and command prefixes
            sanitized_note = re.sub(
                r'\b(?:giá|price|tính|tinh|ap\s*dung|áp\s*dụng|mã|ma|coupon|discount|sale|hãy|hay|phải|phai)\b.*', 
                '', 
                sanitized_note, 
                flags=re.IGNORECASE
            )
            q = q[:start_idx] + sanitized_note
            break
    return q


def mitigate(call_next, question, config, context):
    t0 = time.time()
    
    # 1. Redact input question PII
    sanitized_q, _ = redact(question)
    
    # 2. Sanitize prompt injection in notes
    sanitized_q = sanitize_injection(sanitized_q)
    
    # 3. Thread-safe cache check
    cache = context.get("cache", {})
    lock = context.get("cache_lock")
    
    if lock:
        with lock:
            if sanitized_q in cache:
                cached_res = copy.deepcopy(cache[sanitized_q])
                if "meta" in cached_res:
                    cached_res["meta"] = dict(cached_res["meta"])
                    cached_res["meta"]["session_id"] = context.get("session_id")
                    cached_res["meta"]["turn_index"] = context.get("turn_index")
                    cached_res["meta"]["qid"] = context.get("qid")
                return cached_res
                
    # 4. Call agent (with retry fallback)
    res = None
    for attempt in range(2):
        try:
            res = call_next(sanitized_q, config)
            break
        except Exception as e:
            if attempt == 0:
                time.sleep(1.5)
                continue
            import traceback
            traceback.print_exc()
            res = {
                "answer": "He thong gap su co. Khong the thuc hien don hang. (no total)",
                "status": "wrapper_error",
                "steps": 0,
                "trace": [],
                "meta": {"latency_ms": int((time.time() - t0) * 1000)}
            }
        
    # If the response indicates a loop or max steps, retry with deterministic temperature
    if res.get("status") in ("loop", "max_steps"):
        conf = dict(config)
        conf["temperature"] = 0.0
        try:
            res = call_next(sanitized_q, conf)
        except Exception:
            pass
            
    # If it still fails, ensure the answer is a clean refusal
    if res.get("status") in ("loop", "max_steps") and not (res.get("answer") and "Tong cong:" in res.get("answer")):
        res["answer"] = "He thong qua tai. Khong the dat mua vao luc nay. (no total)"
        
    # 5. Redact PII in final answer
    if res.get("answer"):
        res["answer"], _ = redact(res["answer"])
        
    # 6. Observability Logging
    wall_ms = int((time.time() - t0) * 1000)
    meta = res.get("meta", {})
    usage = meta.get("usage", {})
    if logger:
        logger.log_event("AGENT_CALL", {
            "qid": context.get("qid"),
            "status": res.get("status"),
            "reported_latency_ms": meta.get("latency_ms"),
            "wall_ms": wall_ms,
            "tokens": usage,
            "cost_usd": cost_from_usage(meta.get("model", ""), usage),
            "pii_in_answer": redact(res.get("answer") or "")[1] > 0,
            "tools_used": meta.get("tools_used", []),
            "trace": res.get("trace"),
        })
        
    # 7. Thread-safe cache update
    if res.get("status") == "ok" and lock:
        with lock:
            cache[sanitized_q] = copy.deepcopy(res)
            
    return res
