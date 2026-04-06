"""Streamlit RAG アプリ — RAG / AI エージェント + MCP 切替対応"""

import asyncio
import json
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

# MCP サーバー一覧（複数対応）
MCP_SERVERS = {
    "社内ドキュメント検索": os.environ.get(
        "MCP_SERVER_URL", "http://localhost:7071/runtime/webhooks/mcp/mcp"
    ),
    "Microsoft Learn": "https://learn.microsoft.com/api/mcp",
}

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


# ========== ユーティリティ ==========
def run_async(coro):
    """Streamlit (同期) から async コルーチンを実行"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ========== RAG モード: 検索 ==========
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


# ========== RAG モード: 回答生成 ==========
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


# ========== MCP モード: ツール取得・呼び出し ==========
async def fetch_mcp_tools_from(url):
    """単一の MCP サーバーからツール一覧を取得"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url=url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def fetch_all_mcp_tools():
    """全 MCP サーバーからツールを取得し、ツール名→サーバーURL のマッピングも返す"""
    all_tools = []
    tool_to_server = {}
    for label, url in MCP_SERVERS.items():
        try:
            tools = await fetch_mcp_tools_from(url)
            for tool in tools:
                all_tools.append(tool)
                tool_to_server[tool.name] = {"url": url, "label": label}
        except Exception as e:
            st.warning(f"⚠️ {label} への接続に失敗: {e}")
    return all_tools, tool_to_server


async def call_mcp_tool_async(server_url, tool_name, arguments):
    """指定した MCP サーバーのツールを実行"""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url=server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result


def mcp_tools_to_openai(mcp_tools):
    """MCP ツール定義を Responses API の function tools 形式に変換"""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema
            or {"type": "object", "properties": {}},
        }
        for tool in mcp_tools
    ]


# ========== MCP モード: エージェントループ ==========
def agent_answer(question, openai_tools, tool_to_server, history):
    """Responses API + MCP ツールによるエージェントループ"""
    system_prompt = """あなたは社内ドキュメントと Microsoft 公式ドキュメントの両方を活用して回答するアシスタントです。

## 利用可能なツール
- search_documents: 社内ドキュメント（運用ガイドライン、セキュリティポリシー等）を検索
- microsoft_docs_search: Microsoft Learn の公式ドキュメントを検索
- microsoft_docs_fetch: Microsoft Learn の記事の全文を取得
- microsoft_code_sample_search: Microsoft のコードサンプルを検索

## ツール使用ルール
- ユーザーが新しい情報を求める質問をした場合は、必ずツールで検索してから回答してください。自分の知識だけで回答しないでください。
- 社内ルールと公式ドキュメントの両方を調べるよう求められた場合は、search_documents と microsoft_docs_search の両方を使ってください。
- ユーザーが会話履歴に対する操作（要約、翻訳、言い換え、比較など）を指示した場合は、ツールを使わずにそのまま実行してください。
- 検索結果に情報がない場合は「該当する情報が見つかりませんでした」と回答してください。"""

    input_messages = [{"role": "system", "content": system_prompt}]
    input_messages.extend(history)
    input_messages.append({"role": "user", "content": question})

    response = openai_client.responses.create(
        model=AZURE_OPENAI_MODEL,
        tools=openai_tools,
        input=input_messages,
    )

    tool_calls_log = []

    # ツール呼び出しが続く限りループ
    while any(item.type == "function_call" for item in response.output):
        tool_results = []
        for item in response.output:
            if item.type != "function_call":
                continue
            args = json.loads(item.arguments)
            server_info = tool_to_server.get(item.name, {})
            server_url = server_info.get("url", "")
            server_label = server_info.get("label", "")
            tool_calls_log.append(
                {"name": item.name, "arguments": args, "server": server_label}
            )
            result = run_async(call_mcp_tool_async(server_url, item.name, args))
            content_text = "\n".join(
                c.text for c in result.content if hasattr(c, "text")
            )
            tool_results.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": content_text,
                }
            )

        response = openai_client.responses.create(
            model=AZURE_OPENAI_MODEL,
            tools=openai_tools,
            previous_response_id=response.id,
            input=tool_results,
        )

    return response.output_text, tool_calls_log


# ========== Streamlit UI ==========
st.title("📚 RAG デモ")

mode = st.sidebar.radio("🔧 モード選択", ["RAG", "AI エージェント + MCP"])

if st.sidebar.button("🗑️ 会話履歴をリセット"):
    st.session_state.messages = []
    st.rerun()

# モード変更時にチャット履歴をリセット
if "current_mode" not in st.session_state:
    st.session_state.current_mode = mode
if st.session_state.current_mode != mode:
    st.session_state.current_mode = mode
    st.session_state.messages = []
    st.session_state.pop("mcp_tools", None)
    st.session_state.pop("openai_tools", None)
    st.session_state.pop("tool_to_server", None)
    st.rerun()

if mode == "RAG":
    st.caption("Azure AI Search × Responses API による検索拡張生成")
else:
    st.caption("AI エージェントが MCP ツールを使って回答を生成")
    # MCP ツール一覧を取得（初回のみ）
    if "mcp_tools" not in st.session_state:
        with st.spinner("🔌 MCP サーバーに接続中..."):
            mcp_tools, tool_to_server = run_async(fetch_all_mcp_tools())
            if not mcp_tools:
                st.error("MCP サーバーからツールを取得できませんでした")
                st.stop()
            st.session_state.mcp_tools = mcp_tools
            st.session_state.openai_tools = mcp_tools_to_openai(mcp_tools)
            st.session_state.tool_to_server = tool_to_server
    with st.sidebar.expander("🔧 MCP ツール一覧"):
        for tool in st.session_state.mcp_tools:
            server_label = st.session_state.tool_to_server.get(
                tool.name, {}
            ).get("label", "")
            st.markdown(f"**{tool.name}** ({server_label})")
            st.caption(tool.description)

# サンプル質問
SAMPLE_QUESTIONS = {
    "RAG": [
        "Azure リソースの命名規則を教えてください",
        "セキュリティポリシーの概要を教えて",
        "インシデント発生時の対応フローは？",
        "コスト管理のルールについて教えて",
    ],
    "AI エージェント + MCP": [
        "社内の Azure 命名規則を教えて",
        "Azure Functions の Python でのデプロイ方法は？",
        "社内のセキュリティポリシーと Azure のベストプラクティスを比較して",
        "開発標準で使うべき IaC ツールは何？公式ドキュメントも調べて",
    ],
}

# チャット履歴
if "messages" not in st.session_state:
    st.session_state.messages = []

# 会話が空のときだけサンプル質問を表示
if not st.session_state.messages:
    st.markdown("##### 💡 サンプル質問（クリックで実行）")
    cols = st.columns(2)
    for i, q in enumerate(SAMPLE_QUESTIONS[mode]):
        if cols[i % 2].button(q, key=f"sample_{i}", use_container_width=True):
            st.session_state.pending_question = q
            st.rerun()

for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        # 検索結果の表示（RAG モード）
        if msg.get("search_docs"):
            docs = msg["search_docs"]
            with st.expander(f"🔍 検索結果（{len(docs)}件）", expanded=False):
                for doc in docs:
                    st.markdown(
                        f"**{doc['title']}** (スコア: {doc['score']:.2f})"
                    )
                    st.markdown(doc["content"][:300] + "...")
                    st.divider()
        # ツール呼び出しの表示（Agent + MCP モード）
        if msg.get("tool_calls"):
            tcs = msg["tool_calls"]
            with st.expander(
                f"🔧 ツール呼び出し（{len(tcs)}回）", expanded=False
            ):
                for tc in tcs:
                    server = tc.get("server", "")
                    label = f" ({server})" if server else ""
                    st.markdown(
                        f"**{tc['name']}**{label} "
                        f"`{json.dumps(tc['arguments'], ensure_ascii=False)}`"
                    )
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
        for msg in st.session_state.messages[:-1]  # 最後の user メッセージは除外
    ]

    if mode == "RAG":
        # --- RAG: 検索 → ストリーミング回答 ---
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

    else:
        # --- Agent + MCP: エージェントループ ---
        with st.spinner("🤖 エージェントが回答を生成中..."):
            response_text, tool_calls = agent_answer(
                question,
                st.session_state.openai_tools,
                st.session_state.tool_to_server,
                history,
            )

        if tool_calls:
            with st.expander(
                f"🔧 ツール呼び出し（{len(tool_calls)}回）", expanded=False
            ):
                for tc in tool_calls:
                    server = tc.get("server", "")
                    label = f" ({server})" if server else ""
                    st.markdown(
                        f"**{tc['name']}**{label} "
                        f"`{json.dumps(tc['arguments'], ensure_ascii=False)}`"
                    )
                    st.divider()

        with st.chat_message("assistant"):
            st.markdown(response_text)

        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response_text,
                "tool_calls": tool_calls,
            }
        )
