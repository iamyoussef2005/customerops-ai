"""Opt-in paid retrieval evaluation against an existing index; never runs at import."""

import argparse
import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from customerops_ai.core.config import Settings
from customerops_ai.rag.embeddings import OpenAIEmbeddings
from customerops_ai.rag.store import VectorStore
from customerops_ai.schemas.knowledge import KnowledgeQuery
from customerops_ai.services.knowledge import KnowledgeService


class EvaluationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str = Field(min_length=1, max_length=500)
    expected_sources: list[str]


async def evaluate(dataset: Path, output: Path) -> None:
    settings = Settings()
    if not settings.rag_enabled or settings.openai_api_key is None:
        raise SystemExit(
            "Set CUSTOMEROPS_RAG_ENABLED=true and OPENAI_API_KEY; requests incur cost."
        )
    dataset_text = await asyncio.to_thread(dataset.read_text, encoding="utf-8")
    questions = [
        EvaluationQuestion.model_validate_json(line)
        for line in dataset_text.splitlines()
        if line.strip()
    ]
    if not questions or len({row.id for row in questions}) != len(questions):
        raise SystemExit("Evaluation requires questions with unique IDs.")
    store = await asyncio.to_thread(VectorStore, settings.rag_storage_path)
    try:
        documents = await asyncio.to_thread(store.list_documents)
        available = {record.attributes.source_key for record in documents}
        if any(set(row.expected_sources) - available for row in questions):
            raise SystemExit("Ingest all expected source documents before evaluation.")
        async with AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.rag_embedding_timeout,
            max_retries=0,
        ) as client:
            service = KnowledgeService(
                store,
                OpenAIEmbeddings(
                    client,
                    settings.rag_embedding_model,
                    settings.rag_embedding_dimensions,
                    settings.rag_embedding_batch_size,
                ),
                settings,
            )
            rows = []
            for question in questions:
                result = await service.search(KnowledgeQuery(query=question.question))
                sources = list(dict.fromkeys(hit.source.source_key for hit in result.hits))
                ranks = [
                    index + 1
                    for index, source in enumerate(sources)
                    if source in question.expected_sources
                ]
                rows.append(
                    {
                        **question.model_dump(),
                        "retrieved_sources": sources,
                        "reciprocal_rank": 1 / min(ranks) if ranks else 0,
                        "retrieval_hit": bool(ranks),
                        "no_evidence": not result.hits,
                    }
                )
        known = [row for row in rows if row["expected_sources"]]
        unknown = [row for row in rows if not row["expected_sources"]]
        report = {
            "method": "retrieval-only; no answer faithfulness or semantic entailment score",
            "model": settings.rag_embedding_model,
            "dimensions": settings.rag_embedding_dimensions,
            "top_k": settings.rag_top_k,
            "max_cosine_distance": settings.rag_max_distance,
            "chunk_size": settings.rag_chunk_size,
            "overlap": settings.rag_chunk_overlap,
            "document_fingerprints": {
                record.attributes.source_key: record.fingerprint for record in documents
            },
            "known_questions": len(known),
            "unknown_questions": len(unknown),
            "hit_at_k": sum(bool(row["retrieval_hit"]) for row in known) / len(known)
            if known
            else None,
            "mean_reciprocal_document_rank": sum(float(row["reciprocal_rank"]) for row in known)
            / len(known)
            if known
            else None,
            "unknown_no_evidence_rate": sum(bool(row["no_evidence"]) for row in unknown)
            / len(unknown)
            if unknown
            else None,
            "results": rows,
        }
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(output.write_text, json.dumps(report, indent=2), encoding="utf-8")
        print(f"Measured {len(rows)} retrieval questions. Report: {output}")
    finally:
        await asyncio.to_thread(store.close)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/rag-evaluation.jsonl"))
    parser.add_argument("--output", type=Path, default=Path(".local/rag-evaluation.json"))
    parser.add_argument("--allow-paid-requests", action="store_true", required=True)
    arguments = parser.parse_args()
    asyncio.run(evaluate(arguments.dataset, arguments.output))


if __name__ == "__main__":
    main()
