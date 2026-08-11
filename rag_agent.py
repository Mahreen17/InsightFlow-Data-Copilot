"""
The Enterprise Data Copilot build: the RAG Agent.

WHAT "RAG" ACTUALLY MEANS, IN PLAIN ENGLISH:
RAG = Retrieval-Augmented Generation. The LLM doesn't "know" what's inside
your PDFs — it's never seen them. So instead, we:
  1. Chop the PDFs into small text chunks
  2. Convert each chunk into a list of numbers (a "vector embedding") that
     captures its MEANING, not just its words
  3. Store all those vectors in a searchable index (a "vector store")
  4. When a question comes in, convert the QUESTION into a vector too, and
     find the chunks whose vectors are closest to it (= most similar meaning)
  5. Paste those chunks into the prompt as context, and ask the LLM to
     answer USING ONLY that context

Step 5 is the "generation" part — the LLM writes the final answer. Steps
1-4 are the "retrieval" part — plain search, no LLM involved at all.

WHY LOCAL EMBEDDINGS INSTEAD OF GEMINI'S:
Embedding is a per-chunk operation — with 7 PDFs split into dozens of
chunks, that's dozens of API calls just to build the index, before you've
even asked a single question. On the Gemini free tier, that alone could
burn your rate limit. A local embedding model (running on your own CPU,
downloaded once from Hugging Face) does this instantly and for free, with
no request limit at all. We still use Gemini for the one thing that
actually needs a big language model: writing the final answer.
"""

import os
import glob

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv(".env.local")  

# --- Configuration -----------------------------------------------------
PDF_FOLDER = "dataset/pdfs"       
CHROMA_DIR = "chroma_db"          
MODEL_NAME = "gemini-flash-lite-latest"  
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  


# =============================================================================
# STEP 1: Load and chunk the PDFs.
# =============================================================================
def build_chunks():
    """Reads every PDF in PDF_FOLDER and splits them into overlapping chunks.

    WHY CHUNK AT ALL: an LLM can only read so much text at once, and stuffing
    an entire PDF into every prompt wastes tokens on irrelevant sections.
    Chunking lets us retrieve just the 2-4 most relevant paragraphs instead
    of the whole document.

    WHY OVERLAP (chunk_overlap below): if a sentence explaining something
    important gets cut exactly at a chunk boundary, overlap means it still
    appears fully in at least one chunk, rather than being split in half
    and losing its meaning in both pieces.
    """
    pdf_paths = glob.glob(os.path.join(PDF_FOLDER, "*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDFs found in '{PDF_FOLDER}'. Check the path matches where "
            f"you extracted the dataset zip."
        )

    
    all_pages = []
    for path in pdf_paths:
        reader = PdfReader(path)
        for page_number, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():  # skip blank pages
                all_pages.append(
                    Document(page_content=text, metadata={"source": path, "page": page_number})
                )

    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
    )
    chunks = splitter.split_documents(all_pages)
    print(f"Loaded {len(pdf_paths)} PDFs -> {len(all_pages)} pages -> {len(chunks)} chunks")
    return chunks


# =============================================================================
# STEP 2: Embed the chunks and store them in a searchable vector index.
# =============================================================================
def build_vectorstore(chunks):
    """Turns chunks into vectors and stores them in Chroma, a lightweight
    local vector database (just files on disk, like SQLite for vectors).

    This only needs to run ONCE — after the first run, CHROMA_DIR will
    contain the saved index, so you don't need to re-embed every time you
    ask a question. We check for that below.
    """
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)

    if os.path.exists(CHROMA_DIR) and os.listdir(CHROMA_DIR):
        # Index already built on a previous run — just reconnect to it.
        print("Found existing vector index, reusing it (skipping re-embedding).")
        return Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)

    print("Building vector index for the first time (this downloads the "
          "embedding model on first run, then embeds all chunks — may take "
          "a minute or two, no API calls involved)...")
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=CHROMA_DIR,
    )
    return vectorstore


# =============================================================================
# STEP 3: The RAG chain itself — retrieve, then generate.
# =============================================================================
model = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)

RAG_PROMPT_TEMPLATE = """You are answering questions about TrailPeak Outdoor Co. \
using only the document excerpts provided below. If the excerpts don't contain \
enough information to answer confidently, say so rather than guessing.

Always mention which document(s) your answer draws from, using the source \
filenames shown with each excerpt.

--- DOCUMENT EXCERPTS ---
{context}
--- END EXCERPTS ---

Question: {question}

Answer (concise, and cite the source filename):"""


def _extract_text(content) -> str:
    """See sql_agent.py for the full explanation -- Gemini sometimes returns
    content as a list of blocks instead of plain text; this normalizes it."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return str(content)


def ask_rag(question: str, k: int = 3, verbose: bool = True) -> str:
    """Retrieves the top-k most relevant chunks for the question, then asks
    Gemini to answer using only those chunks. k=3 means 'give me the 3 best
    matches' -- a good starting point; raise it if answers seem to be
    missing context, lower it if answers seem to wander off-topic.

    verbose=True (the default) prints the retrieved sources and answer --
    useful when running this file standalone. The Orchestrator calls this
    with verbose=False since it does its own reporting."""

    # --- Retrieval: pure vector similarity search, no LLM involved yet ---
    results = _vectorstore.similarity_search(question, k=k)

    # Build the context block, labeling each excerpt with its source PDF
    # so the model (and you) can see exactly where each fact came from.
    context_parts = []
    for doc in results:
        source = os.path.basename(doc.metadata.get("source", "unknown"))
        context_parts.append(f"[Source: {source}]\n{doc.page_content}")
    context = "\n\n".join(context_parts)

    # --- Generation: now the LLM writes the final answer ---
    prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)
    response = model.invoke(prompt)
    answer_text = _extract_text(response.content)

    if verbose:
        print(f"\n{'='*70}\nQ: {question}\n{'='*70}")
        print(f"[retrieved {len(results)} chunks from: "
              f"{', '.join(os.path.basename(d.metadata.get('source','?')) for d in results)}]")
        print(f"\nANSWER: {answer_text}\n")
    return answer_text


# =============================================================================
# Build the vector index as soon as this file is imported.
# =============================================================================

_chunks = build_chunks()
_vectorstore = build_vectorstore(_chunks)


# =============================================================================
# STEP 4: Run today's 5 pure-RAG eval questions.
# =============================================================================
if __name__ == "__main__":
    rag_questions = [
        "Can I return a tent after I've used it?",
        "What is the warranty on the TrailBlazer 65L Backpack?",
        "What are the benefits of being a Gold tier loyalty member?",
        "How should I store a tent to avoid voiding the warranty?",
        "Which regions offer phone support?",
    ]

    for q in rag_questions:
        ask_rag(q)