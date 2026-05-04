"""AI エージェント + MCP モード — Responses API + MCP ツール"""

import asyncio
import json
import os
from typing import Any, Coroutine

import streamlit as st
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Tool

from common import AZURE_OPENAI_MODEL, openai_client


# MCP サーバー一覧（複数対応）
MCP_SERVERS = {
    "社内ドキュメント検索": os.environ.get(
        "MCP_SERVER_URL", "http://localhost:7071/runtime/webhooks/mcp/mcp"
    ),
    "Microsoft Learn": "https://learn.microsoft.com/api/mcp",
}


# *******************************************************************************
# 非同期実行ヘルパー
# *******************************************************************************

# 同期コードから async コルーチンを実行
def run_async(coro: Coroutine) -> Any:
    """
    Streamlit (同期) から async コルーチンを実行する。

    Args:
        coro: 実行したいコルーチン。

    Returns:
        コルーチンの返り値。
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# *******************************************************************************
# MCP ツール連携（取得・実行・変換）
# *******************************************************************************

# 1 つの MCP サーバーからツール一覧を取得
async def fetch_mcp_tools_from(url: str) -> list[Tool]:
    """
    単一の MCP サーバーに接続してツール一覧を取得する。

    Args:
        url: MCP サーバーのエンドポイント URL。

    Returns:
        サーバーから取得した Tool オブジェクトのリスト。
    """
    async with streamable_http_client(url=url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


# 全 MCP サーバーのツールを集約し、ツール名→サーバーの対応表も返す
async def fetch_all_mcp_tools() -> tuple[list[Tool], dict[str, dict]]:
    """
    MCP_SERVERS に定義された全サーバーからツールを取得して集約する。

    Returns:
        (全ツールのリスト, ツール名→{"url":..., "label":...} の対応表) のタプル。
    """
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


# 指定した MCP ツールを呼び出して結果を取得
async def call_mcp_tool_async(
    server_url: str, tool_name: str, arguments: dict
) -> CallToolResult:
    """
    指定した MCP サーバーのツールを実行する。

    Args:
        server_url: ツールを提供する MCP サーバーの URL。
        tool_name: 呼び出すツール名。
        arguments: ツールに渡す引数。

    Returns:
        MCP サーバーからの実行結果。
    """
    async with streamable_http_client(url=server_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            return result


# MCP ツール定義を Responses API の function tools 形式に変換
def mcp_tools_to_openai(mcp_tools: list[Tool]) -> list[dict]:
    """
    MCP の Tool 定義を Responses API に渡せる function tools 形式に変換する。

    Args:
        mcp_tools: MCP SDK から取得した Tool オブジェクトのリスト。

    Returns:
        Responses API の tools 引数にそのまま渡せる dict のリスト。
    """
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


# *******************************************************************************
# エージェントループ
# *******************************************************************************

# ツール呼び出しを繰り返しながら回答を生成
def agent_answer(
    question: str,
    openai_tools: list[dict],
    tool_to_server: dict[str, dict],
    history: list[dict],
) -> tuple[str, list[dict]]:
    """
    Responses API + MCP ツールによるエージェントループ。

    LLM がツール呼び出しを返す限り MCP ツールを実行し、結果を LLM に返して
    最終的なテキスト回答が得られるまで繰り返す。

    Args:
        question: ユーザーの質問。
        openai_tools: mcp_tools_to_openai() で変換済みのツール定義。
        tool_to_server: ツール名 → {"url":..., "label":...} の対応表。
        history: 過去の会話履歴（直近のユーザー質問は含めない）。

    Returns:
        (最終回答テキスト, ツール呼び出しログのリスト) のタプル。
        ログの各要素は {"name": str, "arguments": dict, "server": str}。
    """
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


# *******************************************************************************
# Streamlit UI 
# *******************************************************************************

st.title("📚 RAG デモ")
st.caption("AI エージェントが MCP ツールを使って回答を生成")

if st.sidebar.button("🗑️ 会話履歴をリセット"):
    st.session_state.messages = []
    st.rerun()

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

SAMPLE_QUESTIONS = [
    "社内の Azure 命名規則を教えて",
    "Azure Functions の Python でのデプロイ方法は？",
    "社内のセキュリティポリシーと Azure のベストプラクティスを比較して",
    "開発標準で使うべき IaC ツールは何？公式ドキュメントも調べて",
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
        for msg in st.session_state.messages[:-1]
    ]

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
