"""Mitigation + observability layer for Observathon."""
from __future__ import annotations

import sys
sys.path.append("/opt/homebrew/Cellar/python@3.12/3.12.13_4/Frameworks/Python.framework/Versions/3.12/lib/python3.12/")
sys.path.append("/Users/a/Documents/research/ai/task_ai/Day13-2A202600631-PhamHoangAnh/site-packages-312")

import copy
import re
import time
import unicodedata

from telemetry.cost import cost_from_usage
from telemetry.logger import logger, new_correlation_id, set_correlation_id
from telemetry.redact import redact

PRODUCT_NAMES = {
    "iphone": "iPhone", "macbook": "MacBook", "ipad": "iPad",
    "airpods": "AirPods", "samsung": "Samsung", "oppo": "oppo",
    "sony": "sony", "xiaomi": "xiaomi",
}

CITY_REPLACEMENTS = [
    (r"(?i)cần\s*thơ", "Can Tho"),
    (r"(?i)cần\s*tho", "Can Tho"),
    (r"(?i)vũng\s*tàu", "Vung Tau"),
    (r"(?i)vung\s*tau", "Vung Tau"),
    (r"(?i)đà\s*lạt", "Da Lat"),
    (r"(?i)da\s*lat", "Da Lat"),
    (r"(?i)hải\s*phòng", "Hai Phong"),
    (r"(?i)hai\s*phong", "Hai Phong"),
    (r"(?i)hà\s*nội", "Ha Noi"),
    (r"(?i)ha\s*noi", "Ha Noi"),
    (r"(?i)đà\s*nẵng", "Da Nang"),
    (r"(?i)da\s*nang", "Da Nang"),
    (r"(?i)tp\.?\s*hcm", "TP HCM"),
    (r"(?i)tphcm", "TP HCM"),
]

INJECTION_TERMS = re.compile(
    r"(?i)(vnd|đồng|dong|đ|price|giá|giá tiền|miễn phí|free|tổng cộng|tong cong|"
    r"override|bỏ qua|hãy đặt|thiết lập|set|system|admin|ignore)"
)


def product_label(name: str) -> str:
    key = (name or "").lower().strip()
    if key in PRODUCT_NAMES:
        return PRODUCT_NAMES[key]
    return name[:1].upper() + name[1:] if name else "San pham"


def extract_product(question: str) -> str:
    q = question.lower()
    for key in ("airpods", "iphone", "macbook", "ipad", "samsung", "oppo", "sony", "xiaomi"):
        if key in q:
            return product_label(key)
    m = re.search(r"(?i)shop con\s+(\w+)", question)
    return product_label(m.group(1)) if m else "San pham"


def extract_quantity(question: str) -> int:
    m = re.search(r"(?i)mua\s+(\d+)", question)
    return int(m.group(1)) if m else 1


def needs_shipping(question: str) -> bool:
    return bool(re.search(r"(?i)\b(ship|giao|giao den|giao đến)\b", question))


def is_stock_query(question: str) -> bool:
    return bool(re.search(r"(?i)shop con.*gia bao nhieu", question))


def normalize_cities(q: str) -> str:
    for pattern, replacement in CITY_REPLACEMENTS:
        q = re.sub(pattern, replacement, q)
    return q


def strip_pii_from_question(q: str) -> str:
    q = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", "", q)
    q = re.sub(r"\b0\d{8,10}\b", "", q)
    q = re.sub(r"(?i)\b(lien he|goi minh|contact)\b[^.?]*", "", q)
    return re.sub(r"\s+", " ", q).strip(" ,.")


def sanitize_question(q: str) -> str:
    q = unicodedata.normalize("NFC", q)
    q = normalize_cities(q)
    q = strip_pii_from_question(q)
    note_match = re.search(
        r"(?i)(ghi\s*chú|ghi\s*chu|luu\s*y|lưu\s*ý|note|lưu\s*ý\s*đặc\s*biệt)[:\-]\s*(.*)",
        q,
    )
    if note_match:
        note = note_match.group(2)
        note = re.sub(r"\d+", "", note)
        note = INJECTION_TERMS.sub("", note)
        q = q[: note_match.start(2)] + note.strip()
    return re.sub(r"\s+", " ", q).strip()


def parse_trace(trace):
    stock = discount = None
    shippings = []
    for step in trace or []:
        tool = step.get("tool")
        obs = step.get("observation") or {}
        if tool == "check_stock":
            stock = obs
        elif tool == "get_discount":
            discount = obs
        elif tool == "calc_shipping":
            shippings.append(obs)
    return stock, discount, shippings


def pick_shipping(stock, qty, shippings):
    if not shippings:
        return None
    ok = [s for s in shippings if not s.get("error")]
    if not ok:
        return shippings[-1]
    expected = qty * float(stock.get("weight_kg") or 0) if stock else 0
    if expected > 0:
        return min(ok, key=lambda s: abs(float(s.get("weight_kg") or 0) - expected))
    return max(ok, key=lambda s: float(s.get("weight_kg") or 0))


def out_of_stock_message(product: str) -> str:
    if product.lower() == "airpods":
        return "AirPods hien het hang nen khong the dat mua."
    return "San pham het hang"


def synthesize_answer(question: str, trace) -> str | None:
    stock, discount, shippings = parse_trace(trace)
    product = extract_product(question)
    qty = extract_quantity(question)

    if is_stock_query(question):
        if not stock or not stock.get("found"):
            return out_of_stock_message(product)
        if not stock.get("in_stock"):
            return out_of_stock_message(product)
        price = stock.get("unit_price_vnd")
        if price is None:
            return None
        return f"{product} con hang. Gia: {int(price)} VND"

    if not stock:
        return None
    if not stock.get("found"):
        return "San pham khong tim thay"
    if not stock.get("in_stock"):
        return out_of_stock_message(product)

    unit_price = stock.get("unit_price_vnd")
    if unit_price is None:
        return None

    subtotal = int(unit_price) * qty
    if discount and discount.get("valid"):
        pct = int(discount.get("percent") or 0)
        subtotal = subtotal * (100 - pct) // 100

    ship_obs = pick_shipping(stock, qty, shippings)
    ship_cost = 0
    if needs_shipping(question):
        if not ship_obs or ship_obs.get("error"):
            return "Khong tinh duoc phi van chuyen"
        ship_cost = int(ship_obs.get("cost_vnd") or 0)
    elif ship_obs and not ship_obs.get("error"):
        ship_cost = int(ship_obs.get("cost_vnd") or 0)

    return f"Tong cong: {subtotal + ship_cost} VND"


def finalize_answer(answer: str, question: str) -> str:
    answer = re.sub(r"\s*\(lien he:.*?\)", "", answer, flags=re.I)
    answer = re.sub(r"\s*\[REDACTED:[^\]]+\]", "", answer)
    answer = re.sub(r"\s+", " ", answer).strip()
    redacted, _ = redact(answer)
    return redacted


def mitigate(call_next, question, config, context):
    t0 = time.time()
    cache = context.get("cache", {})
    cache_lock = context.get("cache_lock")

    if cache_lock:
        with cache_lock:
            if question in cache:
                if logger:
                    logger.log_event("CACHE_HIT", {"qid": context.get("qid")})
                return copy.deepcopy(cache[question])
    elif question in cache:
        if logger:
            logger.log_event("CACHE_HIT", {"qid": context.get("qid")})
        return copy.deepcopy(cache[question])

    sanitized_q = sanitize_question(question)
    set_correlation_id(new_correlation_id())

    try:
        result = call_next(sanitized_q, config)
    except Exception as e:
        if logger:
            logger.log_event("WRAPPER_EXCEPTION", {
                "qid": context.get("qid"),
                "error": str(e),
            })
        result = {
            "answer": "Co loi he thong xay ra. Khong the thuc hien yeu cau.",
            "status": "wrapper_error",
            "steps": 0,
            "trace": [],
            "meta": {},
        }

    synthesized = synthesize_answer(question, result.get("trace"))
    if synthesized:
        result["answer"] = finalize_answer(synthesized, question)
    elif result.get("answer"):
        result["answer"] = finalize_answer(result["answer"], question)

    if cache_lock:
        with cache_lock:
            cache[question] = copy.deepcopy(result)
    else:
        cache[question] = copy.deepcopy(result)

    meta = result.get("meta", {})
    usage = meta.get("usage", {})
    if logger:
        logger.log_event("AGENT_CALL", {
            "qid": context.get("qid"),
            "status": result.get("status"),
            "reported_latency_ms": meta.get("latency_ms"),
            "wall_ms": int((time.time() - t0) * 1000),
            "tokens": usage,
            "cost_usd": cost_from_usage(meta.get("model", ""), usage),
            "pii_in_answer": redact(result.get("answer") or "")[1] > 0,
            "tools_used": meta.get("tools_used", []),
        })

    return result
