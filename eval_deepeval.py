"""
DeepEval-based quality check for the RAG chatbot.

Runs every golden in eval_dataset.json through the real pipeline
(retrieve_context_node -> generate_answer_node, same as graph.run_chat) and
scores each answer with:
    - AnswerRelevancyMetric    -- does the answer actually address the question?
    - FaithfulnessMetric       -- is every claim grounded in the retrieved CONTEXT?
                                  (this is "THE ONE RULE THAT NEVER BENDS" in
                                  prompt.py's SYSTEM_PROMPT -- this metric checks
                                  the model actually followed it)
    - ContextualRelevancyMetric -- did retrieval fetch chunks relevant to the query?

The dataset covers the behavior modes prompt.py's SYSTEM_PROMPT defines:
product/pricing/coverage questions, competitor comparisons, use cases, small
talk, off-topic requests, prompt injection, gibberish/unsupported/supported-
language handling, ungrounded business questions, sensitive-data requests,
and complaint handling -- see eval_dataset.json's "category" metadata.

Run with:
    .venv/bin/python3 eval_deepeval.py
"""
import contextlib
import io
import os

import config

# deepeval's judge model reads the standard OPENAI_API_KEY env var; this
# project's own config uses OPEN_AI_API_KEY (see config.py), so bridge it.
os.environ.setdefault("OPENAI_API_KEY", config.OPEN_AI_API_KEY or "")

from deepeval.dataset import EvaluationDataset
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.test_case import LLMTestCase

from graph import generate_answer_node, retrieve_context_node

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET_PATH = os.path.join(BASE_DIR, "eval_dataset.json")


def load_dataset(dataset_path: str = DEFAULT_DATASET_PATH) -> EvaluationDataset:
    dataset = EvaluationDataset()
    dataset.add_goldens_from_json_file(
        dataset_path,
        input_key_name="input",
        expected_output_key_name="expected_output",
        additional_metadata_key_name="additional_metadata",
    )
    return dataset


ALL_METRIC_BUILDERS = {
    "answer_relevancy": lambda: AnswerRelevancyMetric(threshold=0.7, include_reason=True),
    "faithfulness": lambda: FaithfulnessMetric(threshold=0.7, include_reason=True),
    "contextual_relevancy": lambda: ContextualRelevancyMetric(threshold=0.5, include_reason=True),
}


def build_metrics():
    # override via e.g. EVAL_METRICS=answer_relevancy,faithfulness to skip a metric
    selected = os.environ.get("EVAL_METRICS", "answer_relevancy,faithfulness,contextual_relevancy").split(",")
    return [ALL_METRIC_BUILDERS[name]() for name in selected if name in ALL_METRIC_BUILDERS]


def run_pipeline(query: str):
    """Run the same two graph nodes run_chat() uses, so this measures the
    real production pipeline rather than a reimplementation of it."""
    state = {"session_id": "deepeval-eval", "question": query, "history": [], "context": "", "answer": ""}
    with contextlib.redirect_stdout(io.StringIO()):  # silence retriever.py's chunk-dump prints
        state = retrieve_context_node(state)
    state = generate_answer_node(state)
    chunks = state["context"].split("\n\n---\n\n") if state["context"] else []
    return chunks, state["answer"]


def run_eval(dataset_path: str = DEFAULT_DATASET_PATH):
    dataset = load_dataset(dataset_path)
    results = []

    for golden in dataset.goldens:
        query = golden.input
        category = (golden.additional_metadata or {}).get("category", "uncategorized")
        language = (golden.additional_metadata or {}).get("language")

        chunks, answer = run_pipeline(query)
        has_chunks = bool(chunks and chunks[0])

        test_case = LLMTestCase(
            input=query,
            actual_output=answer,
            expected_output=golden.expected_output,
            retrieval_context=chunks if has_chunks else ["(no chunks retrieved -- off-topic/small-talk query)"],
        )

        print(f"\n{'=' * 70}\n[{category}] {golden.name}\nQUERY: {query}")
        print(f"CHUNKS RETRIEVED: {len(chunks) if has_chunks else 0}")
        print(f"ANSWER: {answer}\n")

        for metric in build_metrics():
            metric_name = metric.__class__.__name__
            try:
                metric.measure(test_case)
                score, passed, reason, error = metric.score, metric.is_successful(), metric.reason, None
            except Exception as e:
                score, passed, reason, error = None, False, None, str(e)

            if error:
                print(f"  [{metric_name:<26}] ERROR: {error}")
            else:
                print(f"  [{metric_name:<26}] score={score:.2f}  passed={passed}")
                if reason:
                    print(f"      reason: {reason}")

            results.append({
                "name": golden.name,
                "category": category,
                "language": language,
                "metric": metric_name,
                "score": score,
                "passed": passed,
                "error": error,
            })

    print(f"\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    for r in results:
        if r["error"]:
            print(f"  [ERROR] {r['category']:<28} {r['metric']:<26} {r['error'][:60]}  -- {r['name']}")
        else:
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}] {r['category']:<28} {r['metric']:<26} {r['score']:.2f}  -- {r['name']}")

    total = len(results)
    errored = [r for r in results if r["error"]]
    scored = [r for r in results if not r["error"]]
    passed = sum(1 for r in scored if r["passed"])
    print(f"\n{passed}/{len(scored)} metric checks passed, {len(errored)}/{total} errored "
          f"(e.g. API failures), across {len(dataset.goldens)} goldens.")
    if errored:
        print("  NOTE: errored checks are excluded from the averages below -- they are not scored as 0.")

    print(f"\n{'=' * 70}\nAVERAGE SCORES\n{'=' * 70}")
    scores_by_metric = {}
    for r in scored:
        scores_by_metric.setdefault(r["metric"], []).append(r["score"])
    for metric_name, scores in scores_by_metric.items():
        print(f"  {metric_name:<26} avg={sum(scores) / len(scores):.3f}  (n={len(scores)})")

    overall_avg = sum(r["score"] for r in scored) / len(scored) if scored else 0.0
    print(f"\n  OVERALL AVERAGE (all metrics, all goldens combined): {overall_avg:.3f}"
          + ("" if scored else "  (no successfully-scored checks)"))

    languages_present = {r["language"] for r in scored if r["language"]}
    if languages_present:
        print(f"\n{'=' * 70}\nAVERAGE SCORES BY LANGUAGE\n{'=' * 70}")
        scores_by_language = {}
        for r in scored:
            if r["language"]:
                scores_by_language.setdefault(r["language"], []).append(r["score"])
        for lang, scores in sorted(scores_by_language.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
            print(f"  {lang:<12} avg={sum(scores) / len(scores):.3f}  (n={len(scores)})")


if __name__ == "__main__":
    import sys

    run_eval(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATASET_PATH)