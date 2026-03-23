"""Streamlit RAG アプリ — Azure AI Search × Responses API"""

import os
import streamlit as st
from openai import AzureOpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery
from dotenv import load_dotenv

load_dotenv()

# --- 設定 ---
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_MODEL = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o")
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "rag-index")

# --- 認証（ローカル: az login / Azure: マネージドID） ---
credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(
    credential, "https://cognitiveservices.azure.com/.default"
)

# --- クライアント ---
openai_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=token_provider,
    api_version="2025-03-01-preview",
)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=credential,
)


# ========== 検索 ==========
def search(query, top_k=3):
    """Azure AI Search: ハイブリッド検索（キーワード + ベクトル） + セマンティックリランカー"""
    results = search_client.search(
        search_text=query,
        vector_queries=[
            VectorizableTextQuery(
                text=query, k_nearest_neighbors=50, fields="content_vector"
            )
        ],
        query_type="semantic",
        semantic_configuration_name="default",
        top=top_k,
        select=["title", "content"],
    )
    docs = []
    for r in results:
        docs.append(
            {
                "title": r["title"],
                "content": r["content"],
                "score": r.get("@search.reranker_score", r.get("@search.score", 0)),
            }
        )
    return docs


# ========== 回答生成 ==========
def generate_answer(question, context_docs):
    """Responses API: 検索結果をコンテキストにしてストリーミング回答"""
    context_text = "\n\n---\n\n".join(
        f"【{d['title']}】(スコア: {d['score']:.2f})\n{d['content']}"
        for d in context_docs
    )

    system_prompt = f"""あなたは社内ドキュメントに基づいて回答するアシスタントです。
以下の検索結果を参考に、ユーザーの質問に正確に回答してください。
検索結果に情報がない場合は「該当する情報が見つかりませんでした」と回答してください。

## 検索結果
{context_text}"""

    stream = openai_client.responses.create(
        model=AZURE_OPENAI_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        stream=True,
    )
    for event in stream:
        if event.type == "response.output_text.delta":
            yield event.delta


# ========== Streamlit UI ==========
st.title("📚 RAG デモ")
st.caption("Azure AI Search × Responses API による検索拡張生成")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("質問を入力してください"):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 検索
    with st.spinner("🔍 検索中..."):
        docs = search(question)

    with st.expander(f"🔍 検索結果（{len(docs)}件）", expanded=False):
        for doc in docs:
            st.markdown(f"**{doc['title']}** (スコア: {doc['score']:.2f})")
            st.markdown(doc["content"][:300] + "...")
            st.divider()

    # 回答生成（ストリーミング）
    with st.chat_message("assistant"):
        response_text = st.write_stream(generate_answer(question, docs))

    st.session_state.messages.append({"role": "assistant", "content": response_text})
