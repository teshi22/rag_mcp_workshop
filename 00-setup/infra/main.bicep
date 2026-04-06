// ============================================================
// RAG Workshop — Azure リソース一括デプロイ
// ============================================================
// デプロイ:
//   az deployment group create -g <RG> -f infra/main.bicep -p prefix=<PREFIX>
//
// ローカル開発用のRBAC付与も必要なら:
//   az deployment group create -g <RG> -f infra/main.bicep \
//     -p prefix=<PREFIX> \
//     -p userPrincipalId=$(az ad signed-in-user show --query id -o tsv)
// ============================================================

@description('リソース名のプレフィックス（例: ragws）')
param prefix string

@description('リソースのリージョン')
param location string = resourceGroup().location

@description('Foundry のリージョン（モデル提供リージョンが異なる場合に指定）')
param foundryLocation string = location

@description('ローカル開発ユーザーのプリンシパルID（省略時はユーザー向けRBAC割当をスキップ）')
param userPrincipalId string = ''

@description('App Service をデプロイするか（VM クォータが必要）')
param deployAppService bool = false

@description('Azure Functions (MCP サーバー) をデプロイするか')
param deployFunctions bool = false

// ---- モデル設定 ----
param chatModelName string = 'gpt-4.1'
param chatModelVersion string = '2025-04-14'
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'

// ============================================================
// Microsoft Foundry（AIServices + Project）
// ============================================================
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${prefix}-ai'
  location: foundryLocation
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: '${prefix}-ai'
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: '${prefix}-project'
  location: foundryLocation
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'RAG Workshop'
    description: 'RAG + MCP ワークショップ用プロジェクト'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: chatModelName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: embeddingModelName
  dependsOn: [chatDeployment]
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

// ============================================================
// Azure AI Search（free 枠 — ワークショップ用途には十分）
// ============================================================
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: '${prefix}-search'
  location: location
  sku: { name: 'free' }
  identity: { type: 'SystemAssigned' }
  properties: {
    hostingMode: 'default'
    semanticSearch: 'free'
    publicNetworkAccess: 'enabled'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http403'
      }
    }
  }
}

// ============================================================
// Azure Blob Storage
// ============================================================
var storageAccountName = replace('${prefix}storage', '-', '')

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'documents'
}

// ============================================================
// App Service（Linux / Python 3.11）— deployAppService=true 時のみ
// ============================================================
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = if (deployAppService) {
  name: '${prefix}-plan'
  location: location
  kind: 'linux'
  sku: { name: 'B1' }
  properties: { reserved: true }
}

resource app 'Microsoft.Web/sites@2023-12-01' = if (deployAppService) {
  name: '${prefix}-app'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: 'pip install -r app/requirements.txt && python -m streamlit run app/app.py --server.port 8000 --server.address 0.0.0.0'
      appSettings: [
        { name: 'AZURE_OPENAI_ENDPOINT', value: foundry.properties.endpoint }
        { name: 'AZURE_OPENAI_MODEL', value: chatModelName }
        { name: 'AZURE_OPENAI_EMBEDDING_MODEL', value: embeddingModelName }
        { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'AZURE_SEARCH_INDEX', value: 'rag-index' }
        { name: 'MCP_SERVER_URL', value: deployFunctions ? 'https://${func.properties.defaultHostName}/runtime/webhooks/mcp/mcp' : '' }
      ]
    }
  }
}

// ============================================================
// RBAC ロール定義ID
// ============================================================
var roles = {
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
}

// ============================================================
// RBAC: AI Search → 他サービス（インデクサー用）
// ============================================================

// AI Search → Storage: Blob Data Reader（インデクサーがBlobを読む）
resource searchToStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, storage.id, roles.storageBlobDataReader)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataReader)
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// AI Search → Foundry: OpenAI User（埋め込みスキルが Embedding API を呼ぶ）
resource searchToFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(search.id, foundry.id, roles.cognitiveServicesOpenAIUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// RBAC: App Service → 他サービス（アプリ実行用、deployAppService=true 時のみ）
// ============================================================

// App Service → Foundry: OpenAI User（Responses API 呼び出し）
resource appToFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployAppService) {
  name: guid('${prefix}-app', foundry.id, roles.cognitiveServicesOpenAIUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: deployAppService ? app.identity.principalId : ''
    principalType: 'ServicePrincipal'
  }
}

// App Service → AI Search: Index Data Reader（検索クエリ）
resource appToSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployAppService) {
  name: guid('${prefix}-app', search.id, roles.searchIndexDataReader)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
    principalId: deployAppService ? app.identity.principalId : ''
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// Azure Functions — MCP サーバー（deployFunctions=true 時のみ）
// ============================================================
var funcStorageName = replace('${prefix}funcstor', '-', '')

resource funcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = if (deployFunctions) {
  name: funcStorageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: { accessTier: 'Hot' }
}

resource funcPlan 'Microsoft.Web/serverfarms@2023-12-01' = if (deployFunctions) {
  name: '${prefix}-func-plan'
  location: location
  kind: 'linux'
  sku: { name: 'Y1', tier: 'Dynamic' }
  properties: { reserved: true }
}

resource func 'Microsoft.Web/sites@2023-12-01' = if (deployFunctions) {
  name: '${prefix}-func'
  location: location
  kind: 'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: funcPlan.id
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${funcStorageName};EndpointSuffix=${environment().suffixes.storage};AccountKey=${deployFunctions ? funcStorage.listKeys().keys[0].value : ''}' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AZURE_SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'AZURE_SEARCH_INDEX', value: 'rag-index' }
      ]
    }
  }
}

// ============================================================
// RBAC: Azure Functions → 他サービス（deployFunctions=true 時のみ）
// ============================================================

// Functions → AI Search: Index Data Reader（検索クエリ）
resource funcToSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFunctions) {
  name: guid('${prefix}-func', search.id, roles.searchIndexDataReader)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
    principalId: deployFunctions ? func.identity.principalId : ''
    principalType: 'ServicePrincipal'
  }
}

// ============================================================
// RBAC: ローカル開発ユーザー（userPrincipalId 指定時のみ）
// ============================================================

// User → Foundry: OpenAI User
resource userToFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (userPrincipalId != '') {
  name: guid(userPrincipalId, foundry.id, roles.cognitiveServicesOpenAIUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// User → Storage: Blob Data Contributor（upload_docs.py）
resource userToStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (userPrincipalId != '') {
  name: guid(userPrincipalId, storage.id, roles.storageBlobDataContributor)
  scope: storage
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// User → AI Search: Search Service Contributor（create_index.py）
resource userToSearchContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (userPrincipalId != '') {
  name: guid(userPrincipalId, search.id, roles.searchServiceContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// User → AI Search: Index Data Contributor（インデックスデータ管理）
resource userToSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (userPrincipalId != '') {
  name: guid(userPrincipalId, search.id, roles.searchIndexDataContributor)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// User → AI Search: Index Data Reader（検索クエリ）
resource userToSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (userPrincipalId != '') {
  name: guid(userPrincipalId, search.id, roles.searchIndexDataReader)
  scope: search
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
    principalId: userPrincipalId
    principalType: 'User'
  }
}

// ============================================================
// Outputs
// ============================================================
output foundryEndpoint string = foundry.properties.endpoint
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output storageAccountName string = storage.name
output appUrl string = deployAppService ? 'https://${app.properties.defaultHostName}' : 'N/A (App Service not deployed)'
output funcUrl string = deployFunctions ? 'https://${func.properties.defaultHostName}' : 'N/A (Functions not deployed)'
output mcpEndpoint string = deployFunctions ? 'https://${func.properties.defaultHostName}/runtime/webhooks/mcp/mcp' : 'N/A'
output resourceGroup string = resourceGroup().name
output subscriptionId string = subscription().subscriptionId
