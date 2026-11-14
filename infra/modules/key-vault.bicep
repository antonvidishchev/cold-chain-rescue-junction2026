param name string
param location string
param tags object
param principalId string

@secure()
param appSecretValues object

var secretKeys = [
  'COLDCHAIN_DEVICE_KEYS'
  'COLDCHAIN_DEVICE_FUNCTION_KEY'
  'COLDCHAIN_OPERATOR_KEY'
  'VAPID_PRIVATE_KEY'
  'VAPID_PUBLIC_KEY'
  'VAPID_SUBJECT'
]

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 7
    accessPolicies: []
  }
}

resource secrets 'Microsoft.KeyVault/vaults/secrets@2026-05-15' = [for key in secretKeys: {
  parent: vault
  name: replace(key, '_', '-')
  properties: {
    value: appSecretValues[key]
  }
}]

var secretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource runtimeSecretsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vault.id, principalId, secretsUserRole)
  scope: vault
  properties: {
    roleDefinitionId: secretsUserRole
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output vaultUri string = vault.properties.vaultUri
