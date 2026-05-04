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

# 同期コードから async コルーチンを実行する関数
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

# 1 つの MCP サーバーからツール一覧を取得する関数
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


# 全 MCP サーバーからツールを集めて一覧とツール名→サーバーの対応表を返す関数
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


# 指定した MCP ツールを呼び出して結果を取得する関数
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


# MCP ツール定義を Responses API の function tools 形式に変換する関数
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

# ツール呼び出しを繰り返しながら回答をストリーミング生成する関数
def agent_answer(
    question: str,
    openai_tools: list[dict],
    tool_to_server: dict[str, dict],
    history: list[dict],
):
    """
    Responses API + MCP ツールによるエージェントループ。

    LLM がツール呼び出しを返す限り MCP ツールを実行し、結果を LLM に返して
    最終的なテキスト回答が得られるまで繰り返す。途中経過をイベントとして yield する。

    Args:
        question: ユーザーの質問。
        openai_tools: mcp_tools_to_openai() で変換済みのツール定義。
        tool_to_server: ツール名 → {"url":..., "label":...} の対応表。
        history: 過去の会話履歴（直近のユーザー質問は含めない）。

    Yields:
        (kind, payload) のタプル。kind は以下の 3 種類:
            - "tool_call": ツール呼び出し情報 {"name": str, "arguments": dict, "server": str}
            - "tool_result": ツール実行結果 {"name": str, "content": str}
            - "text_delta": ストリーミングされる回答テキストのデルタ (str)
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

    # 初回リクエスト
    stream = openai_client.responses.create(
        model=AZURE_OPENAI_MODEL,
        tools=openai_tools,
        input=input_messages,
        stream=True,
    )

    # ツール呼び出しが続く限りループ
    while True:
        function_calls = []
        response_id = None
        for event in stream:
            if event.type == "response.output_text.delta":
                yield ("text_delta", event.delta)
            elif event.type == "response.completed":
                response_id = event.response.id
                function_calls = [
                    item
                    for item in event.response.output
                    if item.type == "function_call"
                ]

        # ツール呼び出しがなければ完了
        if not function_calls:
            return

        # ツールを実行して結果を集める
        tool_results = []
        for item in function_calls:
            args = json.loads(item.arguments)
            server_info = tool_to_server.get(item.name, {})
            server_url = server_info.get("url", "")
            server_label = server_info.get("label", "")
            yield (
                "tool_call",
                {"name": item.name, "arguments": args, "server": server_label},
            )
            result = run_async(call_mcp_tool_async(server_url, item.name, args))
            content_text = "\n".join(
                c.text for c in result.content if hasattr(c, "text")
            )
            yield ("tool_result", {"name": item.name, "content": content_text})
            tool_results.append(
                {
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": content_text,
                }
            )

        # ツール結果を返して次のリクエストへ
        stream = openai_client.responses.create(
            model=AZURE_OPENAI_MODEL,
            tools=openai_tools,
            previous_response_id=response_id,
            input=tool_results,
            stream=True,
        )


# *******************************************************************************
# Streamlit UI 
# *******************************************************************************

# ツール実行結果を読みやすい形で表示する関数
def render_tool_result(content_text: str) -> None:
    """
    MCP ツールの返り値を可能ならドキュメント一覧として表示する。

    JSON としてパースでき、title/content の並びだと見なせる場合は
    RAG モードの検索結果と同じスタイルで表示し、それ以外は
    コードブロックとして表示する。
    """
    try:
        data = json.loads(content_text)
    except (json.JSONDecodeError, TypeError):
        st.code(content_text[:1000] + ("..." if len(content_text) > 1000 else ""))
        return

    # {"results": [...]} の形式は results の中身を見る
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        data = data["results"]

    if isinstance(data, list) and data and all(
        isinstance(d, dict) and ("title" in d or "content" in d) for d in data
    ):
        for d in data:
            title = d.get("title", "(no title)")
            content = d.get("content", "")
            url = d.get("contentUrl") or d.get("url")
            if url:
                st.markdown(f"**[{title}]({url})**")
            else:
                st.markdown(f"**{title}**")
            st.markdown(content[:300] + ("..." if len(content) > 300 else ""))
        return

    st.json(data, expanded=False)


st.title("📚 AI エージェント + MCP")
st.caption("AI エージェントが MCP ツールを使って回答を生成")

if st.sidebar.button("🗑️ 会話履歴をリセット"):
    st.session_state.agent_messages = []
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
if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []

# 会話が空のときだけサンプル質問を表示
sample_placeholder = st.empty()
if not st.session_state.agent_messages:
    with sample_placeholder.container():
        st.markdown("##### 💡 サンプル質問（クリックで実行）")
        cols = st.columns(2)
        for i, q in enumerate(SAMPLE_QUESTIONS):
            if cols[i % 2].button(q, key=f"agent_sample_{i}", use_container_width=True):
                st.session_state.agent_pending_question = q
                st.rerun()

for msg in st.session_state.agent_messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    elif msg["role"] == "assistant":
        with st.chat_message("assistant"):
            # ツール呼び出しと回答テキストを出現順に表示
            for seg in msg.get("segments", []):
                if seg["type"] == "tools":
                    tools = seg["data"]
                    with st.expander(
                        f"🔧 ツール呼び出し（{len(tools)}件）", expanded=False
                    ):
                        for tc in tools:
                            server = tc.get("server", "")
                            label = f" ({server})" if server else ""
                            st.markdown(
                                f"**{tc['name']}**{label} "
                                f"`{json.dumps(tc['arguments'], ensure_ascii=False)}`"
                            )
                            if tc.get("result"):
                                render_tool_result(tc["result"])
                            st.divider()
                elif seg["type"] == "text":
                    st.markdown(seg["content"])

# サンプル質問ボタンまたはチャット入力から質問を取得
question = st.chat_input("質問を入力してください")
if not question and st.session_state.get("agent_pending_question"):
    question = st.session_state.pop("agent_pending_question")

if question:
    sample_placeholder.empty()

    st.session_state.agent_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    # 過去の会話履歴を構築（直近のユーザー質問は含めない）
    history = []
    for msg in st.session_state.agent_messages[:-1]:
        if msg["role"] == "user":
            history.append({"role": "user", "content": msg["content"]})
        elif msg["role"] == "assistant":
            # アシスタントの回答テキスト部分だけを連結して LLM に渡す
            text = "".join(
                seg["content"]
                for seg in msg.get("segments", [])
                if seg["type"] == "text"
            )
            if text:
                history.append({"role": "assistant", "content": text})

    # エージェントから順に返ってくる出力をそのまま上から表示し、同じ順番でチャット履歴に保存
    segments = []
    current_tools = []
    tools_expander = None
    text_buffer = ""
    text_placeholder = None

    with st.chat_message("assistant"):
        for kind, payload in agent_answer(
            question,
            st.session_state.openai_tools,
            st.session_state.tool_to_server,
            history,
        ):
            if kind == "tool_call":
                # テキストを区切って、ツール呼び出し用の折りたたみブロックを開く
                if text_buffer:
                    segments.append({"type": "text", "content": text_buffer})
                    text_buffer = ""
                    text_placeholder = None
                if tools_expander is None:
                    current_tools = []
                    tools_expander = st.expander("🔧 ツール呼び出し", expanded=False)
                with tools_expander:
                    server = payload.get("server", "")
                    label = f" ({server})" if server else ""
                    st.markdown(
                        f"**{payload['name']}**{label} "
                        f"`{json.dumps(payload['arguments'], ensure_ascii=False)}`"
                    )
                current_tools.append({**payload, "result": None})
            elif kind == "tool_result":
                # 直前のツール呼び出しに結果を紐づけて表示
                if current_tools:
                    current_tools[-1]["result"] = payload["content"]
                    with tools_expander:
                        render_tool_result(payload["content"])
                        st.divider()
            elif kind == "text_delta":
                # 同じテキストブロックに文字を追加しながら表示
                if current_tools:
                    segments.append({"type": "tools", "data": current_tools})
                    current_tools = []
                    tools_expander = None
                if text_placeholder is None:
                    text_placeholder = st.empty()
                text_buffer += payload
                text_placeholder.markdown(text_buffer)

        # 最後に残っているブロックをチャット履歴に保存
        if current_tools:
            segments.append({"type": "tools", "data": current_tools})
        if text_buffer:
            segments.append({"type": "text", "content": text_buffer})

    st.session_state.agent_messages.append(
        {"role": "assistant", "segments": segments}
    )
