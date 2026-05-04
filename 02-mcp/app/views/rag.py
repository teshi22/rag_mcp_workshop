"""通常 RAG モード — Azure AI Search × Responses API"""

import os

import streamlit as st
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery

from common import AZURE_OPENAI_MODEL, credential, openai_client

# --- 設定 ---
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX", "rag-index")

# --- クライアント ---
search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=SEARCH_INDEX,
    credential=credential,
)


# *******************************************************************************
# 検索 & 回答生成の関数
# *******************************************************************************

# ドキュメントを検索する関数
def search(query: str, top_k: int = 3) -> list[dict]:
    """
    Azure AI Search でハイブリッド検索（キーワード + ベクトル） + セマンティックリランカーを実行する。

    Args:
        query: ユーザーの検索クエリ。
        top_k: 取得する上位件数。

    Returns:
        検索結果のリスト。各要素は {"title": str, "content": str, "score": float}。
    """
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


# 検索結果を踏まえて回答をストリーミング生成する関数
def generate_answer(
    question: str,
    context_docs: list[dict],
    history: list[dict],
):
    """
    検索結果をコンテキストにして Responses API でストリーミング回答を生成する。

    Args:
        question: ユーザーの質問。
        context_docs: search() の返り値。コンテキストとしてプロンプトに埋め込む。
        history: 過去の会話履歴（直近のユーザー質問は含めない）。

    Yields:
        ストリーミングされる回答テキストのデルタ。
    """
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


# *******************************************************************************
# Streamlit UI 
# *******************************************************************************

st.title("📚 RAG デモ")
st.caption("Azure AI Search × Responses API による検索拡張生成")

if st.sidebar.button("🗑️ 会話履歴をリセット"):
    st.session_state.rag_messages = []
    st.rerun()

SAMPLE_QUESTIONS = [
    "Azure リソースの命名規則を教えてください",
    "セキュリティポリシーの概要を教えて",
    "インシデント発生時の対応フローは？",
    "コスト管理のルールについて教えて",
]

# チャット履歴
if "rag_messages" not in st.session_state:
    st.session_state.rag_messages = []

# 会話が空のときだけサンプル質問を表示
sample_placeholder = st.empty()
if not st.session_state.rag_messages:
    with sample_placeholder.container():
        st.markdown("##### 💡 サンプル質問（クリックで実行）")
        cols = st.columns(2)
        for i, q in enumerate(SAMPLE_QUESTIONS):
            if cols[i % 2].button(q, key=f"rag_sample_{i}", use_container_width=True):
                st.session_state.rag_pending_question = q
                st.rerun()

for msg in st.session_state.rag_messages:
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
if not question and st.session_state.get("rag_pending_question"):
    question = st.session_state.pop("rag_pending_question")

if question:
    sample_placeholder.empty()

    st.session_state.rag_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 過去の会話履歴を構築（直近のユーザー質問は含めない）
    history = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in st.session_state.rag_messages[:-1]
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

    st.session_state.rag_messages.append(
        {"role": "assistant", "content": response_text, "search_docs": docs}
    )
