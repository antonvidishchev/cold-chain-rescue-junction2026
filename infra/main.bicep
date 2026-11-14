targetScope = 'subscription'

@sealed()
type ResourceNames = {
  functionApp: string
  functionPlan: string
  hostStorageAccount: string
  appStorageAccount: string
  keyVault: string
  logAnalyticsWorkspace: string
  appInsights: string
  staticWebApp: string
  userAssignedIdentity: string
}

param environmentName string
param location string
param resourceGroupName string
param sessionId string
param deployedBy string
param createdAt string
param resourceNames ResourceNames
param foundrySubscriptionId string
param foundryResourceGroupName string
param foundryAccountName string
param foundryDeploymentName string
param foundryEndpoint string

@description('Additional exact HTTPS origins. The actual Static Web App origin is always included.')
param corsOrigins array = []

@description('Legacy helper compatibility only; ignored. Build the frontend using the actual functionAppUrl output.')
#disable-next-line no-unused-params
param staticWebAppApiBaseUrl string = ''

@description('Optional bootstrap caller object ID for application Table, Blob and Queue data access. Empty disables these assignments.')
param deployerObjectId string = ''
param imageContainerName string = 'images'
param imageQueueName string = 'image-analysis'

@minValue(1)
param maxImageBytes int = 5242880

@secure()
@description('Six application secret values supplied only by the ignored, ACL-protected private parameter file.')
param appSecretValues object

var tags = {
  environment: environmentName
  sessionId: sessionId
  deployedBy: deployedBy
  createdAt: createdAt
  application: 'cold-chain-rescue'
}

resource appGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module identity './modules/identity.bicep' = {
  name: 'runtime-identity'
  scope: appGroup
  params: {
    name: resourceNames.userAssignedIdentity
    location: location
    tags: tags
  }
}

module storage './modules/storage.bicep' = {
  name: 'storage'
  scope: appGroup
  params: {
    location: location
    tags: tags
    hostStorageAccountName: resourceNames.hostStorageAccount
    appStorageAccountName: resourceNames.appStorageAccount
    principalId: identity.outputs.principalId
    deployerObjectId: deployerObjectId
    imageContainerName: imageContainerName
    imageQueueName: imageQueueName
  }
}

module vault './modules/key-vault.bicep' = {
  name: 'application-secrets'
  scope: appGroup
  params: {
    name: resourceNames.keyVault
    location: location
    tags: tags
    principalId: identity.outputs.principalId
    appSecretValues: appSecretValues
  }
}

module monitoring './modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: appGroup
  params: {
    location: location
    tags: tags
    workspaceName: resourceNames.logAnalyticsWorkspace
    appInsightsName: resourceNames.appInsights
  }
}

module frontend './modules/static-web-app.bicep' = {
  name: 'frontend'
  scope: appGroup
  params: {
    name: resourceNames.staticWebApp
    tags: tags
  }
}

module foundryAccess './modules/existing-foundry-access.bicep' = {
  name: 'coldchain-foundry-${uniqueString(appGroup.id)}'
  scope: resourceGroup(foundrySubscriptionId, foundryResourceGroupName)
  params: {
    accountName: foundryAccountName
    principalId: identity.outputs.principalId
  }
}

module backend './modules/functions.bicep' = {
  name: 'backend'
  scope: appGroup
  params: {
    name: resourceNames.functionApp
    planName: resourceNames.functionPlan
    location: location
    tags: tags
    identityResourceId: identity.outputs.resourceId
    identityClientId: identity.outputs.clientId
    hostStorageAccountName: storage.outputs.hostStorageAccountName
    deploymentContainerUrl: storage.outputs.deploymentContainerUrl
    tableServiceUrl: storage.outputs.tableServiceUrl
    blobServiceUrl: storage.outputs.blobServiceUrl
    queueServiceUrl: storage.outputs.queueServiceUrl
    imageContainerName: imageContainerName
    imageQueueName: imageQueueName
    tableName: storage.outputs.tableName
    maxImageBytes: maxImageBytes
    keyVaultUri: vault.outputs.vaultUri
    appInsightsConnectionString: monitoring.outputs.connectionString
    foundryEndpoint: foundryEndpoint
    foundryDeploymentName: foundryDeploymentName
    corsOrigins: union([frontend.outputs.url], corsOrigins)
  }
  dependsOn: [
    foundryAccess
  ]
}

@description('HTTPS API origin, without /api. Use for frontend VITE_API_URL (the client appends /api).')
output functionAppUrl string = backend.outputs.url
@description('HTTPS API route base including /api; not the frontend origin.')
output backendApiUrl string = '${backend.outputs.url}/api'
output staticWebAppUrl string = frontend.outputs.url
output functionAppName string = resourceNames.functionApp
output resourceGroupName string = appGroup.name
output hostStorageAccountName string = storage.outputs.hostStorageAccountName
output appStorageAccountName string = storage.outputs.appStorageAccountName
output storageAccountUrl string = storage.outputs.tableServiceUrl
output storageBlobUrl string = storage.outputs.blobServiceUrl
output storageQueueUrl string = storage.outputs.queueServiceUrl
output keyVaultName string = resourceNames.keyVault
