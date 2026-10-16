# Proto-Mold Capsule — LLM Ingestion Entry Point

> **INTENDED READER: LLM / CODE AGENT.** This README is deliberately written to be loaded as context by an LLM that will inspect, modify, test, or derive the Capsule implementation. It is **LLM-first, not human-first**: prioritize precise contracts, boundaries, edit paths, and verification requirements over narrative explanation.
>
> **Project status: experimental prototype.** The design describes intended boundaries; the Python implementation and tests determine actual behavior. Do not interpret this repository as a security certification or proof that an LLM will behave reliably.

## 0. Instructions to an LLM loading this repository

Treat this README as the repository-level modification contract. Before editing, perform these steps in order:

1. Inspect the repository tree and identify the exact implementation/version in use.
2. Read the complete source file `axiom_proto_mold_capsule_min4_3.py`, including its embedded **Proto-Mold Capsule — LLM modification contract** near the top.
3. If `PROTO_MOLD_CAPSULE_SPEC.md` is present, read it fully before changing behavior. If it is absent, do not assume it is available; use the source contract and explicitly report that the companion specification was unavailable.
4. Locate tests and project configuration. Do not infer that tests exist or have passed merely because the source contains test helpers.
5. Map the request to the owning functions, invariants, persistence behavior, public API, and affected tests before editing.
6. Make the smallest change that fulfills the request. Avoid unrelated refactors, implicit behavior changes, or new architecture layers.
7. Run the relevant checks. Report exactly what was executed and what remains unverified.

Do not treat this README, a source comment, or a model-generated explanation as runtime enforcement. Verify actual code paths.

## 1. Project purpose

Proto-Mold Capsule is a **prototype mold for deriving purpose-specific Capsule variants**. It is a consistency-oriented state container, not a general-purpose memory store, truth verifier, authentication system, or autonomous reasoning engine.

The mold defines boundaries between:

- a relatively fixed core (`αβ`),
- contextual address (`γ`),
- change history (`Δ`),
- bounded current-state lines (`IS`),
- write decisions and human approval queues,
- integrity digests (`Hash-A`, `Hash-B`),
- the vocabulary permitted for writes.

Variants may specialize behavior, but changes must state which contract changes and why. A variant's intended purpose does not prove its behavior; tests must support claims.

## 2. Source-of-truth precedence

When sources appear inconsistent, do not silently reconcile them. Identify the conflict and use this priority for implementation facts:

1. **Actual implementation and executed tests** — establish current runtime behavior.
2. **Embedded source contract / companion specification** — express intended behavior and invariants; compare them with implementation.
3. **This README** — provides repository navigation and LLM work instructions.
4. **Prior conversation, assumptions, or generated summaries** — context only; never stronger than checked files.

If the implementation contradicts the stated contract, report the discrepancy before changing it unless the user's request clearly resolves it. Do not silently “fix” surprising behavior that may be compatibility-sensitive.

## 3. Core model and invariant boundaries

| Component | Owns | Must not silently become |
|---|---|---|
| `α` / `Alpha` | Core behavioral rules | A mutable event history |
| `β` / `Beta` / `BetaFact` | Core identity/configuration/facts | A sink for runtime `Δ` updates |
| `Hash-A` / `Inner` | Digest of the defined core payload | A digest of mutable `Δ`/`IS` state or an authentication signature |
| `γ` / `Gamma` | Address axes: `time_label`, `project`, `topic` | An inferred context, hidden axis, or global query when empty |
| `Δ` / `Delta` | Append-ordered change history | Automatically adopted current state |
| `IS` | Bounded current-state lines per address | A copy of latest `Δ` values |
| Gate / pending queues | Reject, queue for human approval, or allow commit | A claim that content is true |
| `Hash-B` | Digest of the specified mutable payload | A complete authentication or anti-tamper guarantee |
| Vocabulary | Built-in closed words plus explicitly adopted runtime words | A permission set restored from untrusted snapshot data |
| Indexes | Search buckets derived from committed addresses | An independent source of truth |

### Non-negotiable defaults

- Do not add a new conceptual layer unless explicitly required.
- Keep `αβ`, `γ`, `Δ`, `IS`, gate, Hash-A, and Hash-B responsibilities distinct.
- `γ` has only `time_label`, `project`, and `topic` axes.
- A write address requires at least one non-empty `γ` axis.
- Missing `γ` axes are not inferred or backfilled.
- `Δ` writes never update `IS` implicitly; `IS` writes never append `Δ` implicitly.
- Query defaults and ordering are compatibility-sensitive. In particular, `latest` is based on append order, not `Delta.timestamp`.
- Pending items are not committed state and must not create indexed addresses before commit.
- Input acceptance is not proof of factual correctness.

## 4. Current implementation contract (min4.3)

The following describes intended/current contract areas. Confirm exact behavior in source before relying on it after a version change.

### 4.1 Gamma and time grain

- Allowed grain values: `month`, `day`, `week`.
- `month` normalizes a valid date label to `YYYY-MM`.
- `day` normalizes to a valid `YYYY-MM-DD`.
- `week` derives ISO week from a real calendar date; do not infer a week from month-only input.
- Unknown grain must not silently fall back to `month`.
- `exact=True` compares only supplied axes exactly; unspecified axes remain wildcards.
- `exact=False` performs case-insensitive substring matching on supplied axes.
- An empty filter `{}` is not a query for the entire index.
- Invalid or non-γ filter keys must not be silently ignored.

### 4.2 `Δ` and `IS`

- Built-in vocabulary in min4.3: `課題`, `改善点`, `結論`, `立場`, `状態` (with aliases declared in `WORD_ALIAS`).
- `IS_MAX = 3` lines per address.
- The current pinned IS word is `状態`. Eviction removes the oldest non-pinned word first; if all candidates are pinned, the oldest line is removed.
- IS upserts by canonical word: a new line for the same word replaces that word's previous line at the same address.
- Wide queries may combine lines from multiple addresses; do not impose a new global 3-line cap in rendering/query code.
- `keep_history=False` changes same-address/same-field history behavior and is compatibility-sensitive.

### 4.3 Gate and vocabulary

- `identity` must be a finite non-boolean number in `[0, 1]`.
- `identity < 0.20` is rejected by the current gate.
- `human=True` queues an otherwise eligible write for human review; it does not commit it immediately.
- `Eta` exists, but in the current `gate()` implementation its value does not decide write acceptance. `render()` can still use `eta.high()` to alter its binding text. Do not claim Eta controls writes without changing and testing the implementation.
- `adopt_word()` is the explicit runtime path for widening the accepted vocabulary.
- `restore()` intentionally discards the snapshot's `adopted` set and filters persisted rows to built-in `WORDS`. After restore, required custom words must be re-authorized from a separate trusted caller/configuration. Custom-word history is not restored by the current restore policy.

### 4.4 Packet and ingest

Packet top-level keys are closed to `gamma`, `delta`, and `is`. `gamma` is required. Nested objects use closed key sets; unknown keys are rejected rather than guessed.

Current source defines input bounds, including packet character count, row counts, field/value lengths, γ axis lengths, source ID length, reason length, and restore limits. Before changing a bound, locate the corresponding constant and test both direct method calls and packet/restore routes.

Current ingest signature:

```python
ingest(raw, human=False, identity=1.0, grain="month", atomic=False)
```

- `atomic=False` preserves best-effort behavior: writes within a packet may have mixed outcomes.
- `atomic=True` preflights detectable packet/semantic/gate errors and rejects before writes when those preflight errors exist.
- **Do not describe `atomic=True` as a universal transaction or rollback mechanism.** It does not automatically prove that arbitrary runtime exceptions after preflight roll back state.
- Some invalid input/grain/address paths return `None`; do not assume every call returns a result dictionary.
- For structured result dictionaries, preserve the distinction between `success`, `partial`, `queued`, `rejected`, and `noop`.
- A duplicate pending item that was not newly queued should remain distinguishable from a new queue insertion.

### 4.5 Hash scope

- Hash-A covers the payload built by `Inner.payload()` (α rules, β fields, β facts in the current implementation). Mutable `Δ`/`IS` state is outside Hash-A.
- Hash-B covers the payload declared by `mutable_view()`: `deltas`, `is`, `pending`, `is_pending`.
- The current Hash-B excludes `adopted`.
- SHA-256 digests detect mismatch only when compared against an independently retained trusted reference. A digest alone is not a signature or complete protection against an attacker who can replace both state and reference digest.
- Any changes to canonical serialization, payload membership, key/value representation, ordering, or schema require explicit compatibility analysis and tests.

### 4.6 Snapshot and restore

The current snapshot contract contains top-level keys `deltas`, `is`, `pending`, `is_pending`, and `adopted`.

Treat all restore input as untrusted. Preserve defensive type checks, closed schemas, size/row/address bounds, built-in vocabulary filtering, and index rebuilding. If changing the snapshot schema, introduce or document a migration/versioning plan before changing key semantics. Test valid snapshots, malformed rows/containers, limits, ordering, pending items, IS-only addresses, and custom vocabulary behavior.

## 5. Code map: change the owning path

| Change area | Primary code locations to inspect | Required follow-through |
|---|---|---|
| Core payload / Hash-A | `Inner.payload`, `compute_hash`, `seal`, `intact` | Core hash tests, old-hash compatibility |
| Hash-B | `mutable_view`, `hash_mutable`, `Capsule.hash_b`, `verify_hash_b`, `integrity_report` | Payload scope/reference digest tests |
| Packet contract | `_closed`, `_strip_fence`, `parse_packet`, `packet_validation_errors`, `ingest` | Closed-key, type, size, atomic-preflight tests |
| γ/time grain | `coarse_time`, `normalize_filt`, `Gamma.matches`, `_prepare_address`, `gamma_has_axis`, `filt_has_axis` | Month/day/week, malformed date, exact/non-exact matching |
| Δ lifecycle | `write_delta`, `_commit`, `pending`, `approve_pending`, `reject_pending` | Append ordering, history mode, queue/approval/rejection |
| IS lifecycle | `write_is`, `_adopt_is`, `cap_is_bag`, `approve_is`, `reject_is` | Upsert, pinning, eviction, IS/Δ isolation |
| Vocabulary | `canon_word`, `allowed_words`, `adopt_word`, `restore` | Alias, unknown word, post-restore custom word tests |
| Index/query | `_index_put`, `_addresses`, `query_delta`, `query_gamma`, `latest_at`, `latest`, `history`, `lookup`, `is_lines` | Rebuilt indexes, IS-only address, ordering, exact/non-exact |
| Persistence | `snapshot`, `restore` | Snapshot compatibility, malformed inputs, bounds, migration |
| User-facing text | `render` | No inferred context, no state mutation, invalid filter behavior |

Do not change a call-site alone when the contract is owned by a deeper helper. Search all references to changed functions/constants and update affected tests/docs.

## 6. LLM modification protocol

For every requested code change, use this workflow:

### Phase A — Scope

1. Restate the requested behavior in testable terms.
2. Identify current behavior from source, not memory.
3. List invariants affected and explicitly list invariants that must remain unchanged.
4. Determine whether public API, packet schema, snapshot format, hash payload, vocabulary policy, or query ordering changes.
5. If an ambiguity blocks correctness, ask one concise question; otherwise select the smallest reasonable implementation and state the assumption.

### Phase B — Implement

1. Modify the owning function and any necessary caller/helper.
2. Avoid unrelated refactoring and new layers.
3. If behavior changes, update the embedded source contract and `PROTO_MOLD_CAPSULE_SPEC.md` if that file is present in the repository.
4. If compatibility changes, document old/new behavior and migration requirements.
5. Never weaken restore validation merely to make a malformed fixture pass.

### Phase C — Verify

Add or run tests for all applicable categories:

- positive/common path,
- negative/malformed input,
- boundary values and all configured limits,
- state transition sequences (write → queue → approve/reject → query),
- `atomic=False` and `atomic=True`,
- restore and rebuilt indexes,
- Hash-A/Hash-B expected and mismatch cases,
- built-in and adopted vocabulary before/after restore,
- exact and non-exact queries,
- compatibility/regression behavior for existing public methods.

Do not call an unexecuted test “passed.” If a full test suite is absent, say so and run directly relevant executable checks where feasible. A syntax check is not a functional test; a unit test is not a whole-project compatibility proof.

### Phase D — Report

Every code-modification response must contain:

```text
Purpose:
Files changed:
Behavior changed:
Invariants preserved:
API / Snapshot / Hash compatibility impact:
Tests added or updated:
Commands actually executed and results:
Known gaps / unverified risks:
```

Give actual counts only for tests that were executed in the current work session. Do not claim “fully safe,” “bug-free,” or “all tests pass” without defining the scope and evidence.

## 7. Change-risk classification

Use this classification before implementation:

- **LOW:** comments/docs, diagnostics, tests that do not alter runtime behavior.
- **MEDIUM:** input validation, status/result shape, query filtering, local helper behavior, default limits.
- **HIGH:** public method signatures/defaults, packet key/schema changes, Snapshot migration, canonical hashes, `γ` matching semantics, `Δ` ordering, IS eviction/pinning, gate threshold, vocabulary restore/trust policy, changing `atomic` semantics.

HIGH changes require explicit rationale, compatibility notes, targeted tests, and a migration plan where persisted data or hashes are affected. A request from an LLM to “clean up,” “simplify,” or “optimize” is not permission to change high-risk contracts silently.

## 8. Minimal interaction example

```python
from axiom_proto_mold_capsule_min4_3 import Gamma, make_test_capsule

capsule = make_test_capsule()
packet = {
    "gamma": {
        "time_label": "2026-10",
        "project": "AXIOM",
        "topic": "Prototype-Capsule-mold",
    },
    "delta": [
        {
            "field": "課題",
            "old_value": "未整理",
            "new_value": "回帰テストを追加",
            "source_id": "example-001",
            "reason": "動作確認",
        }
    ],
    "is": [
        {"field": "状態", "value": "試作中"}
    ],
}

result = capsule.ingest(packet, atomic=True)
print(result)
```

This example illustrates the packet shape only. It is not evidence that the example has been executed in a given environment; execute it before reporting its result. Adapt the import path to the actual filename/module layout in the checked-out repository.

## 9. Repository maintenance rules

- Keep this README aligned with the checked-in source version; do not silently describe a newer local file than the repository contains.
- Keep detailed contracts and implementation comments synchronized when semantics change.
- Prefer versioned, reviewable changes over overwriting historical snapshots without notes.
- Do not add external dependencies unless required; document why and test installation/runtime assumptions.
- Do not infer CI, package, license, or test status from repository appearance. Inspect the repository.
- The presence of this README is an instruction for LLM-assisted maintenance, **not** a guarantee that every LLM will follow it.

## 10. Success criterion for an LLM-derived variant

A derived Capsule is acceptable only when:

1. its intended behavior is stated precisely;
2. unchanged invariants are listed and tested;
3. behavior changes are implemented in their owning paths;
4. tests cover common, negative, boundary, state-transition, restore, and compatibility paths relevant to the change;
5. hash/snapshot/API impacts are documented;
6. test claims match actual execution;
7. known unverified behavior is disclosed.

**Do not optimize for apparent sophistication. Optimize for explicit contracts, bounded behavior, observable failures, minimal changes, and reproducible verification.**
