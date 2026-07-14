import requests

def get_doc_text(doc_id):
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    resp = requests.get(url)
    return resp.text if resp.status_code == 200 else ""


from googleapiclient.discovery import build
from google.oauth2 import service_account

# Scope untuk membaca Google Docs
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']
SERVICE_ACCOUNT_FILE = 'credentials_.json'


def read_paragraph_element(element):
    text_run = element.get("textRun")
    if not text_run:
        return ""
    return text_run.get("content")


def get_doc_content(doc_id):
    # Load credentials
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    # Build Docs API service
    service = build('docs', 'v1', credentials=creds)

    # Ambil isi dokumen
    doc = service.documents().get(documentId=doc_id).execute()
    content = []
    text = ""

    for element in doc.get('body').get('content', []):
        if "paragraph" in element:
            for elem in element.get("paragraph").get("elements"):
                text += read_paragraph_element(elem)
        elif "table" in element:
            # kalau ada tabel
            for row in element.get("table").get("tableRows"):
                for cell in row.get("tableCells"):
                    text += get_doc_content(cell.get("content"))
        elif "tableOfContents" in element:
            text += get_doc_content(element.get("tableOfContents").get("content"))
    return text

def get_doc_content2(doc_id):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('docs', 'v1', credentials=creds)
    doc = service.documents().get(documentId=doc_id).execute()
    
    content = []
    for element in doc.get('body').get('content'):
        if 'paragraph' in element:
            texts = element['paragraph'].get('elements')
            for t in texts:
                if 'textRun' in t:
                    content.append(t['textRun']['content'])
    return "".join(content)

import re

def split_sections(text):
    parts = re.split(r"\n(?=\d+\.\s|\w.*:)", text)  # split by numbering or title
    sections = []
    for part in parts:
        lines = [l.strip() for l in part.strip().splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0]
        content = "\n".join(lines[1:]) if len(lines) > 1 else ""
        sections.append({"title": title, "content": content})
    return sections


def parse_sections(doc_id):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

    # Build Docs API service
    service = build('docs', 'v1', credentials=creds)

    # Ambil isi dokumen
    doc = service.documents().get(documentId=doc_id).execute()
    elements = doc.get('body').get('content', [])

    sections = []
    current_section = {"title": None, "content": []}
    # print(elements)

    for value in elements:
        if "paragraph" in value:
            paragraph = value.get("paragraph")
            style = paragraph.get("paragraphStyle", {})
            elements_text = " ".join(
                [elem.get("textRun", {}).get("content", "") for elem in paragraph.get("elements", [])]
            ).strip()

            if not elements_text:
                continue

            # Jika heading baru
            if style.get("namedStyleType", "").startswith("HEADING"):
                # simpan section lama
                if current_section["title"]:
                    sections.append({
                        "title": current_section["title"],
                        "content": "\n".join(current_section["content"])
                    })
                # mulai section baru
                current_section = {"title": elements_text, "content": []}
            else:
                # anggap ini isi dari section sekarang
                current_section["content"].append(elements_text)

    # simpan section terakhir
    if current_section["title"]:
        sections.append({
            "title": current_section["title"],
            "content": "\n".join(current_section["content"])
        })

    return sections


import faiss
import numpy as np
from sentence_transformers import SentenceTransformer, util

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

def build_faiss_index(sections):
    texts = [sec["title"] + " " + sec["content"] for sec in sections]
    embeddings = model.encode(texts, normalize_embeddings=True)

    # Buat FAISS index
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # pakai cosine similarity (inner product)
    index.add(np.array(embeddings, dtype=np.float32))

    # Simpan metadata (id -> section)
    metadata = {i: sections[i] for i in range(len(sections))}
    return index, metadata


def search(query, top_k=3, final_k=1, index=[], metadata=[]):
    # Encode query
    query_emb = model.encode([query], normalize_embeddings=True)
    
    # Cari kandidat top_k dari FAISS
    D, I = index.search(np.array(query_emb, dtype=np.float32), top_k)
    
    # Ambil hasil awal
    candidates = []
    for idx, score in zip(I[0], D[0]):
        sec = metadata[idx]
        candidates.append({
            "title": sec["title"],
            "content": sec["content"],
            "score": float(score)
        })
    
    # Reranking pakai cosine similarity lebih presisi
    candidate_texts = [c["title"] + " " + c["content"] for c in candidates]
    cand_embs = model.encode(candidate_texts, normalize_embeddings=True)
    sims = util.cos_sim(query_emb, cand_embs)[0].cpu().numpy()
    
    for i, sim in enumerate(sims):
        candidates[i]["rerank_score"] = float(sim)
    
    # Urutkan ulang berdasarkan rerank_score
    candidates = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
    print(candidates)
    
    return candidates[:final_k]





from fastapi import FastAPI
from pydantic import BaseModel
from google import genai

app = FastAPI()

class QuestionRequest(BaseModel):
    question: str

@app.post("/ask")
def ask(req: QuestionRequest):
    print(f"Pertanyaan diterima: {req.question}")
    client = genai.Client(api_key="YOUR_AI_API_KEY_HERE")
    doc_id = "YOUR_DOCS_ID_HERE"
    text = get_doc_content2(doc_id)

    prompt = f"""
Jawablah pertanyaan berdasarkan dokumen berikut:

{text}

Pertanyaan: {req.question}

Jawaban singkat, jelas, dan hanya berdasarkan isi dokumen di atas saja.
"""

    resp = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt
    )

    return {"question": req.question, "answers": resp.text}
