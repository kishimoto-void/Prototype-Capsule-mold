#!/usr/bin/env python3
"""AXIOM Capsule min4.3 — Proto-Mold Capsule reference implementation.

Purpose:
  A consistency-preserving state container, not a memory store. This file is a
  prototype mold from which purpose-specific Capsule variants may be derived.

Proto-Mold Capsule — LLM modification contract (design note)
============================================================
This section is a maintenance contract for humans and LLM-based code editors.
It describes intended boundaries; comments do not enforce these rules at runtime.

Core responsibilities:
  - αβ (Inner): immutable-by-contract core. Hash-A covers alpha rules, beta
    fields, and β facts. Mutable Δ/IS state must not be folded into Hash-A.
  - γ (Gamma): address only: time_label, project, topic. Do not silently infer
    missing axes, treat an empty γ as a global query, or add implicit axes.
  - Δ (Delta): append-ordered change history. A Δ write does not adopt IS.
  - IS: bounded current-state lines, isolated from Δ. Do not auto-copy Δ into IS.
  - Gate: NONE rejects; HUMAN queues; an allowed non-human write may commit.
  - Hash-B: digest of the defined mutable payload (Δ, IS, pending, is_pending),
    not a signature and not a guarantee against an attacker who can replace both
    state and its reference digest. Keep its scope explicit.
  - Vocabulary: WORDS is the built-in closed set. restore() intentionally does
    not trust snapshot.adopted; custom words must be re-authorized through
    adopt_word() after restore. Custom-word history is therefore not restored.

Safe modification rules:
  1. Make the smallest change that satisfies the requested behavior; do not
     introduce a new layer or merge αβ, γ, Δ, IS, gate, or hashes without an
     explicit design decision.
  2. Keep packet keys and nested field sets closed. If a schema changes, update
     the parser, validation/preflight, write path, restore path, and docs together.
  3. Preserve ingest(atomic=False) behavior unless compatibility is explicitly
     changed. atomic=True must reject on preflight errors before mutating state.
  4. Treat restore input as untrusted. Preserve bounded work, validate container
     and field types, and do not restore custom vocabulary as trusted authority.
  5. Keep status outcomes truthful: distinguish success, partial, queued,
     rejected, and noop. A duplicate that was not appended is not a new write.
  6. If a change affects canonical payloads, Hash-A/Hash-B, ordering, γ matching,
     time grain, vocabulary, eviction, or restore, add regression tests first.
  7. Never claim a test passed unless it was actually executed. State untested
     compatibility risks when changing public APIs or serialized snapshots.

Recommended change procedure:
  A. State the intended behavior and invariants affected.
  B. Change implementation and this contract together when semantics change.
  C. Add positive, negative, boundary, restore, and regression test cases.
  D. Run syntax checks and the targeted/full test suite; report exact coverage.

Code map (edit the owning path, not only the nearest visible function):
  - Canonical hashes: Inner.payload/compute_hash/seal/intact, mutable_view,
    hash_mutable, Capsule.hash_b.
  - Packet contract: _closed, parse_packet, _validate_preflight, ingest.
  - γ address and time grain: coarse_time, normalize_filt, Gamma.matches,
    _prepare_address, gamma_has_axis, filt_has_axis.
  - Δ lifecycle: write_delta, _commit, pending, approve_pending, reject_pending.
  - IS lifecycle: write_is, _adopt_is, cap_is_bag, approve_is, reject_is.
  - Queries: query_delta, query_gamma, latest_at, latest, history, lookup,
    is_lines. Update tests for both exact=True and exact=False when relevant.
  - Persistence and trust boundary: snapshot, restore. Test malformed input,
    bounds, custom vocabulary, ordering, and rebuilt indexes after any change.
  - Text output: render. Do not let render infer missing γ dimensions or mutate state.

Compatibility note:
  Snapshot structure is an interchange contract. Do not rename, remove, or
  reinterpret keys without an explicit migration/versioning plan.

Gamma = time + project + topic. Delta = updates. Mold: axiom_min.py.

Capsule is a consistency-preserving state container, not a memory store.
Hash-B is integrity of Δ/IS/pending. It is not sealed into Hash-A.
See CAPSULE_CORE.md. that note is not sealed into Hash-A.

No new layer:
  - IS is Δ only. facts stay inside αβ
  - latest/is_lines default exact=True
  - exact=True equals supplied filter keys only; missing γ axes are wildcards
  - write_delta calls gate(). NONE drops. HUMAN queues
  - render prints supplied γ axes from the filter
  - latest is append order. η does not decide writes
  - LLM writes only via closed packet {gamma, delta, is}
  - IS is isolated from Δ. write_delta never adopts IS
  - query_gamma reads _index (IS-only addresses stay visible)
  - query/render coarsen time_label with the same grain as write
  - identity default 1.0. caller must pass it to trip the 0.20 gate
  - Delta.timestamp is audit only. latest stays append order
  - γ packet needs at least one axis. empty address is not an address
  - index grows only after a committed Δ or adopted IS
  - IS_MAX caps each address. render does not recut across addresses
  - IS upserts by closed word. same field replaces its previous line
  - IS eviction drops oldest non-pinned word. 状態 is pinned. if every line is pinned, oldest goes
  - ingest reports evicted IS lines. not a new memory layer
  - adopt_word uses the same gate as write. HUMAN / NONE do not widen WORDS
  - Δ pending skips the same address+field+new_value already queued
  - grain month=YYYY-MM, day=YYYY-MM-DD, week=ISO YYYY-Www when a day is present
  - unknown grain is not month. write drops. query returns empty
  - empty γ is rejected on write_delta / write_is, not only ingest
  - restore does not load adopted. adopt_word stays the only widen path
  - restore / approve_is keep only closed-word IS lines
  - restore keeps only closed-word Δ rows
  - adopt_word rejects empty / whitespace words
  - query / is_lines / render need a non-empty γ axis. {} is not the whole map
  - Gamma.matches reads only time_label / project / topic. other keys fail the match
  - ingest unknown grain returns None, not a packet with gamma=None
  - identity that is not finite or outside [0, 1] is NONE, not a crash
  - closed packet text, row count, and field sizes are bounded
  - atomic ingest rejects a packet before mutation if preflight fails
  - ingest reports success / partial / queued / rejected / noop explicitly
  - Hash-B matches only against an independently retained reference digest
  - oversized JSON payloads rejected before parsing; malformed restore containers ignored
  - boolean identity values rejected instead of treated as numeric scores
  - week grain needs a real calendar day; 2026-99-99 is not a week address
"""
from __future__ import annotations
import hashlib, json, time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from math import isfinite
import re
from typing import Any, Optional

IS_MAX = 3
IS_PIN = frozenset({"状態"})
ETA_HIGH = 0.35
GRAINS = frozenset({"month", "day", "week"})
WORDS = frozenset({"課題", "改善点", "結論", "立場", "状態"})
WORD_ALIAS = {"issue": "課題", "improve": "改善点", "improvement": "改善点", "conclusion": "結論", "position": "立場", "status": "状態", "state": "状態"}
PACKET_KEYS = frozenset({"gamma", "delta", "is"})
GAMMA_KEYS = frozenset({"time_label", "project", "topic"})
DELTA_KEYS = frozenset({"field", "new_value", "old_value", "source_id", "reason"})
IS_KEYS = frozenset({"field", "value"})
SNAP_DELTA_KEYS = frozenset({"field", "old_value", "new_value", "timestamp", "source_id", "reason"})

# Closed input contract limits. These bound accidental / malformed LLM payloads.
MAX_PACKET_ROWS = 100
MAX_PACKET_CHARS = 1_000_000
MAX_WORD_LENGTH = 64
MAX_VALUE_LENGTH = 8192
MAX_GAMMA_LENGTH = 256
MAX_SOURCE_ID_LENGTH = 256
MAX_REASON_LENGTH = 1024
# Defensive restore bounds. Excess history is truncated from the oldest end.
MAX_RESTORE_ROWS = 100_000
MAX_RESTORE_PENDING = 10_000
MAX_RESTORE_ADDRESSES = 50_000
MAX_RESTORE_IS_LINES_PER_ADDRESS = 100

def _sha(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()

def mutable_view(snap: dict) -> dict:
    # Hash-B payload. adopted is not part of B.
    return {
        "deltas": (snap or {}).get("deltas") or [],
        "is": (snap or {}).get("is") or {},
        "pending": (snap or {}).get("pending") or [],
        "is_pending": (snap or {}).get("is_pending") or [],
    }

def hash_mutable(snap: dict) -> str:
    return _sha(mutable_view(snap))

def canon_word(field: str) -> str:
    """Canonicalize a field name without allowing malformed input to crash writes."""
    if not isinstance(field, str):
        return ""
    f = field.strip()
    if not f or len(f) > MAX_WORD_LENGTH:
        return ""
    return WORD_ALIAS.get(f, WORD_ALIAS.get(f.lower(), f))

def _valid_text(value: Any, *, allow_empty: bool = False, max_length: int = MAX_VALUE_LENGTH) -> bool:
    return (isinstance(value, str)
            and len(value) <= max_length
            and (allow_empty or bool(value.strip())))

def coarse_time(label: str, grain: str = "month") -> Optional[str]:
    """Normalize a calendar label; reject malformed dates instead of indexing them."""
    if grain not in GRAINS or not isinstance(label, str):
        return None
    s = label.strip().replace("/", "-")
    if grain == "month":
        if not re.match(r"^\d{4}-\d{2}$", s) and not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", s):
            return None
        try:
            year, month = int(s[:4]), int(s[5:7])
            date(year, month, 1)
            if len(s) >= 10:
                date.fromisoformat(s[:10])
        except (ValueError, TypeError):
            return None
        return s[:7]
    if grain == "day":
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", s):
            return None
        try:
            date.fromisoformat(s[:10])
        except ValueError:
            return None
        return s[:10]
    # Week labels are always derived from a real calendar day.
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[T ])", s):
        return None
    try:
        iso = date.fromisoformat(s[:10]).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    except ValueError:
        return None

def normalize_filt(filt, grain="month"):
    # Only γ axes are accepted. Invalid filters return None rather than raising.
    if grain not in GRAINS or not isinstance(filt, dict):
        return None
    if any(k not in GAMMA_KEYS for k in filt):
        return None
    out = {}
    for key, value in filt.items():
        if not isinstance(value, str):
            return None
        value = value.strip()
        if key == "time_label" and value:
            stamped = coarse_time(value, grain=grain)
            if stamped is None:
                return None
            value = stamped
        out[key] = value
    return out

def gamma_line(filt: dict) -> str:
    # shows supplied dimensions only. missing axes stay blank, not inferred.
    parts = [filt.get(k, "") for k in ("time_label", "project", "topic")]
    return " / ".join(p for p in parts if p) or "(unscoped)"

@dataclass(frozen=True)
class Alpha:
    rules: tuple[str, ...] = ("βを遵守する", "核を動かさない", "今のγ住所の外を補完しない", "βとΔを混ぜない")

@dataclass(frozen=True)
class Beta:
    name: str
    tone: str
    center: str
    values: tuple[str, ...]

@dataclass(frozen=True)
class BetaFact:
    knowledge_id: str
    field: str
    value: str

@dataclass
class Inner:
    alpha: Alpha
    beta: Beta
    facts: tuple[BetaFact, ...] = ()
    hash_a: str = ""
    def payload(self):
        return {"alpha": list(self.alpha.rules), "beta": {"name": self.beta.name, "tone": self.beta.tone, "center": self.beta.center, "values": list(self.beta.values)}, "facts": [asdict(f) for f in self.facts]}
    def compute_hash(self):
        return _sha(self.payload())
    def seal(self):
        self.hash_a = self.compute_hash(); return self
    def intact(self):
        return bool(self.hash_a) and self.hash_a == self.compute_hash()
    def fact_lines(self):
        return [f"{f.field}={f.value}" for f in self.facts]

@dataclass(frozen=True)
class Gamma:
    time_label: str = ""
    project: str = ""
    topic: str = ""
    def matches(self, filt, exact=True):
        # exact = equality on supplied γ axes only. unspecified γ axes stay wildcards.
        # exact does not mean "all three axes must be present".
        # key / label / matches are methods, not axes.
        if not isinstance(filt, dict):
            return False
        for k, v in filt.items():
            if k not in GAMMA_KEYS:
                return False
            val = str(getattr(self, k))
            needle = str(v)
            if exact and val != needle: return False
            if not exact and needle.lower() not in val.lower(): return False
        return True
    def label(self):
        return " / ".join(p for p in (self.time_label, self.project, self.topic) if p) or "(unscoped)"
    def key(self):
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

def gamma_has_axis(g: Gamma) -> bool:
    return any(str(getattr(g, k, "") or "").strip() for k in ("time_label", "project", "topic"))

def filt_has_axis(filt) -> bool:
    # no supplied γ axis means no route. empty filter is not every address.
    if not isinstance(filt, dict):
        return False
    return any(str(filt.get(k, "") or "").strip() for k in ("time_label", "project", "topic"))

def is_line_word(line) -> Optional[str]:
    # Stored IS is "語=値". Enforce the same bounds on live and restored rows.
    if not isinstance(line, str) or "=" not in line or len(line) > MAX_VALUE_LENGTH + MAX_WORD_LENGTH + 1:
        return None
    field, _, value = line.partition("=")
    if not _valid_text(field, max_length=MAX_WORD_LENGTH) or not _valid_text(value):
        return None
    return canon_word(field)

def cap_is_bag(bag, incoming_line: str) -> tuple[list[str], list[str]]:
    # one slot per closed word. 状態 stays unless every visible line is pinned.
    word = is_line_word(incoming_line)
    if word is None:
        return list(bag or []), []
    out = []
    for line in bag or []:
        w = is_line_word(line)
        if w is None or w == word:
            continue
        out.append(line)
    out.append(incoming_line)
    evicted = []
    while len(out) > IS_MAX:
        drop_at = next((i for i, line in enumerate(out) if is_line_word(line) not in IS_PIN), 0)
        evicted.append(out.pop(drop_at))
    return out, evicted

GammaIndex = Gamma  # alias. index row is the address itself.

@dataclass(frozen=True)
class Delta:
    field: str
    old_value: Optional[str]
    new_value: str
    timestamp: float
    source_id: str = ""
    reason: str = ""
    def line(self):
        return f"{self.field}={self.new_value}" if self.old_value is None else f"{self.field}:{self.old_value}->{self.new_value}"

DeltaIndex = Delta  # alias. index row is the update itself.

@dataclass
class Eta:
    pull: float = 0.0
    streak: int = 0
    def step(self, tone, identity, values):
        gap = 0.45*(1-tone)+0.40*(1-identity)+0.15*(1-values)
        self.pull = max(0.0, min(1.0, gap))
        if self.pull >= 0.30: self.streak += 1
        else:
            self.streak = 0; self.pull *= 0.45
    def high(self):
        return self.pull >= ETA_HIGH

class Write:
    NONE = "none"; DELTA = "delta"; HUMAN = "needs_human"; UNKNOWN_WORD = "unknown_word"; BAD_PACKET = "bad_packet"; IS = "is"

def gate(eta: Eta, identity: float, human: bool) -> str:
    # eta kept for gate-policy compatibility. min3 write does not read it.
    _ = eta
    if isinstance(identity, bool):
        return Write.NONE
    try:
        identity = float(identity)
    except (TypeError, ValueError, OverflowError):
        return Write.NONE
    if not isfinite(identity) or not 0.0 <= identity <= 1.0:
        return Write.NONE
    if identity < 0.20: return Write.NONE
    if human: return Write.HUMAN
    return Write.DELTA

def _closed(obj, allowed):
    if not isinstance(obj, dict):
        return None
    if set(obj) - allowed:
        return None
    return obj

def _strip_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = s[3:]
    if s[:4].lower() == "json":
        s = s[4:]
    end = s.rfind("```")
    if end >= 0:
        s = s[:end]
    return s.strip()

def parse_packet(raw):
    """Parse a closed LLM packet. Invalid shape, types, or bounds return None."""
    if isinstance(raw, str):
        # Bound parser work before JSON decoding; oversized / deeply nested payloads
        # are rejected without touching capsule state.
        if len(raw) > MAX_PACKET_CHARS:
            return None
        raw = _strip_fence(raw)
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, RecursionError):
            return None
    pkt = _closed(raw, PACKET_KEYS)
    if pkt is None or "gamma" not in pkt:
        return None

    g = _closed(pkt.get("gamma"), GAMMA_KEYS)
    if g is None:
        return None
    clean_gamma = {}
    for key, value in g.items():
        if not _valid_text(value, allow_empty=True, max_length=MAX_GAMMA_LENGTH):
            return None
        clean_gamma[key] = value.strip()
    if not any(clean_gamma.get(k, "") for k in GAMMA_KEYS):
        return None
    pkt = {**pkt, "gamma": clean_gamma}

    if "delta" in pkt:
        rows = pkt["delta"]
        if not isinstance(rows, list) or len(rows) > MAX_PACKET_ROWS:
            return None
        clean_rows = []
        for row in rows:
            d = _closed(row, DELTA_KEYS)
            if d is None or "field" not in d or "new_value" not in d:
                return None
            if not _valid_text(d["field"], max_length=MAX_WORD_LENGTH):
                return None
            if not _valid_text(d["new_value"]):
                return None
            if "old_value" in d and d["old_value"] is not None and not _valid_text(d["old_value"], allow_empty=True):
                return None
            if "source_id" in d and not _valid_text(d["source_id"], allow_empty=True, max_length=MAX_SOURCE_ID_LENGTH):
                return None
            if "reason" in d and not _valid_text(d["reason"], allow_empty=True, max_length=MAX_REASON_LENGTH):
                return None
            clean_rows.append(dict(d))
        pkt = {**pkt, "delta": clean_rows}

    if "is" in pkt:
        rows = pkt["is"]
        if not isinstance(rows, list) or len(rows) > MAX_PACKET_ROWS:
            return None
        clean_rows = []
        for row in rows:
            item = _closed(row, IS_KEYS)
            if item is None or "field" not in item or "value" not in item:
                return None
            if not _valid_text(item["field"], max_length=MAX_WORD_LENGTH):
                return None
            if not _valid_text(item["value"]):
                return None
            clean_rows.append(dict(item))
        pkt = {**pkt, "is": clean_rows}
    return pkt


def packet_validation_errors(pkt: dict, allowed_words) -> list[dict]:
    """Semantic preflight used by atomic ingest; it performs no state mutation."""
    errors = []
    for kind in ("delta", "is"):
        for i, row in enumerate(pkt.get(kind) or []):
            word = canon_word(row.get("field"))
            if word not in allowed_words:
                errors.append({"kind": kind, "index": i, "field": row.get("field"), "code": Write.UNKNOWN_WORD})
    return errors

def _load_gamma(obj) -> Optional[Gamma]:
    g = _closed(obj, GAMMA_KEYS)
    if g is None:
        return None
    axes = {}
    for key in GAMMA_KEYS:
        value = g.get(key, "")
        if not _valid_text(value, allow_empty=True, max_length=MAX_GAMMA_LENGTH):
            return None
        axes[key] = value.strip()
    address = Gamma(**axes)
    return address if gamma_has_axis(address) else None

def _load_delta(obj) -> Optional[Delta]:
    d = _closed(obj, SNAP_DELTA_KEYS)
    if d is None or "field" not in d or "new_value" not in d:
        return None
    if not _valid_text(d["field"], max_length=MAX_WORD_LENGTH) or not _valid_text(d["new_value"]):
        return None
    old_value = d.get("old_value")
    source_id = d.get("source_id", "")
    reason = d.get("reason", "")
    if old_value is not None and not _valid_text(old_value, allow_empty=True):
        return None
    if not _valid_text(source_id, allow_empty=True, max_length=MAX_SOURCE_ID_LENGTH):
        return None
    if not _valid_text(reason, allow_empty=True, max_length=MAX_REASON_LENGTH):
        return None
    try:
        ts = float(d.get("timestamp") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not isfinite(ts):
        return None
    return Delta(
        field=canon_word(d["field"]), old_value=old_value, new_value=d["new_value"],
        timestamp=ts, source_id=source_id, reason=reason,
    )

def packet_gamma(pkt) -> Gamma:
    g = pkt.get("gamma") or {}
    return Gamma(
        time_label=str(g.get("time_label", "")),
        project=str(g.get("project", "")),
        topic=str(g.get("topic", "")),
    )

def _safe_pop(rows: list, index: int):
    """Pop only a valid integer index; malformed/out-of-range indices are no-ops."""
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    if index < -len(rows) or index >= len(rows):
        return None
    return rows.pop(index)

class Capsule:
    def __init__(self, inner: Inner):
        self.inner = inner.seal()
        self._deltas = []
        self._pending = []
        self._is = {}
        self._is_pending = []
        self._index = defaultdict(list)
        self._by_project = defaultdict(list)
        self._by_topic = defaultdict(list)
        self._adopted = set()
        self.eta = Eta()
        self.last_write = Write.NONE
        self.last_is_evicted = []
    def allowed_words(self):
        return frozenset(WORDS | self._adopted)
    def adopt_word(self, field, human: bool = False, identity: float = 1.0):
        # same gate as write. does not add a pending-word layer.
        w = canon_word(field)
        if not str(w).strip():
            self.last_write = Write.UNKNOWN_WORD
            return None
        decision = gate(self.eta, identity, human)
        if decision == Write.NONE:
            self.last_write = Write.NONE
            return None
        if decision == Write.HUMAN:
            self.last_write = Write.HUMAN
            return None
        self._adopted.add(w)
        return w
    def _index_put(self, g: Gamma) -> None:
        # buckets only. time is judged later by Gamma.matches.
        # empty γ is not an address. "::" is not created as a place.
        if not gamma_has_axis(g):
            return
        k = f"{g.project}::{g.topic}"
        if g not in self._index[k]:
            self._index[k].append(g)
        if g.project and g not in self._by_project[g.project]:
            self._by_project[g.project].append(g)
        if g.topic and g not in self._by_topic[g.topic]:
            self._by_topic[g.topic].append(g)
    def _prepare_address(self, address: Gamma, grain: str = "month") -> Optional[Gamma]:
        if grain not in GRAINS or not isinstance(address, Gamma):
            return None
        axes = {}
        for key in ("time_label", "project", "topic"):
            value = getattr(address, key)
            if not _valid_text(value, allow_empty=True, max_length=MAX_GAMMA_LENGTH):
                return None
            axes[key] = value.strip()
        if axes["time_label"]:
            stamped = coarse_time(axes["time_label"], grain=grain)
            if stamped is None:
                return None
            axes["time_label"] = stamped
        return Gamma(**axes)
    def write_delta(self, address: Gamma, field: str, new_value: str, old_value: Optional[str] = None, source_id: str = "", reason: str = "", keep_history: bool = True, human: bool = False, identity: float = 1.0, grain: str = "month") -> Optional[Delta]:
        # identity=1.0 means the 0.20 gate stays open unless the caller passes a score.
        if grain not in GRAINS:
            self.last_write = Write.NONE
            return None
        word = canon_word(field)
        if word not in self.allowed_words():
            self.last_write = Write.UNKNOWN_WORD
            return None
        if (not _valid_text(new_value) or
                (old_value is not None and not _valid_text(old_value, allow_empty=True)) or
                not _valid_text(source_id, allow_empty=True, max_length=MAX_SOURCE_ID_LENGTH) or
                not _valid_text(reason, allow_empty=True, max_length=MAX_REASON_LENGTH)):
            self.last_write = Write.BAD_PACKET
            return None
        decision = gate(self.eta, identity, human)
        self.last_write = decision
        if decision == Write.NONE:
            return None
        address = self._prepare_address(address, grain=grain)
        if address is None or not gamma_has_axis(address):
            self.last_write = Write.BAD_PACKET
            return None
        d = Delta(word, old_value, new_value, time.time(), source_id, reason)
        if decision == Write.HUMAN:
            dup = any(g == address and x.field == d.field and x.new_value == d.new_value for g, x in self._pending)
            if not dup:
                self._pending.append((address, d))
            return None
        return self._commit(address, d, keep_history=keep_history)
    def _commit(self, address, d, keep_history=True):
        if not gamma_has_axis(address):
            self.last_write = Write.BAD_PACKET
            return None
        if d.field not in self.allowed_words():
            self.last_write = Write.UNKNOWN_WORD
            return None
        if not keep_history:
            self._deltas = [(c, x) for c, x in self._deltas if not (c == address and x.field == d.field)]
        self._deltas.append((address, d))
        self._index_put(address)
        self.last_write = Write.DELTA
        return d
    def write_is(self, address: Gamma, field: str, value: str, human: bool = False, identity: float = 1.0, grain: str = "month") -> Optional[str]:
        """Adopt into isolated IS. Does not append Δ. identity=1.0 leaves the gate open."""
        if grain not in GRAINS:
            self.last_write = Write.NONE
            return None
        word = canon_word(field)
        if not _valid_text(value):
            self.last_write = Write.BAD_PACKET
            return None
        text = value.strip()
        if word not in self.allowed_words():
            self.last_write = Write.UNKNOWN_WORD
            return None
        decision = gate(self.eta, identity, human)
        if decision == Write.NONE:
            self.last_write = Write.NONE
            return None
        address = self._prepare_address(address, grain=grain)
        if address is None or not gamma_has_axis(address):
            self.last_write = Write.BAD_PACKET
            return None
        line = f"{word}={text}"
        if decision == Write.HUMAN:
            item = (address, line)
            if item not in self._is_pending:
                self._is_pending.append(item)
            self.last_write = Write.HUMAN
            return None
        return self._adopt_is(address, line)
    def _adopt_is(self, address, line):
        if not gamma_has_axis(address):
            self.last_write = Write.BAD_PACKET
            return None
        word = is_line_word(line)
        if word is None or word not in self.allowed_words():
            self.last_write = Write.UNKNOWN_WORD
            return None
        key = address.key()
        bag, evicted = cap_is_bag(self._is.get(key, []), line)
        self._is[key] = bag
        self.last_is_evicted = evicted
        self._index_put(address)
        self.last_write = Write.IS
        return line
    def approve_is(self, index=-1):
        item = _safe_pop(self._is_pending, index)
        if item is None:
            return None
        address, line = item
        adopted = self._adopt_is(address, line)
        if adopted is None:
            return None
        return adopted
    def reject_is(self, index=-1):
        return _safe_pop(self._is_pending, index)
    def ingest(self, raw: Any, human: bool = False, identity: float = 1.0,
               grain: str = "month", atomic: bool = False) -> Optional[dict]:
        """Only LLM write entry. atomic=True rejects the whole packet on preflight errors.

        Existing default behavior remains best-effort/partial-success. Returned result
        keeps the min3 keys and adds status/errors/queued/Hash-B diagnostics.
        """
        pkt = parse_packet(raw)
        if pkt is None:
            self.last_write = Write.BAD_PACKET
            return None
        if grain not in GRAINS:
            self.last_write = Write.NONE
            return None
        address = self._prepare_address(packet_gamma(pkt), grain=grain)
        if address is None or not gamma_has_axis(address):
            self.last_write = Write.BAD_PACKET
            return None

        errors = packet_validation_errors(pkt, self.allowed_words())
        try:
            if isinstance(identity, bool):
                raise ValueError
            score = float(identity)
            if not isfinite(score) or not 0.0 <= score <= 1.0:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            errors.append({"kind": "gate", "code": Write.NONE, "message": "identity must be a finite number in [0, 1]"})
        else:
            if score < 0.20:
                errors.append({"kind": "gate", "code": Write.NONE, "message": "identity is below the 0.20 write threshold"})

        if atomic and errors:
            self.last_write = errors[0].get("code", Write.BAD_PACKET)
            return {
                "gamma": address, "delta": [], "is": [], "dropped": list(errors),
                "queued": [], "skipped": [], "evicted": [], "write": self.last_write,
                "wrote": {"delta": 0, "is": 0}, "status": "rejected",
                "atomic": True, "errors": list(errors), "hash_b": self.hash_b(),
                "integrity": self.integrity_report(),
            }

        out = {"gamma": address, "delta": [], "is": [], "dropped": [],
               "queued": [], "skipped": [], "evicted": [], "write": Write.NONE,
               "errors": list(errors), "atomic": bool(atomic)}
        for row in pkt.get("delta") or []:
            pending_before = len(self._pending)
            d = self.write_delta(
                address, row["field"], row["new_value"],
                old_value=row.get("old_value"),
                source_id=row.get("source_id", "llm"),
                reason=row.get("reason", ""), human=human, identity=identity, grain=grain,
            )
            if d is not None:
                out["delta"].append(d)
            elif self.last_write == Write.HUMAN and len(self._pending) > pending_before:
                out["queued"].append({"kind": "delta", "field": row.get("field"), "write": self.last_write})
            elif self.last_write == Write.HUMAN:
                out["skipped"].append({"kind": "delta", "field": row.get("field"), "code": "duplicate_pending"})
            else:
                out["dropped"].append({"kind": "delta", "field": row.get("field"), "write": self.last_write})

        for row in pkt.get("is") or []:
            pending_is_before = len(self._is_pending)
            line = self.write_is(address, row["field"], row["value"],
                                 human=human, identity=identity, grain=grain)
            if line is not None:
                out["is"].append(line)
                out["evicted"].extend(self.last_is_evicted)
            elif self.last_write == Write.HUMAN and len(self._is_pending) > pending_is_before:
                out["queued"].append({"kind": "is", "field": row.get("field"), "write": self.last_write})
            elif self.last_write == Write.HUMAN:
                out["skipped"].append({"kind": "is", "field": row.get("field"), "code": "duplicate_pending"})
            else:
                out["dropped"].append({"kind": "is", "field": row.get("field"), "write": self.last_write})

        out["wrote"] = {"delta": len(out["delta"]), "is": len(out["is"])}
        if out["is"]:
            out["write"] = Write.IS
        elif out["delta"]:
            out["write"] = Write.DELTA
        elif out["queued"]:
            out["write"] = Write.HUMAN
            self.last_write = Write.HUMAN
        elif out["dropped"]:
            out["write"] = self.last_write
        else:
            self.last_write = Write.NONE
            out["write"] = Write.NONE

        did_write = bool(out["delta"] or out["is"])
        if out["dropped"] and (did_write or out["queued"]):
            out["status"] = "partial"
        elif did_write:
            out["status"] = "success"
        elif out["queued"]:
            out["status"] = "queued"
        elif out["dropped"]:
            out["status"] = "rejected"
        else:
            out["status"] = "noop"
        out["hash_b"] = self.hash_b()
        out["integrity"] = self.integrity_report()
        return out
    def pending(self):
        return list(self._pending)
    def pending_is(self):
        return list(self._is_pending)
    def approve_pending(self, index=-1, keep_history=True):
        item = _safe_pop(self._pending, index)
        if item is None:
            return None
        address, d = item
        return self._commit(address, d, keep_history=keep_history)
    def reject_pending(self, index=-1):
        return _safe_pop(self._pending, index)
    def _addresses(self):
        # _index is the address set. IS-only γ lives here too.
        seen = []
        for bag in self._index.values():
            for g in bag:
                if g not in seen:
                    seen.append(g)
        return seen
    def query_delta(self, filt, exact=True, grain="month"):
        filt = normalize_filt(filt, grain=grain)
        if filt is None or not filt_has_axis(filt):
            return []
        return [(g, d) for g, d in self._deltas if g.matches(filt, exact=exact)]
    def query_gamma(self, filt: dict, exact: bool = True, grain: str = "month") -> list[Gamma]:
        filt = normalize_filt(filt, grain=grain)
        if filt is None or not filt_has_axis(filt):
            return []
        if "project" in filt and "topic" in filt and exact:
            cand = list(self._index.get(f"{filt['project']}::{filt['topic']}", []))
        elif "project" in filt and exact:
            cand = list(self._by_project.get(filt["project"], []))
        elif "topic" in filt and exact:
            cand = list(self._by_topic.get(filt["topic"], []))
        else:
            cand = self._addresses()
        out = []
        for g in cand:
            if g.matches(filt, exact=exact) and g not in out:
                out.append(g)
        return out
    def latest_at(self, filt, exact=True, grain="month"):
        # latest = append order on _deltas. timestamp is audit only.
        last = {}
        for _, d in self.query_delta(filt, exact=exact, grain=grain):
            last[d.field] = d
        return list(last.values())
    def latest(self, filt, word, exact=True, grain="month"):
        word = canon_word(word)
        found = [d for _, d in self.query_delta(filt, exact=exact, grain=grain) if d.field == word]
        return found[-1] if found else None
    def history(self, filt, word, exact=True, grain="month"):
        word = canon_word(word)
        return [d for _, d in self.query_delta(filt, exact=exact, grain=grain) if d.field == word]
    def lookup(self, word):
        word = canon_word(word)
        out = []
        for g, d in self._deltas:
            if d.field == word and g not in out:
                out.append(g)
        return out
    def is_lines(self, filt, exact=True, grain="month"):
        # isolated IS only. Δ latest is not copied here.
        # footnote: IS_MAX lives in _adopt_is. wide filters keep every matching address.
        filt = normalize_filt(filt, grain=grain)
        if filt is None or not filt_has_axis(filt):
            return []
        lines = []
        for key, bag in self._is.items():
            g = Gamma(**json.loads(key))
            if not g.matches(filt, exact=exact):
                continue
            for line in bag:
                if line not in lines:
                    lines.append(line)
        return lines
    def snapshot(self):
        return {
            "deltas": [{"gamma": asdict(g), "delta": asdict(d)} for g, d in self._deltas],
            "is": dict(self._is),
            "pending": [{"gamma": asdict(g), "delta": asdict(d)} for g, d in self._pending],
            "is_pending": [{"gamma": asdict(g), "line": line} for g, line in self._is_pending],
            "adopted": sorted(self._adopted),
        }
    def mutable_payload(self) -> dict:
        return mutable_view(self.snapshot())
    def hash_b(self) -> str:
        # integrity of mutable state. not Hash-A. not a new layer.
        return hash_mutable(self.snapshot())
    def verify_hash_b(self, expected_hash_b: str) -> bool:
        """Compare current mutable-state hash to an independently retained reference."""
        return isinstance(expected_hash_b, str) and bool(expected_hash_b) and self.hash_b() == expected_hash_b
    def integrity_report(self, expected_hash_b: Optional[str] = None) -> dict:
        """Report Hash-A integrity and Hash-B digest; B verification needs a reference."""
        actual_b = self.hash_b()
        return {
            "hash_a_intact": self.inner.intact(),
            "hash_a": self.inner.hash_a,
            "hash_b": actual_b,
            "hash_b_reference_supplied": isinstance(expected_hash_b, str) and bool(expected_hash_b),
            "hash_b_matches_reference": self.verify_hash_b(expected_hash_b) if expected_hash_b else None,
        }
    def restore(self, snap):
        # snapshot is internal. extra keys and broken rows are dropped, not trusted.
        if not isinstance(snap, dict):
            return self
        deltas = []
        raw_deltas = snap.get("deltas")
        if not isinstance(raw_deltas, list):
            raw_deltas = []
        raw_deltas = raw_deltas[-MAX_RESTORE_ROWS:]
        for row in raw_deltas:
            if not isinstance(row, dict):
                continue
            g, d = _load_gamma(row.get("gamma")), _load_delta(row.get("delta"))
            if g is not None and d is not None and gamma_has_axis(g) and d.field in WORDS:
                deltas.append((g, d))
        pending = []
        raw_pending = snap.get("pending")
        if not isinstance(raw_pending, list):
            raw_pending = []
        raw_pending = raw_pending[-MAX_RESTORE_PENDING:]
        for row in raw_pending:
            if not isinstance(row, dict):
                continue
            g, d = _load_gamma(row.get("gamma")), _load_delta(row.get("delta"))
            if g is not None and d is not None and gamma_has_axis(g) and d.field in WORDS:
                pending.append((g, d))
        is_store = {}
        raw_is = snap.get("is") or {}
        if isinstance(raw_is, dict):
            # Collect only the newest addresses without copying the entire mapping.
            recent_is_items = []
            for item in reversed(raw_is.items()):
                recent_is_items.append(item)
                if len(recent_is_items) >= MAX_RESTORE_ADDRESSES:
                    break
            for key, bag in reversed(recent_is_items):
                try:
                    parsed = json.loads(key) if isinstance(key, str) else None
                except (json.JSONDecodeError, TypeError):
                    parsed = None
                g = _load_gamma(parsed)
                if g is None or not gamma_has_axis(g) or not isinstance(bag, list):
                    continue
                folded = []
                # A valid live address needs at most IS_MAX lines; inspect a bounded tail
                # so malformed snapshots cannot force unbounded per-address work.
                for x in bag[-MAX_RESTORE_IS_LINES_PER_ADDRESS:]:
                    if is_line_word(x) not in WORDS:
                        continue
                    folded, _ = cap_is_bag(folded, x)
                if folded:
                    is_store[g.key()] = folded
        is_pending = []
        raw_is_pending = snap.get("is_pending")
        if not isinstance(raw_is_pending, list):
            raw_is_pending = []
        raw_is_pending = raw_is_pending[-MAX_RESTORE_PENDING:]
        for row in raw_is_pending:
            if not isinstance(row, dict):
                continue
            g = _load_gamma(row.get("gamma"))
            line = row.get("line")
            if g is not None and gamma_has_axis(g) and is_line_word(line) in WORDS:
                is_pending.append((g, line))
        # adopted is not trusted. snapshot may list it; restore does not widen WORDS.
        self._deltas = deltas
        self._pending = pending
        self._is = is_store
        self._is_pending = is_pending
        self._adopted = set()
        self._index = defaultdict(list)
        self._by_project = defaultdict(list)
        self._by_topic = defaultdict(list)
        # pending does not create an address. same rule as write.
        for g, _ in self._deltas:
            self._index_put(g)
        for key in self._is:
            self._index_put(Gamma(**json.loads(key)))
        return self
    def render(self, user, filt, exact=True, grain="month"):
        shown = normalize_filt(filt, grain=grain)
        if shown is None:
            shown = {}
        inn = self.inner
        if not inn.intact():
            bind = "核の整合性が壊れている。生成するな。"
        elif self.eta.high():
            bind = "偏差が大きい。基準へ戻せ。今の住所の外を埋めつな。核は書き換えるな。"
        else:
            bind = "基準に従って短く。更新と核を混ぜるな。核は変えるな。"
        if self._pending or self._is_pending:
            bind = f"{bind} pending Δ={len(self._pending)} IS={len(self._is_pending)}"
        facts = inn.fact_lines()
        fact_block = "\n".join(f"- {x}" for x in facts) if facts else "(none)"
        is_block = "\n".join(f"- {x}" for x in self.is_lines(filt, exact=exact, grain=grain)) or "(none)"
        return "\n".join([
            f"[αβ] {inn.hash_a[:16]} intact={inn.intact()}",
            f"name: {inn.beta.name}",
            f"tone: {inn.beta.tone}",
            f"center: {inn.beta.center}",
            f"values: {', '.join(inn.beta.values)}",
            "",
            "[β facts]",
            fact_block,
            "",
            "[γ address]",
            gamma_line(shown),
            "",
            "[IS]",
            is_block,
            "",
            "[bind]",
            bind,
            "",
            "[user]",
            user,
        ])

def make_test_capsule(name: str = "テスト体", tone: str = "簡潔", center: str = "中心軸", values: tuple[str, ...] = ("不変",), facts: tuple[BetaFact, ...] = ()) -> Capsule:
    return Capsule(Inner(Alpha(), Beta(name=name, tone=tone, center=center, values=values), facts=facts))
