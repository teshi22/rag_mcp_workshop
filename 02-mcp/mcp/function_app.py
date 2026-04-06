"""Azure Functions MCP サーバー — AI Search 検索ツール"""

import json
import logging
import os

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizableTextQuery

app = func.FunctionApp()

credential = DefaultAzureCredential()

tool_properties_search = json.dumps([
    {
        "propertyName": "query",
        "propertyType": "string",
        "description": "検索クエリ文字列",
    },
    {
        "propertyName": "top_k",
        "propertyType": "string",
        "description": "返す結果の最大件数（デフォルト: 3）",
    },
])


@app.generic_trigger(
    arg_name="context",
    type="mcpToolTrigger",
    toolName="search_documents",
    description="社内ドキュメントをハイブリッド検索（キーワード＋ベクトル）し、セマンティックリランカーで関連度順に返します。",
    toolProperties=tool_properties_search,
)
def search_documents(context) -> str:
    content = json.loads(context)
    args = content["arguments"]
    query = args["query"]
    top_k = int(args.get("top_k", "3"))

    logging.info(f"MCP search_documents: query='{query}', top_k={top_k}")

    search_client = SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=os.environ.get("AZURE_SEARCH_INDEX", "rag-index"),
        credential=credential,
    )

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

    return json.dumps(docs, ensure_ascii=False)
