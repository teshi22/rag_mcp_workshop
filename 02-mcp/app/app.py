"""Streamlit RAG アプリ — エントリポイント（ナビゲーション定義）"""

import streamlit as st

pages = [
    st.Page("views/rag.py", title="通常 RAG", icon="📚", default=True),
    st.Page("views/agent_mcp.py", title="AI エージェント + MCP", icon="📚"),
]

st.navigation(pages).run()
