param location string
param tags object
param hostStorageAccountName string
param appStorageAccountName string
param principalId string
param deployerObjectId string = ''
param imageContainerName string
param imageQueueName string

var tableName = 'ColdChain'
var deploymentContainerName = 'function-deployments'
var blobContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var queueContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
var tableContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
var hostRoles = [
  subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b') // Blob Data Owner for Functions host.
  queueContributorRole
  subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '17d1049b-9a84-46fb-8f53-869881c3d3ab') // Storage Account Contributor for Functions host.
]
var appRoles = [
  blobContributorRole
  queueContributorRole
  tableContributorRole
]

resource host 'Microsoft.Storage/storageAccounts@2026-09-01' = {
  name: hostStorageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource app 'Microsoft.Storage/storageAccounts@2026-09-01' = {
  name: appStorageAccountName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource hostBlobs 'Microsoft.Storage/storageAccounts/blobServices@2026-09-01' = {
  parent: host
  name: 'default'
  properties: {}
}

resource deployment 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-09-01' = {
  parent: hostBlobs
  name: deploymentContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource appBlobs 'Microsoft.Storage/storageAccounts/blobServices@2026-09-01' = {
  parent: app
  name: 'default'
  properties: {}
}

resource images 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-09-01' = {
  parent: appBlobs
  name: imageContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource tables 'Microsoft.Storage/storageAccounts/tableServices@2026-09-01' = {
  parent: app
  name: 'default'
  properties: {}
}

resource table 'Microsoft.Storage/storageAccounts/tableServices/tables@2026-09-01' = {
  parent: tables
  name: tableName
  properties: {}
}

resource queues 'Microsoft.Storage/storageAccounts/queueServices@2026-09-01' = {
  parent: app
  name: 'default'
  properties: {}
}

resource imageQueues 'Microsoft.Storage/storageAccounts/queueServices/queues@2026-09-01' = [for name in [imageQueueName, '${imageQueueName}-poison']: {
  parent: queues
  name: name
  properties: {}
}]

resource imageLifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2026-09-01' = {
  parent: app
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-images-after-30-days'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['${imageContainerName}/']
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 30
                }
              }
            }
          }
        }
      ]
    }
  }
}

resource hostAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in hostRoles: {
  name: guid(host.id, principalId, roleId)
  scope: host
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource appAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in appRoles: {
  name: guid(app.id, principalId, roleId)
  scope: app
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

// The host Blob Data Owner already includes deployment data access. This explicit
// container grant records the deployment identity contract without widening scope.
resource deploymentAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(deployment.id, principalId, blobContributorRole)
  scope: deployment
  properties: {
    roleDefinitionId: blobContributorRole
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource bootstrapAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in appRoles: if (!empty(deployerObjectId)) {
  name: guid(app.id, deployerObjectId, roleId)
  scope: app
  properties: {
    roleDefinitionId: roleId
    principalId: deployerObjectId
  }
}]

output hostStorageAccountName string = host.name
output appStorageAccountName string = app.name
output deploymentContainerUrl string = '${host.properties.primaryEndpoints.blob}${deployment.name}'
output tableServiceUrl string = app.properties.primaryEndpoints.table
output blobServiceUrl string = app.properties.primaryEndpoints.blob
output queueServiceUrl string = app.properties.primaryEndpoints.queue
output tableName string = table.name
