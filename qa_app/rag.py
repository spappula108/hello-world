"""Lightweight RAG assistant for SOP Q&A.

Pure-Python TF-IDF (no sklearn/numpy) over local SOP corpus. Optionally calls a local LLM via Ollama.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

import math
import re
import requests


def _read_texts_from_dir(directory: str) -> List[Tuple[str, str]]:
    texts: List[Tuple[str, str]] = []
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
        # Write minimal SOPs
        samples = {
            "SOP-001-RAW.txt": "SOP-001-RAW\nHandling raw materials. Sampling procedures. Acceptance criteria for assays 98-102%. Moisture below 0.5%.",
            "SOP-002-FP.txt": "SOP-002-FP\nFinished product testing. Dissolution Q not less than 80%. Uniformity AV not more than 15.",
            "SOP-003-RAW.txt": "SOP-003-RAW\nIbuprofen raw material controls. Moisture below 0.3%. Assay between 97-103%.",
        }
        for name, content in samples.items():
            with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
                f.write(content)

    for filename in os.listdir(directory):
        if not filename.lower().endswith(".txt"):
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                texts.append((filename, f.read()))
        except Exception:
            continue
    return texts


@dataclass
class Retrieval:
    doc_id: str
    text: str
    score: float


class RAGAssistant:
    def __init__(self, corpus_dir: str, ollama_base_url: str = "http://localhost:11434", model_env_var: str = "OLLAMA_MODEL") -> None:
        self.corpus_dir = corpus_dir
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model_env_var = model_env_var
        self.doc_ids: List[str] = []
        self.doc_texts: List[str] = []
        self.idf: Dict[str, float] = {}
        self.doc_tf: List[Dict[str, float]] = []

    def build_index(self) -> None:
        docs = _read_texts_from_dir(self.corpus_dir)
        self.doc_ids = [d for d, _ in docs]
        self.doc_texts = [t for _, t in docs]
        # Compute TF
        self.doc_tf = []
        df: Dict[str, int] = {}
        for text in self.doc_texts:
            tokens = self._tokenize(text)
            counts: Dict[str, int] = {}
            for tok in tokens:
                counts[tok] = counts.get(tok, 0) + 1
            total = sum(counts.values()) or 1
            tf: Dict[str, float] = {t: c / total for t, c in counts.items()}
            self.doc_tf.append(tf)
            for t in tf.keys():
                df[t] = df.get(t, 0) + 1
        # Compute IDF
        n_docs = max(len(self.doc_texts), 1)
        self.idf = {t: math.log((n_docs + 1) / (d + 1)) + 1.0 for t, d in df.items()}

    def retrieve(self, query: str, k: int = 3) -> List[Retrieval]:
        if not self.doc_texts:
            return []
        q_tf = self._tf(self._tokenize(query))
        q_vec = {t: q_tf.get(t, 0.0) * self.idf.get(t, 0.0) for t in q_tf}
        scores: List[Tuple[int, float]] = []
        for i, d_tf in enumerate(self.doc_tf):
            d_vec = {t: d_tf.get(t, 0.0) * self.idf.get(t, 0.0) for t in d_tf}
            sim = self._cosine(q_vec, d_vec)
            scores.append((i, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        out: List[Retrieval] = []
        for idx, sc in scores[:k]:
            out.append(Retrieval(doc_id=self.doc_ids[idx], text=self.doc_texts[idx], score=sc))
        return out

    def ask(self, question: str, k: int = 3, use_ollama: bool = True) -> str:
        retrieved = self.retrieve(question, k=k)
        context = "\n\n".join([f"[{r.doc_id}]\n{r.text}" for r in retrieved]) or "No SOP context available."
        prompt = (
            "You are a helpful SOP assistant. Use the provided SOP context to answer concisely.\n"
            "If unsure, say you don't know.\n\n"
            f"SOP Context:\n{context}\n\nQuestion: {question}\nAnswer:"
        )

        if use_ollama and os.environ.get(self.model_env_var):
            model = os.environ.get(self.model_env_var, "mistral")
            try:
                resp = requests.post(
                    f"{self.ollama_base_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                    timeout=15,
                )
                if resp.ok:
                    data = resp.json()
                    return data.get("response", "")
            except Exception:
                pass
        # Fallback: return the most relevant context snippet directly
        return context.splitlines()[0] if context else "No answer."

    # --- internal helpers ---
    def _tokenize(self, text: str) -> List[str]:
        return [t for t in re.findall(r"[a-zA-Z0-9]+", text.lower()) if len(t) > 1]

    def _tf(self, tokens: List[str]) -> Dict[str, float]:
        counts: Dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        total = sum(counts.values()) or 1
        return {t: c / total for t, c in counts.items()}

    def _cosine(self, v1: Dict[str, float], v2: Dict[str, float]) -> float:
        # dot
        dot = 0.0
        for t, w in v1.items():
            dot += w * v2.get(t, 0.0)
        # norms
        n1 = math.sqrt(sum(w * w for w in v1.values()))
        n2 = math.sqrt(sum(w * w for w in v2.values()))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return dot / (n1 * n2)

