"""V2 program-produced facts, followed by one bounded interpretation call.

No raw performance arrays, MusicXML, audio or credentials enter model input.
Unknown requests cannot be silently retried; only validated outputs are cached.
"""
from __future__ import annotations
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler

CONTRACTS = Path(__file__).parent / "contracts/practice-record-analysis"
AGGREGATE_VERSION = "2.0-account-1"
MAPPING_VERSION = "account-history-1"
CLAIM_RULES_VERSION = "counts-only-scoped-text-and-investment-summary-2"
SELECTION_VERSION = "all-selected-counts-fixed-category-order-1"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_INPUT_BYTES = 16 * 1024
MAX_INPUT_TOKEN_BOUND = 32768
MAX_OUTPUT_TOKENS = 4096
UUID_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
SETTINGS = {"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS, "stream": False}


class AnalysisError(Exception):
    def __init__(self, status, message, *, uncertain=False):
        self.status, self.message, self.uncertain = status, message, uncertain
        super().__init__(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf8")


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json_bytes(value)).hexdigest()


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def validate_schema(value, schema, root=None):
    """All assertion keywords used by the delivered Draft 2020-12 schemas.

    Unsupported assertion keywords fail configuration, never silently bypass.
    """
    root = schema if root is None else root
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        validate_schema(value, target, root)
    supported = {"$ref", "$schema", "$defs", "$comment", "title", "description", "type", "const", "enum", "required", "properties", "additionalProperties", "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "items"}
    if set(schema) - supported:
        raise ValueError("Unsupported schema assertion")
    kinds = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "boolean": isinstance(value, bool), "null": value is None}
    expected = schema.get("type")
    if expected is not None and not any(kinds.get(k, False) for k in (expected if isinstance(expected, list) else [expected])):
        raise ValueError("Incorrect schema type")
    if "const" in schema and value != schema["const"] or "enum" in schema and value not in schema["enum"]:
        raise ValueError("Incorrect schema value")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - set(value):
            raise ValueError("Missing schema fields")
        if schema.get("additionalProperties") is False and set(value) - set(schema.get("properties", {})):
            raise ValueError("Unexpected schema fields")
        for key, item in value.items():
            if key in schema.get("properties", {}):
                validate_schema(item, schema["properties"][key], root)
    if isinstance(value, str) and not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", math.inf):
        raise ValueError("Text exceeds schema bounds")
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            raise ValueError("List exceeds schema bounds")
        if schema.get("uniqueItems") and len({json_bytes(item) for item in value}) != len(value):
            raise ValueError("Duplicate schema items")
        for item in value:
            if "items" in schema:
                validate_schema(item, schema["items"], root)


def private_skill_directory(value=None):
    configured = value or os.environ.get("NOTELITE_PRACTICE_SKILL_DIR")
    if not configured:
        raise AnalysisError(503, "文字分析规则尚未配置。")
    return Path(configured)


def contracts(directory=None):
    # Public structural contracts support a clean source checkout. Production
    # validates the exact operator-provided schema alongside its private prompt.
    directory = CONTRACTS if directory is None else Path(directory)
    return tuple(parse_json((directory / name).read_text(encoding="utf8")) for name in ("aggregate-input.schema.json", "output.schema.json"))


def validate_input(value, evidence_index, schema):
    validate_schema(value, schema)
    ids = set()
    for fact in value["facts"]:
        if fact["factId"] in ids or any(key not in evidence_index or not evidence_index[key].get("events") for key in fact["evidenceRefs"]):
            raise ValueError("Fact evidence does not resolve")
        ids.add(fact["factId"])
        state, kind = fact["claimState"], fact["kind"]
        if kind in {"weakness", "strength", "progress"} and state != "verified_fact" or kind == "pending_review" and state != "pending_review" or kind == "unavailable" and state != "unavailable" or state == "pending_review" and kind != "pending_review" or state == "unavailable" and kind != "unavailable" or state == "provisional_pattern" and kind != "performance_observation":
            raise ValueError("Inconsistent fact classification")
    if len(json_bytes(value)) > MAX_INPUT_BYTES:
        raise AnalysisError(413, "事实汇总超过分析预算，请选择较少的记录。")
    return value


LIMITED_SUMMARIES = {
    "investment_only": "本次可回顾已记录的练习投入，现有演奏证据不足以判断技术强弱项或进步。",
    "no_usable_data": "本次没有可用于投入或演奏反馈的事实，请补充可分析记录后再查看。",
}


def unsupported_capability_assertion(content):
    """Catch explicit capability upgrades in timer-only/no-data feedback.

    This is a bounded language guard, not proof of arbitrary text semantics.
    Negations and proposed later checks are allowed within their own clause;
    they cannot excuse a separate affirmative clause after punctuation.
    """
    claim = re.compile(
        r"稳定(?:强项|弱项)|强弱项|(?:已(?:经)?|成为|属于|是|具备|形成|表现出).{0,8}(?:强项|弱项)|"
        r"(?:音准|音高|节奏|演奏(?:能力|水平|表现|质量)?|弹奏|技巧|技术|能力|水平).{0,16}"
        r"(?:稳定|准确|正确|优秀|良好|突出|糟糕|改善|提高|提升|进步|退步)|"
        r"(?:已(?:经)?|持续|明显|显著|不断|取得|有了|正在).{0,8}(?:进步|提高|提升|改善)|"
        r"(?:stable\s+(?:strength|weakness)|(?:pitch|rhythm|ability|technique).{0,20}(?:improved|improvement|accurate|stable))",
        re.IGNORECASE,
    )
    qualification = re.compile(
        r"不能|不可|无法|不足以|尚不能|暂不|未能|"
        r"尚未(?:证明|确认|认定|判断|评估)|未(?:被)?(?:证明|确认|认定|判断|评估)|"
        r"不(?:意味着|等于|证明|代表|说明|属于|是)|并非|"
        r"没有(?:足够|可靠|明确|可用)?(?:依据|证据)|"
        r"待|如果|若|后续|未来|下一次|之后|复测|是否|可能|有待|后再|"
        r"需要(?:确认|判断|复核|核对|观察|比较|评估)|再(?:观察|比较|评估|判断)|"
        r"以便(?:观察|比较|评估|判断)|"
        r"\b(?:not|cannot|can't|unknown|unavailable|unverified|whether|future|later)\b",
        re.IGNORECASE,
    )
    negative_tail = re.compile(r"^[^，,。；;！？!?]{0,20}(?:暂(?:时)?不(?:可|能)|不可|不能|无法|尚未|未知|暂无|尚无|未(?:获|经)?(?:证实|确认|证明|评估)|需(?:要)?(?:复核|核对|评估|确认|判断))")
    for clause in re.split(r"[，,。；;！？!?\n]|但是|然而|不过|但|却|\bbut\b", content, flags=re.IGNORECASE):
        for match in claim.finditer(clause):
            if not qualification.search(clause[:match.end()]) and not negative_tail.search(clause[match.end():]):
                return True
    return False


def validate_fact_text(content, referenced):
    factual_text = " ".join(str(f[key] or "") for f in referenced for key in ("statement", "displayValue", "scope", "label"))
    allowed_numbers = set(re.findall(r"\d+(?:\.\d+)?", factual_text))
    unit_pattern = r"\d+(?:\.\d+)?\s*(?:%|秒|分钟|小时|次|条|项|BPM|bpm|拍)"
    allowed_units = {re.sub(r"\s", "", v) for v in re.findall(unit_pattern, factual_text)}
    if any(v not in allowed_numbers for v in re.findall(r"\d+(?:\.\d+)?", content)) or any(re.sub(r"\s", "", v) not in allowed_units for v in re.findall(unit_pattern, content)):
        raise ValueError("Precise value missing from cited facts")
    for theory in re.findall(r"(?:大|小|增|减)[二三四五六七八九十]度|最高失败率|失败概率最高|手型错误|用力错误|疲劳导致|耐力很好|已经形成习惯|技术明显改善", content):
        if theory not in factual_text:
            raise ValueError("Unsupported theory/ranking/cause")
    if re.search(r"(?:听过|听完|听了|聆听了).*(?:音频|录音)|(?:录音|音频).*(?:已经听过|已听完)", content):
        raise ValueError("Audio was not supplied")


def validate_output(value, input_value, schema=None, *, project_summary=True):
    validate_schema(value, contracts()[1] if schema is None else schema)
    if value["status"] != input_value["reportStatus"]:
        raise ValueError("Model changed report coverage")
    facts = {fact["factId"]: fact for fact in input_value["facts"]}
    texts = [(content, list(facts.values())) for content in (value["summary"], *value["limitations"])]
    for group in ("observations", "weaknesses", "strengths", "progress", "pendingReview", "suggestions"):
        for item in value[group]:
            if any(key not in facts for key in item["factIds"]):
                raise ValueError("Invented fact reference")
            referenced = [facts[key] for key in item["factIds"]]
            if group in {"weaknesses", "strengths", "progress"}:
                category = {"weaknesses": "weakness", "strengths": "strength", "progress": "progress"}[group]
                if any(f["kind"] != category or f["claimState"] != "verified_fact" for f in referenced):
                    raise ValueError("Unjustified strong classification")
            elif group == "pendingReview":
                if any(f["kind"] != "pending_review" or f["claimState"] != "pending_review" for f in referenced):
                    raise ValueError("Invalid pending classification")
            elif group == "observations":
                if any(f["claimState"] in {"pending_review", "unavailable"} for f in referenced):
                    raise ValueError("Pending/unavailable evidence is not an observation")
                if any(f["claimState"] == "provisional_pattern" for f in referenced) and not re.search("当前样本|初步观察|初步", item["title"] + item["description"]):
                    raise ValueError("Provisional claim lost its qualification")
            elif any(f["claimState"] == "unavailable" for f in referenced):
                raise ValueError("Suggestion without usable evidence")
            texts.extend((item[key], referenced) for key in item if key != "factIds")
    usable = {f["factId"] for f in facts.values() if f["kind"] in {"practice_investment", "performance_observation"} and f["claimState"] in {"verified_fact", "provisional_pattern"}}
    if usable and not any(usable.intersection(item["factIds"]) for item in value["observations"]):
        raise ValueError("Missing constructive observation")
    if any(f["claimState"] == "unavailable" for f in facts.values()) and not value["limitations"]:
        raise ValueError("Unavailable dimensions lost their limitations")
    for content, referenced in texts:
        validate_fact_text(content, referenced)
        if input_value["reportStatus"] in LIMITED_SUMMARIES and unsupported_capability_assertion(content):
            raise ValueError("Investment/no-data text asserted musical capability")
    # Validate the model's text before projecting: rejected assertions must use
    # fallback, not become a supposedly successful report by silently removing it.
    if project_summary and input_value["reportStatus"] in LIMITED_SUMMARIES:
        return {**value, "summary": LIMITED_SUMMARIES[input_value["reportStatus"]]}
    return value


class DeepSeekProvider:
    def __init__(self, key_file, model="deepseek-flash", *, skill_dir=None):
        if model not in {"deepseek-flash", "deepseek-v4-pro"}:
            raise ValueError("Unsupported configured model")
        self.key_file, self.model = Path(key_file), model
        self.skill_dir = private_skill_directory(skill_dir)
        self.prompt = (self.skill_dir / "deepseek-system-prompt.txt").read_text(encoding="utf8")
        self.settings = SETTINGS.copy()
        self.opener = build_opener(NoRedirect(), HTTPSHandler())

    def __call__(self, input_value):
        messages = [{"role": "system", "content": self.prompt}, {"role": "user", "content": json_bytes(input_value).decode("utf8")}]
        # Conservative UTF-8 byte upper bound plus message framing, not billing
        # token estimation or an asserted provider-specific tokenizer count.
        if len(json_bytes(input_value)) > MAX_INPUT_BYTES or len(json_bytes(messages)) + 512 > MAX_INPUT_TOKEN_BOUND:
            raise AnalysisError(413, "事实汇总超过输入预算。")
        key = ""
        sent = False
        try:
            key = self.key_file.read_text(encoding="ascii").strip()
            if not re.fullmatch(r"sk-[A-Za-z0-9_-]{16,160}", key):
                raise AnalysisError(503, "文字分析服务尚未配置。")
            request = Request("https://api.deepseek.com/chat/completions", data=json_bytes({"model": self.model, "messages": messages, **self.settings}), headers={"Content-Type": "application/json", "Authorization": "Bearer " + key}, method="POST")
            sent = True
            with self.opener.open(request, timeout=90) as response:
                if response.status != 200:
                    raise AnalysisError(502, "文字分析服务暂时不可用。")
                raw = response.read(128 * 1024 + 1)
                if len(raw) > 128 * 1024:
                    raise AnalysisError(502, "文字分析响应超过读取范围。")
            reply = parse_json(raw)
            choice = reply["choices"][0]
            if choice.get("finish_reason") != "stop" or not isinstance(choice.get("message", {}).get("content"), str) or not choice["message"]["content"].strip():
                raise AnalysisError(502, "文字分析未完整返回。")
            return parse_json(choice["message"]["content"])
        except HTTPError as error:
            raise AnalysisError(429 if error.code == 429 else 503 if error.code in {401, 402, 403} else 502, "文字分析服务暂时不可用。") from None
        except (URLError, TimeoutError, OSError):
            raise AnalysisError(504 if sent else 503, "文字分析请求结果尚未确认。" if sent else "文字分析服务尚未配置。", uncertain=sent) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise AnalysisError(502, "文字分析返回格式不完整。") from None
        finally:
            key = ""


class PracticeAnalysis:
    def __init__(self, store, provider, clock=time.time):
        self.store, self.provider, self.clock = store, provider, clock
        self.lock, self.capacity, self.active = threading.RLock(), threading.BoundedSemaphore(2), set()
        self.input_schema, self.output_schema = contracts(getattr(provider, "skill_dir", None))
        self.prompt = getattr(provider, "prompt", None)
        if not isinstance(self.prompt, str) or not self.prompt:
            raise AnalysisError(503, "文字分析规则尚未配置。")
        self.fingerprint = {"aggregateVersion": AGGREGATE_VERSION, "mappingVersion": MAPPING_VERSION, "claimRulesVersion": CLAIM_RULES_VERSION, "selectionVersion": SELECTION_VERSION, "promptHash": sha(self.prompt.encode()), "inputSchemaHash": sha(self.input_schema), "outputSchemaHash": sha(self.output_schema), "model": getattr(provider, "model", "test-provider"), "settings": getattr(provider, "settings", SETTINGS), "locale": "zh-CN", "timezone": "UTC"}
        with store.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS practice_analysis_v2_requests(user_id TEXT NOT NULL,request_id TEXT NOT NULL,input_sha TEXT NOT NULL,state TEXT NOT NULL,result TEXT,attempted INTEGER NOT NULL,created REAL NOT NULL,PRIMARY KEY(user_id,request_id));
            CREATE TABLE IF NOT EXISTS practice_analysis_v2_cache(user_id TEXT NOT NULL,input_sha TEXT NOT NULL,result TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(user_id,input_sha));
            """)

    def input(self, user_id, event_ids=None):
        if event_ids is not None and (not isinstance(event_ids, list) or not 1 <= len(event_ids) <= 200 or any(not isinstance(v, str) or not UUID_RE.fullmatch(v) for v in event_ids) or len(set(event_ids)) != len(event_ids)):
            raise AnalysisError(400, "请提供最多 200 条不同的练习记录标识。")
        with self.store.connect() as db:
            if event_ids is None:
                selected = list(db.execute("SELECT event_id,length(CAST(payload AS BLOB)) AS size FROM history WHERE user_id=? ORDER BY created DESC,event_id DESC LIMIT 201", (user_id,)))
                has_more, selected = len(selected) > 200, selected[:200]
            else:
                selected = [db.execute("SELECT event_id,length(CAST(payload AS BLOB)) AS size FROM history WHERE user_id=? AND event_id=?", (user_id, key)).fetchone() for key in sorted(event_ids)]
                if any(row is None for row in selected):
                    raise AnalysisError(404, "练习记录尚未同步，或不属于当前账户。")
                has_more = False
            if not selected:
                raise AnalysisError(409, "尚无已同步练习记录，请先保存一次练习。")
            if sum(row["size"] for row in selected) > MAX_SOURCE_BYTES:
                raise AnalysisError(413, "记录内容超过本次汇总范围，请选择较少记录。")
            rows = [dict(db.execute("SELECT event_id,payload,created,score_sha256,score_revision FROM history WHERE user_id=? AND event_id=?", (user_id, row["event_id"])).fetchone()) for row in selected]
        rows.sort(key=lambda row: row["event_id"])
        source_hash = sha(rows)
        records = [parse_json(row["payload"]) for row in rows]
        scope = {"recordCount": len(records), "hasMore": has_more, "description": "当前账户所选记录" if event_ids is not None else "当前账户最近 200 条已同步记录；其余历史未分析" if has_more else "当前账户全部已同步记录（不超过 200 条）"}
        evidence, facts = {}, []
        metrics = {"recordCount": len(records), "durationSeconds": None, "unanalysedRecordCount": 0, "emptyAnalysisRecordCount": 0, "confirmedClientErrorCount": 0, "pendingClientErrorCount": 0, "evaluatedOpportunities": None, "errorRate": None, "stableCapabilityRulesSatisfied": False}
        buckets = {key: [] for key in ("timing", "unanalysed", "empty", "pending", "pending-state", "wrong", "missed", "extra", "rhythm", "conflict")}
        duration = Decimal(0)
        for row, record in zip(rows, records):
            base = {"eventId": row["event_id"], "sourceContentHash": sha(record), "scoreRevision": row["score_revision"], "scoreSha256": row["score_sha256"]}
            value = record.get("durationSeconds")
            if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 86400:
                duration += Decimal(str(value))
                buckets["timing"].append({**base, "field": "/durationSeconds"})
            analysis = record.get("analysis") or {}
            state = analysis.get("status") if isinstance(analysis, dict) else None
            errors = analysis.get("errors") if isinstance(analysis, dict) else None
            if state == "uncertain":
                buckets["pending-state"].append({**base, "field": "/analysis/status", "originalState": state})
            if state == "unanalysed" or errors is None:
                buckets["unanalysed"].append({**base, "field": "/analysis", "originalState": state, "errorsNull": errors is None})
                continue
            if not isinstance(state, str) or state not in {"analysed", "uncertain"} or not isinstance(errors, list) or record.get("mode") in {"free", "playback"}:
                buckets["conflict"].append({**base, "field": "/analysis", "originalState": state})
                continue
            if not errors:
                buckets["empty"].append({**base, "field": "/analysis/errors", "originalState": state})
                continue
            seen, counts = set(), {key: 0 for key in ("pending", "wrong", "missed", "extra", "rhythm")}
            for error in errors:
                if not isinstance(error, dict):
                    buckets["conflict"].append({**base, "field": "/analysis/errors", "originalState": state})
                    continue
                identity = sha({key: val for key, val in error.items() if key != "confidence"})
                if identity in seen:
                    continue
                seen.add(identity)
                kind = error.get("type")
                if state == "uncertain" or kind == "uncertain":
                    counts["pending"] += 1
                elif isinstance(kind, str) and kind in {"wrong", "missed", "extra", "rhythm"}:
                    counts[kind] += 1
                else:
                    buckets["conflict"].append({**base, "field": "/analysis/errors", "originalState": state})
            for kind, count in counts.items():
                if count:
                    buckets[kind].append({**base, "field": "/analysis/errors", "originalState": state, "classification": kind, "dedupedCount": count})

        def add(key, kind, dimension, label, statement, display=None, state="verified_fact", limitations=None):
            ref = "evidence-" + key + "-" + source_hash[:16]
            bucket_key = {"practice-investment": "timing", "performance-unanalysed": "unanalysed", "empty-analysis-scope-unknown": "empty", "pending-performance-markers": "pending", "pending-analysis-state": "pending-state", "conflicting-record-state": "conflict", "capability-dimensions-unavailable": "unavailable"}.get(key, key.removesuffix("-client-count"))
            evidence[ref] = {"aggregationVersion": AGGREGATE_VERSION, "sourceSnapshotId": source_hash, "events": buckets[bucket_key]}
            facts.append({"factId": key, "kind": kind, "dimension": dimension, "label": label, "statement": statement, "displayValue": display, "claimState": state, "scope": scope["description"], "confidence": "high" if state == "verified_fact" else "low" if state == "provisional_pattern" else "unknown", "evidenceRefs": [ref], "limitations": limitations or []})

        if buckets["timing"]:
            display = format(duration, "f").rstrip("0").rstrip(".") if "." in format(duration, "f") else format(duration, "f")
            metrics["durationSeconds"] = display
            add("practice-investment", "practice_investment", "practice_investment", "已记录的练习计时", f"当前记录保存了 {len(buckets['timing'])} 条计时信息，累计记录时长为 {display} 秒。", f"{display} 秒", limitations=["计时由客户端报告，不证明真实演奏质量；暂停规则由记录提供者定义，重叠记录未抵扣。"])
        if buckets["unanalysed"]:
            metrics["unanalysedRecordCount"] = len(buckets["unanalysed"])
            add("performance-unanalysed", "data_quality", "other", "演奏尚未分析", f"有 {len(buckets['unanalysed'])} 条记录未分析或错误结果为 null，不能解释为零错音。", f"{len(buckets['unanalysed'])} 条记录", limitations=["不能据未分析记录判断技巧、正确率或稳定强项。"])
        if buckets["empty"]:
            metrics["emptyAnalysisRecordCount"] = len(buckets["empty"])
            add("empty-analysis-scope-unknown", "data_quality", "other", "空结果的评估范围未声明", f"有 {len(buckets['empty'])} 条分析结果列表为空，但协议没有声明已评估机会和覆盖范围。", f"{len(buckets['empty'])} 条记录", limitations=["空列表不能证明整次演奏零错音，也不能作为稳定强项。"])
        labels = {"wrong": "音高错误标记", "missed": "漏音标记", "extra": "多音标记", "rhythm": "节奏错误标记"}
        for kind, label in labels.items():
            count = sum(item["dedupedCount"] for item in buckets[kind])
            if count:
                metrics["confirmedClientErrorCount"] += count
                add(kind + "-client-count", "performance_observation", "rhythm" if kind == "rhythm" else "other", label, f"当前样本的客户端已分析记录包含 {count} 项{label}，仅说明收到的标记次数。", f"{count} 项", "provisional_pattern", ["演奏判断未经服务端独立核验；缺少已评估机会，不能计算错误率或判定稳定弱项。", "相同记录内相同语义标记已去重；缺少事件定位时无法区分重复上报与相同失误。"])
        pending = sum(item["dedupedCount"] for item in buckets["pending"])
        if pending:
            metrics["pendingClientErrorCount"] = pending
            add("pending-performance-markers", "pending_review", "other", "疑似演奏标记待复核", f"当前记录包含 {pending} 项疑似标记，仍保持待复核，不归入确定错误或正确表现。", f"{pending} 项", "pending_review", ["需要复核原始演奏结果；本次没有读取或听取录音。"])
        if buckets["pending-state"]:
            add("pending-analysis-state", "pending_review", "other", "分析状态待复核", f"有 {len(buckets['pending-state'])} 条记录的分析状态仍为 uncertain，不升级为确定演奏结论。", f"{len(buckets['pending-state'])} 条记录", "pending_review")
        if buckets["conflict"]:
            add("conflicting-record-state", "pending_review", "other", "记录状态不一致", "部分分析状态或字段与练习协议不一致，需要复核，未计入确定演奏统计。", None, "pending_review")
        buckets["unavailable"] = [{"eventId": row["event_id"], "sourceContentHash": sha(record), "field": "/analysis"} for row, record in zip(rows, records)]
        add("capability-dimensions-unavailable", "unavailable", "other", "音程、速度和稳定能力暂不可判定", "当前协议缺少预期音符匹配、已评估机会、可靠速度和技巧标签，不能生成音程、速度趋势、稳定强弱项或进步结论。", None, "unavailable", ["不同曲谱和版本没有被认定可比；错误计数没有失败率分母。"])
        status = "partial" if metrics["confirmedClientErrorCount"] else "investment_only" if buckets["timing"] else "pending_review" if pending or buckets["pending-state"] or buckets["conflict"] else "no_usable_data"
        coverage = {"description": scope["description"], "omittedDetail": True, "selectionPolicy": "所选记录全部在程序侧聚合；保留投入、未分析、客户端问题计数、待复核和限制；模型不接收原始逐音内容。", "limitations": ["模型未接收逐音记录、乐谱、曲名备注或录音；只解释本次已选汇总事实。", "计时不能替代演奏判定；未声明评估分母、匹配和可比条件。"] + (["超过最近 200 条的历史未纳入本次分析。"] if has_more else [])}
        model_input = {"schemaVersion": "2.0", "reportStatus": status, "locale": "zh-CN", "snapshotId": source_hash, "aggregateVersion": AGGREGATE_VERSION, "coverage": coverage, "facts": facts}
        validate_input(model_input, evidence, self.input_schema)
        if len(json_bytes([{"role": "system", "content": self.prompt}, {"role": "user", "content": json_bytes(model_input).decode()}])) + 512 > MAX_INPUT_TOKEN_BOUND:
            raise AnalysisError(413, "事实汇总超过输入预算，请选择较少的记录。")
        return {"modelInput": model_input, "scope": scope, "evidenceIndex": evidence, "metrics": metrics, "sourceHash": source_hash}

    def fallback(self, prepared, request_id, *, retry_allowed):
        observations, pending = [], []
        for fact in prepared["modelInput"]["facts"]:
            item = {"title": fact["label"], "description": fact["statement"], "factIds": [fact["factId"]]}
            if fact["kind"] in {"practice_investment", "performance_observation"} and len(observations) < 4:
                observations.append(item)
            elif fact["claimState"] == "pending_review" and len(pending) < 4:
                pending.append(item)
        output = {"schemaVersion": "2.0", "status": prepared["modelInput"]["reportStatus"], "summary": "文字分析暂未生成，可稍后重试。已核对的记录汇总继续保留。" if retry_allowed else "文字分析请求结果尚未确认，已保留记录汇总；同次请求不会再次调用分析服务。", "observations": observations, "weaknesses": [], "strengths": [], "progress": [], "pendingReview": pending, "suggestions": [], "limitations": prepared["modelInput"]["coverage"]["limitations"] + ["本次显示程序汇总事实，没有生成成功的文字解释。"]}
        validate_output(output, prepared["modelInput"], self.output_schema, project_summary=False)
        return self.envelope(prepared, request_id, output, "fallback", False, retry_allowed)

    def envelope(self, prepared, request_id, output, state, cached, retry_allowed=False):
        return {"id": request_id, "output": output, "facts": prepared["modelInput"]["facts"], "scope": prepared["scope"], "evidenceIndex": prepared["evidenceIndex"], "metrics": prepared["metrics"], "provider": "DeepSeek", "model": self.fingerprint["model"], "generationStatus": state, "summarySource": "program" if state != "completed" or output["status"] in LIMITED_SUMMARIES else "model", "cached": cached, "retryAllowed": retry_allowed}

    def analyse(self, user_id, request_id, event_ids=None):
        if not isinstance(request_id, str) or not UUID_RE.fullmatch(request_id):
            raise AnalysisError(400, "分析请求标识无效。")
        prepared = self.input(user_id, event_ids)  # Authorise before EVERY cache hit.
        input_sha = sha({"owner": user_id, "aggregate": prepared["modelInput"], "source": prepared["sourceHash"], "fingerprint": self.fingerprint})
        active_key, reserved = (user_id, input_sha), False
        try:
            with self.lock, self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM practice_analysis_v2_requests WHERE user_id=? AND request_id=?", (user_id, request_id)).fetchone()
                if old:
                    if old["input_sha"] != input_sha:
                        raise AnalysisError(409, "记录、规则或分析版本已变化，请发起新的分析。")
                    if old["state"] in {"completed", "fallback", "unknown"}:
                        result = parse_json(old["result"])
                        validate_output(result["output"], prepared["modelInput"], self.output_schema)
                        return {**result, "cached": old["state"] == "completed", "reusedRequest": True}
                    if active_key in self.active:
                        raise AnalysisError(409, "同次分析仍在处理，请稍后继续查看。")
                uncertain = db.execute("SELECT request_id FROM practice_analysis_v2_requests WHERE user_id=? AND input_sha=? AND state IN ('pending','unknown') LIMIT 1", (user_id, input_sha)).fetchone()
                if uncertain:
                    if active_key in self.active:
                        raise AnalysisError(409, "这份记录的分析仍在处理，请稍后继续查看。")
                    result = self.fallback(prepared, request_id, retry_allowed=False)
                    if old:
                        db.execute("UPDATE practice_analysis_v2_requests SET state='unknown',result=? WHERE user_id=? AND request_id=?", (json_bytes(result).decode(), user_id, request_id))
                    else:
                        db.execute("INSERT INTO practice_analysis_v2_requests VALUES(?,?,?,'unknown',?,0,?)", (user_id, request_id, input_sha, json_bytes(result).decode(), self.clock()))
                    return result
                cached = db.execute("SELECT result FROM practice_analysis_v2_cache WHERE user_id=? AND input_sha=?", (user_id, input_sha)).fetchone()
                if cached:
                    output = parse_json(cached[0])
                    validate_output(output, prepared["modelInput"], self.output_schema)
                    result = self.envelope(prepared, request_id, output, "completed", True)
                    db.execute("INSERT INTO practice_analysis_v2_requests VALUES(?,?,?,'completed',?,0,?)", (user_id, request_id, input_sha, json_bytes(result).decode(), self.clock()))
                    return result
                attempts = db.execute("SELECT count(*) FROM practice_analysis_v2_requests WHERE user_id=? AND attempted=1 AND created>?", (user_id, self.clock() - 3600)).fetchone()[0]
                if attempts >= 6:
                    raise AnalysisError(429, "本小时已发起 6 次文字分析，请稍后再试。")
                if not self.capacity.acquire(blocking=False):
                    raise AnalysisError(429, "文字分析正在处理其他请求，请稍后重试。")
                reserved = True
                db.execute("INSERT INTO practice_analysis_v2_requests VALUES(?,?,?,'pending',NULL,1,?)", (user_id, request_id, input_sha, self.clock()))
                self.active.add(active_key)
        except Exception:
            if reserved:
                self.active.discard(active_key)
                self.capacity.release()
            raise
        try:
            try:
                output = validate_output(self.provider(prepared["modelInput"]), prepared["modelInput"], self.output_schema)
                result, state = self.envelope(prepared, request_id, output, "completed", False), "completed"
            except AnalysisError as error:
                result, state = self.fallback(prepared, request_id, retry_allowed=not error.uncertain), "unknown" if error.uncertain else "fallback"
            except (ValueError, KeyError, IndexError, TypeError):
                result, state = self.fallback(prepared, request_id, retry_allowed=True), "fallback"
            except Exception:
                result, state = self.fallback(prepared, request_id, retry_allowed=False), "unknown"
            with self.store.connect() as db:
                db.execute("UPDATE practice_analysis_v2_requests SET state=?,result=? WHERE user_id=? AND request_id=?", (state, json_bytes(result).decode(), user_id, request_id))
                if state == "completed":
                    db.execute("INSERT OR REPLACE INTO practice_analysis_v2_cache VALUES(?,?,?,?)", (user_id, input_sha, json_bytes(result["output"]).decode(), self.clock()))
            return result
        finally:
            with self.lock:
                self.active.discard(active_key)
            self.capacity.release()


def from_environment(store):
    key_file = os.environ.get("NOTELITE_DEEPSEEK_KEY_FILE")
    if not key_file:
        return None
    try:
        return PracticeAnalysis(store, DeepSeekProvider(key_file, os.environ.get("NOTELITE_DEEPSEEK_MODEL", "deepseek-flash")))
    except (AnalysisError, OSError, UnicodeError, ValueError):
        # A missing optional private rules package disables analysis, not login.
        return None
