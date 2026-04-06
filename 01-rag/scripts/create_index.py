"""Azure AI Search インデックス・インデクサー作成スクリプト

作成するリソース:
  1. 検索インデックス（ベクトル検索 + セマンティックリランカー）
  2. Blob データソース（マネージドID認証）
  3. スキルセット（チャンク分割 + ベクトル化）
  4. インデクサー
"""

import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential
from azure.search.documents.indexes import SearchIndexClient, SearchIndexerClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
    SearchIndexerDataSourceConnection,
    SearchIndexerDataContainer,
    SearchIndexer,
    SearchIndexerSkillset,
    SplitSkill,
    AzureOpenAIEmbeddingSkill,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchIndexerIndexProjection,
    SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters,
    IndexProjectionMode,
)

load_dotenv()

# 必須環境変数の設定有無を先に表示する
REQUIRED_ENV_VARS = [
    "AZURE_SEARCH_ENDPOINT",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_STORAGE_ACCOUNT_NAME",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP",
]


def print_and_validate_env_vars():
    print("=== 環境変数チェック ===")
    missing = []

    for key in REQUIRED_ENV_VARS:
        value = os.environ.get(key)
        print(f"{key}: {value if value else '<MISSING>'}")
        if not value:
            missing.append(key)

    print(
        "AZURE_SEARCH_INDEX: "
        f"{os.environ.get('AZURE_SEARCH_INDEX') or 'rag-index (default)'}"
    )
    print(
        "AZURE_OPENAI_EMBEDDING_MODEL: "
        f"{os.environ.get('AZURE_OPENAI_EMBEDDING_MODEL') or 'text-embedding-3-small (default)'}"
    )
    print(
        "AZURE_STORAGE_CONTAINER: "
        f"{os.environ.get('AZURE_STORAGE_CONTAINER') or 'documents (default)'}"
    )
    print()

    if missing:
        raise RuntimeError(f"必須環境変数が未設定です: {', '.join(missing)}")


# --- 設定 ---
SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT")
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX", "rag-index")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
EMBEDDING_MODEL = os.environ.get("AZURE_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
STORAGE_ACCOUNT = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME")
CONTAINER_NAME = os.environ.get("AZURE_STORAGE_CONTAINER", "documents")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID")
RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP")

STORAGE_RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}"
    f"/resourceGroups/{RESOURCE_GROUP}"
    f"/providers/Microsoft.Storage/storageAccounts/{STORAGE_ACCOUNT}"
)

index_client = None
indexer_client = None


def init_clients():
    global index_client
    global indexer_client
    credential = DefaultAzureCredential()
    index_client = SearchIndexClient(SEARCH_ENDPOINT, credential)
    indexer_client = SearchIndexerClient(SEARCH_ENDPOINT, credential)


def create_index():
    """検索インデックス作成（ベクトル検索 + セマンティックリランカー対応）"""
    fields = [
        SearchField(name="chunk_id", type=SearchFieldDataType.String, key=True, filterable=True, searchable=True, analyzer_name="keyword"),
        SimpleField(name="parent_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, analyzer_name="ja.lucene"),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="ja.lucene"),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="vector-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw")],
        profiles=[
            VectorSearchProfile(
                name="vector-profile",
                algorithm_configuration_name="hnsw",
                vectorizer_name="openai-vectorizer",
            )
        ],
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name="openai-vectorizer",
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=AZURE_OPENAI_ENDPOINT,
                    deployment_name=EMBEDDING_MODEL,
                    model_name="text-embedding-3-small",
                ),
            )
        ],
    )

    semantic_search = SemanticSearch(
        configurations=[
            SemanticConfiguration(
                name="default",
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ]
    )

    index = SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )
    index_client.create_or_update_index(index)
    print(f"✅ インデックス '{INDEX_NAME}' を作成しました")


def create_data_source():
    """Blob Storage データソース作成（マネージドID認証）"""
    data_source = SearchIndexerDataSourceConnection(
        name=f"{INDEX_NAME}-datasource",
        type="azureblob",
        connection_string=f"ResourceId={STORAGE_RESOURCE_ID};",
        container=SearchIndexerDataContainer(name=CONTAINER_NAME),
    )
    indexer_client.create_or_update_data_source_connection(data_source)
    print(f"✅ データソース '{data_source.name}' を作成しました")


def create_skillset():
    """スキルセット作成（チャンク分割 + ベクトル化）"""
    split_skill = SplitSkill(
        name="text-split",
        description="ドキュメントをチャンクに分割",
        context="/document",
        text_split_mode="pages",
        maximum_page_length=2000,
        page_overlap_length=500,
        inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
        outputs=[OutputFieldMappingEntry(name="textItems", target_name="pages")],
    )

    embedding_skill = AzureOpenAIEmbeddingSkill(
        name="embedding",
        description="テキストをベクトル化",
        context="/document/pages/*",
        resource_url=AZURE_OPENAI_ENDPOINT,
        deployment_name=EMBEDDING_MODEL,
        model_name="text-embedding-3-small",
        inputs=[InputFieldMappingEntry(name="text", source="/document/pages/*")],
        outputs=[OutputFieldMappingEntry(name="embedding", target_name="content_vector")],
    )

    index_projections = SearchIndexerIndexProjection(
        selectors=[
            SearchIndexerIndexProjectionSelector(
                target_index_name=INDEX_NAME,
                parent_key_field_name="parent_id",
                source_context="/document/pages/*",
                mappings=[
                    InputFieldMappingEntry(name="content", source="/document/pages/*"),
                    InputFieldMappingEntry(name="content_vector", source="/document/pages/*/content_vector"),
                    InputFieldMappingEntry(name="title", source="/document/metadata_storage_name"),
                ],
            )
        ],
        parameters=SearchIndexerIndexProjectionsParameters(
            projection_mode=IndexProjectionMode.SKIP_INDEXING_PARENT_DOCUMENTS,
        ),
    )

    skillset = SearchIndexerSkillset(
        name=f"{INDEX_NAME}-skillset",
        skills=[split_skill, embedding_skill],
        index_projection=index_projections,
    )
    indexer_client.create_or_update_skillset(skillset)
    print(f"✅ スキルセット '{skillset.name}' を作成しました")


def create_indexer():
    """インデクサー作成（作成後に自動実行される）"""
    indexer = SearchIndexer(
        name=f"{INDEX_NAME}-indexer",
        data_source_name=f"{INDEX_NAME}-datasource",
        skillset_name=f"{INDEX_NAME}-skillset",
        target_index_name=INDEX_NAME,
    )
    indexer_client.create_or_update_indexer(indexer)
    print(f"✅ インデクサー '{indexer.name}' を作成しました（自動実行されます）")


if __name__ == "__main__":
    print("=== Azure AI Search セットアップ ===\n")
    print_and_validate_env_vars()
    init_clients()
    create_index()
    create_data_source()
    create_skillset()
    create_indexer()
    print("\n✅ セットアップ完了！")
