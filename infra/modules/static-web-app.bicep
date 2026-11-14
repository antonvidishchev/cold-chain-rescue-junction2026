param name string
param tags object

resource site 'Microsoft.Web/staticSites@2025-05-01' = {
  name: name
  location: 'westeurope'
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    allowConfigFileUpdates: true
  }
}

output url string = 'https://${site.properties.defaultHostname}'
