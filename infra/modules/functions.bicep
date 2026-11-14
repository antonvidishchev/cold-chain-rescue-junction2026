param name string
param planName string
param location string
param tags object
param identityResourceId string
param identityClientId string
param hostStorageAccountName string
param deploymentContainerUrl string
param tableServiceUrl string
param blobServiceUrl string
param queueServiceUrl string
param imageContainerName string
param imageQueueName string
param tableName string
param maxImageBytes int
param keyVaultUri string
param appInsightsConnectionString string
param foundryEndpoint string
param foundryDeploymentName string
param corsOrigins array

var secretKeys = [
  'COLDCHAIN_DEVICE_KEYS'
  'COLDCHAIN_DEVICE_FUNCTION_KEY'
  'COLDCHAIN_OPERATOR_KEY'
  'VAPID_PRIVATE_KEY'
  'VAPID_PUBLIC_KEY'
  'VAPID_SUBJECT'
]
var secretSettings = [for key in secretKeys: {
  name: key
  value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/${replace(key, '_', '-')})'
}]
var settings = {
  AzureWebJobsStorage__accountName: hostStorageAccountName
  AzureWebJobsStorage__credential: 'managedidentity'
  AzureWebJobsStorage__clientId: identityClientId
  ImageStorage__queueServiceUri: queueServiceUrl
  ImageStorage__credential: 'managedidentity'
  ImageStorage__clientId: identityClientId
  AZURE_CLIENT_ID: identityClientId
  STORAGE_ACCOUNT_URL: tableServiceUrl
  STORAGE_BLOB_URL: blobServiceUrl
  STORAGE_QUEUE_URL: queueServiceUrl
  IMAGE_QUEUE_NAME: imageQueueName
  IMAGE_CONTAINER: imageContainerName
  COLDCHAIN_TABLE_NAME: tableName
  MAX_IMAGE_BYTES: string(maxImageBytes)
  COLDCHAIN_IMAGE_MAX_BYTES: string(maxImageBytes)
  FOUNDRY_ENDPOINT: foundryEndpoint
  FOUNDRY_VISION_DEPLOYMENT: foundryDeploymentName
  APPLICATIONINSIGHTS_CONNECTION_STRING: appInsightsConnectionString
}

var runtimeSettings = [for setting in items(settings): {
  name: setting.key
  value: setting.value
}]

resource plan 'Microsoft.Web/serverfarms@2026-08-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource app 'Microsoft.Web/sites@2026-08-01' = {
  name: name
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityResourceId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    keyVaultReferenceIdentity: identityResourceId
    functionAppConfig: {
      runtime: {
        name: 'python'
        version: '3.13'
      }
      scaleAndConcurrency: {
        instanceMemoryMB: 2048
        maximumInstanceCount: 40
        alwaysReady: []
      }
      deployment: {
        storage: {
          type: 'blobContainer'
          value: deploymentContainerUrl
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identityResourceId
          }
        }
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      scmMinTlsVersion: '1.2'
      ftpsState: 'Disabled'
      cors: {
        allowedOrigins: corsOrigins
        supportCredentials: false
      }
      appSettings: concat(runtimeSettings, secretSettings)
    }
  }
}

output url string = 'https://${app.properties.defaultHostName}'
