"""
ContextEngine — FAISS-based vector index for RAG semantic search.

This module provides the ContextEngine class that builds a FAISS vector
index from document chunks (briefing requirements, source code) and
enables semantic similarity search for the AI evaluation engine.

Used by the Grading Loop to retrieve the most relevant context
for each rubric criterion evaluation.
"""

from langchain_community.vectorstores import FAISS
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document

from core.logging_config import logger

# Type alias for documents: supports both dict and Document objects
DocumentInput = dict | Document


class ContextEngine:
    """
    FAISS-powered context retrieval engine for RAG.

    Converts document chunks into vector embeddings and provides
    semantic similarity search to find relevant context for each
    evaluation criterion.

    Attributes:
        embeddings: The Embeddings instance (Google or OpenAI) for vectorization.
        vector_store: FAISS index built from the provided documents.
    """

    # Provider-safe embedding constraints.
    # Vertex currently accepts up to 250 instances/request and enforces
    # an input token limit per request. We use conservative defaults.
    EMBEDDING_MAX_INSTANCES_PER_REQUEST = 200
    EMBEDDING_MAX_CHARS_PER_REQUEST = 15000
    EMBEDDING_MAX_TEXT_CHARS = 4000
    EMBEDDING_TEXT_OVERLAP_CHARS = 200

    def __init__(
        self,
        documents: list[DocumentInput],
        embedding_provider: str = None,
        embedding_model: str = None,
        embedding_api_key: str = None,
    ):
        """
        Initialize the context engine with documents and build the FAISS index.

        Args:
            documents: List of document dicts with 'page_content' and 'metadata'
                    keys, or langchain Document objects.
            embedding_provider: Optional "gemini" or "openai". Evaluates to settings default if None.
            embedding_model: Optional specific model name. Evaluates to settings default if None.
            embedding_api_key: Optional API key. Evaluates to environment key if None.

        Raises:
            ValueError: If documents list is empty or provider is unsupported.
        """
        if not documents:
            raise ValueError("Cannot create ContextEngine with an empty document list.")

        # Create the correct embeddings client using the factory method
        self.embeddings = self._create_embeddings(
            provider=embedding_provider,
            model=embedding_model,
            api_key=embedding_api_key
        )

        # Extract texts and metadatas from documents (support both dict and Document)
        texts, metadatas = self._extract_texts_and_metadatas(documents)

        # Normalize oversized texts, then build the FAISS vector store in safe batches.
        texts, metadatas = self._normalize_text_lengths(texts, metadatas)
        logger.debug(f"Building FAISS index with {len(texts)} document chunks...")
        self.vector_store = self._build_faiss_from_texts_batched(texts, metadatas)
        logger.debug("FAISS index created successfully.")

    def get_relevant_context(self, query: str, k: int = 5) -> list[dict]:
        """
        Perform semantic similarity search against the FAISS index.

        Args:
            query: Natural language query (e.g., "error handling requirements").
            k: Number of most similar document chunks to return.

        Returns:
            List of dicts, each with 'page_content' and 'metadata' keys,
            ordered by relevance (most similar first).
        """
        results = self.vector_store.similarity_search(query, k=k)

        context = [
            {
                "page_content": doc.page_content,
                "metadata": doc.metadata,
            }
            for doc in results
        ]

        logger.debug(
            f"Context search for '{query[:60]}...' returned {len(context)} results"
        )
        return context

    def add_documents(self, documents: list[DocumentInput]) -> None:
        """
        Add new documents to the existing FAISS index.

        Useful for combining briefing requirements and code files
        into a single searchable index.

        Args:
            documents: List of document dicts with 'page_content' and 'metadata'
                    keys, or langchain Document objects.

        Raises:
            ValueError: If documents list is empty.
        """
        if not documents:
            raise ValueError("Cannot add an empty document list.")

        texts, metadatas = self._extract_texts_and_metadatas(documents)
        texts, metadatas = self._normalize_text_lengths(texts, metadatas)

        self._add_texts_batched(texts, metadatas)
        logger.debug(f"Added {len(texts)} documents to FAISS index.")

    def _build_faiss_from_texts_batched(
        self,
        texts: list[str],
        metadatas: list[dict],
    ) -> FAISS:
        """Create FAISS index in batches to avoid oversized embedding requests."""
        first_batch_texts, first_batch_metadatas, next_index = self._next_embedding_batch(
            texts,
            metadatas,
            start=0,
        )

        vector_store = FAISS.from_texts(
            first_batch_texts,
            self.embeddings,
            metadatas=first_batch_metadatas,
        )

        if next_index < len(texts):
            self._add_texts_batched_to_store(
                vector_store,
                texts[next_index:],
                metadatas[next_index:],
            )

        return vector_store

    def _add_texts_batched(self, texts: list[str], metadatas: list[dict]) -> None:
        """Append texts to FAISS index in provider-safe embedding batches."""
        self._add_texts_batched_to_store(self.vector_store, texts, metadatas)

    def _add_texts_batched_to_store(
        self,
        vector_store: FAISS,
        texts: list[str],
        metadatas: list[dict],
    ) -> None:
        """Append texts to a specific FAISS store in provider-safe batches."""
        if not texts:
            return

        cursor = 0
        while cursor < len(texts):
            batch_texts, batch_metadatas, next_cursor = self._next_embedding_batch(
                texts,
                metadatas,
                start=cursor,
            )
            vector_store.add_texts(batch_texts, metadatas=batch_metadatas)
            cursor = next_cursor

    def _next_embedding_batch(
        self,
        texts: list[str],
        metadatas: list[dict],
        start: int,
    ) -> tuple[list[str], list[dict], int]:
        """Build the next embedding batch honoring item and char budgets."""
        batch_texts: list[str] = []
        batch_metadatas: list[dict] = []
        batch_chars = 0
        cursor = start

        while cursor < len(texts):
            text = texts[cursor] or ""
            text_len = len(text)

            exceeds_instance_limit = (
                len(batch_texts) >= self.EMBEDDING_MAX_INSTANCES_PER_REQUEST
            )
            exceeds_char_budget = (
                batch_texts
                and batch_chars + text_len > self.EMBEDDING_MAX_CHARS_PER_REQUEST
            )

            if exceeds_instance_limit or exceeds_char_budget:
                break

            batch_texts.append(text)
            batch_metadatas.append(metadatas[cursor])
            batch_chars += text_len
            cursor += 1

        # Defensive fallback: always return at least one item.
        if not batch_texts:
            batch_texts.append(texts[start] or "")
            batch_metadatas.append(metadatas[start])
            cursor = start + 1

        return batch_texts, batch_metadatas, cursor

    def _normalize_text_lengths(
        self,
        texts: list[str],
        metadatas: list[dict],
    ) -> tuple[list[str], list[dict]]:
        """Split oversized texts before embedding to keep requests predictable."""
        normalized_texts: list[str] = []
        normalized_metadatas: list[dict] = []

        for text, metadata in zip(texts, metadatas):
            safe_text = text or ""
            if len(safe_text) <= self.EMBEDDING_MAX_TEXT_CHARS:
                normalized_texts.append(safe_text)
                normalized_metadatas.append(metadata)
                continue

            start = 0
            segment_index = 0
            step = max(
                self.EMBEDDING_MAX_TEXT_CHARS - self.EMBEDDING_TEXT_OVERLAP_CHARS,
                1,
            )
            while start < len(safe_text):
                end = min(start + self.EMBEDDING_MAX_TEXT_CHARS, len(safe_text))
                segment = safe_text[start:end]
                segment_metadata = dict(metadata)
                segment_metadata["segment_index"] = segment_index
                segment_metadata["segment_total_chars"] = len(safe_text)

                normalized_texts.append(segment)
                normalized_metadatas.append(segment_metadata)

                if end == len(safe_text):
                    break

                start += step
                segment_index += 1

        return normalized_texts, normalized_metadatas

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_texts_and_metadatas(
        documents: list,
    ) -> tuple[list[str], list[dict]]:
        """
        Extract texts and metadatas from a mixed list of dicts / Document objects.

        Args:
            documents: List of dicts or Document objects.

        Returns:
            Tuple of (texts, metadatas).
        """
        texts = []
        metadatas = []

        for doc in documents:
            if isinstance(doc, Document):
                texts.append(doc.page_content)
                metadatas.append(doc.metadata)
            elif isinstance(doc, dict):
                texts.append(doc.get("page_content", ""))
                metadatas.append(doc.get("metadata", {}))
            else:
                raise TypeError(
                    f"Unsupported document type: {type(doc)}. "
                    "Expected dict or langchain Document."
                )

        return texts, metadatas

    @staticmethod
    def _create_embeddings(provider: str = None, model: str = None, api_key: str = None):
        """
        Factory method to create the appropriate Embeddings instance.
        """
        from core.settings import AIProvider, settings
        
        

        # Create specific embedding provider
        if provider == AIProvider.GEMINI:
            # Server default Gemini path uses Vertex embeddings when enabled.
            if settings.VERTEX_ENABLED and not api_key:
                try:
                    from langchain_google_vertexai import VertexAIEmbeddings
                except ModuleNotFoundError as exc:
                    raise RuntimeError(
                        "Vertex embeddings dependency missing. Install langchain-google-vertexai and rebuild the backend image."
                    ) from exc

                return VertexAIEmbeddings(
                    model_name=model,
                    project=settings.GCP_PROJECT_ID,
                    location=settings.GCP_LOCATION,
                )

            # BYOK path uses Gemini Developer API key.
            return GoogleGenerativeAIEmbeddings(
                model=model,
                google_api_key=api_key,
            )
            
        elif provider == AIProvider.OPENAI:
            return OpenAIEmbeddings(
                model=model,
                api_key=api_key,
            )
            
        else:
            message=f"Unupported embedding provider: {provider}, model: {model}"
            logger.error(message)
            raise ValueError(message)
