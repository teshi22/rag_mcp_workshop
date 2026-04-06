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
AZURE_OPENAI_MODEL = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4.1")
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
def generate_answer(question, context_docs, history):
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

    input_messages = [{"role": "system", "content": system_prompt}]
    input_messages.extend(history)
    input_messages.append({"role": "user", "content": question})

    stream = openai_client.responses.create(
        model=AZURE_OPENAI_MODEL,
        input=input_messages,
        stream=True,
    )
    for event in stream:
        if event.type == "response.output_text.delta":
            yield event.delta


# ========== Streamlit UI ==========
st.title("📚 RAG デモ")
st.caption("Azure AI Search × Responses API による検索拡張生成")

if st.sidebar.button("🗑️ 会話履歴をリセット"):
    st.session_state.messages = []
    st.rerun()

SAMPLE_QUESTIONS = [
    "Azure リソースの命名規則を教えてください",
    "セキュリティポリシーの概要を教えて",
    "インシデント発生時の対応フローは？",
    "コスト管理のルールについて教えて",
]

# チャット履歴
if "messages" not in st.session_state:
    st.session_state.messages = []

# 会話が空のときだけサンプル質問を表示
if not st.session_state.messages:
    st.markdown("##### 💡 サンプル質問（クリックで実行）")
    cols = st.columns(2)
    for i, q in enumerate(SAMPLE_QUESTIONS):
        if cols[i % 2].button(q, key=f"sample_{i}", use_container_width=True):
            st.session_state.pending_question = q
            st.rerun()

for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        if msg.get("search_docs"):
            docs = msg["search_docs"]
            with st.expander(f"🔍 検索結果（{len(docs)}件）", expanded=False):
                for doc in docs:
                    st.markdown(
                        f"**{doc['title']}** (スコア: {doc['score']:.2f})"
                    )
                    st.markdown(doc["content"][:300] + "...")
                    st.divider()
        with st.chat_message("assistant"):
            st.markdown(msg["content"])

# サンプル質問ボタンまたはチャット入力から質問を取得
question = st.chat_input("質問を入力してください")
if not question and st.session_state.get("pending_question"):
    question = st.session_state.pop("pending_question")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 過去の会話履歴を構築（直近のユーザー質問は含めない）
    history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in st.session_state.messages[:-1]
    ]

    with st.spinner("🔍 検索中..."):
        docs = search(question)

    with st.expander(f"🔍 検索結果（{len(docs)}件）", expanded=False):
        for doc in docs:
            st.markdown(f"**{doc['title']}** (スコア: {doc['score']:.2f})")
            st.markdown(doc["content"][:300] + "...")
            st.divider()

    with st.chat_message("assistant"):
        response_text = st.write_stream(
            generate_answer(question, docs, history)
        )

    st.session_state.messages.append(
        {"role": "assistant", "content": response_text, "search_docs": docs}
    )
