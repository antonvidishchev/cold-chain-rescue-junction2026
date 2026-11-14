# Cold Chain Azure infrastructure

`main.bicep` is a subscription-scope template. It creates one application resource group and deploys resource-scoped modules. **Compilation and validation do not authorize provisioning or code publication.** No application code or model deployment is created by Bicep.

## Resources and boundaries

- Linux Azure Functions Flex Consumption (`FC1`), Python 3.13, 2,048 MB, maximum 40 instances, no always-ready instances. Native `functionAppConfig` configures runtime, scaling and deployment storage; legacy runtime/package app settings are deliberately absent.
- Standard Static Web App in West Europe, with no linked backend. Its **actual** `defaultHostname` becomes an exact Functions CORS origin. Additional `corsOrigins` default to `[]`; wildcards are not needed. The frontend calls the separate public Functions origin.
- Two Hot GPv2 Standard_LRS accounts, HTTPS/TLS 1.2 only, anonymous blobs and shared-key access disabled. The host account contains a private `function-deployments` container. The application account contains private `images`, Table `ColdChain`, and queues `image-analysis` / `image-analysis-poison` by default.
- Only the application image-container prefix has a 30-day last-modified block-blob deletion policy. Host/deployment blobs, Tables and queues are not subject to that policy. Lifecycle processing is asynchronous, not an exact deletion deadline.
- Standard RBAC Key Vault, soft delete and purge protection. Six `appSecretValues` keys become hyphenated secret names: `COLDCHAIN-DEVICE-KEYS`, `COLDCHAIN-DEVICE-FUNCTION-KEY`, `COLDCHAIN-OPERATOR-KEY`, `VAPID-PRIVATE-KEY`, `VAPID-PUBLIC-KEY`, `VAPID-SUBJECT`. Both receiving Bicep modules use `@secure()`; no secret values are outputs. Functions uses versionless Key Vault references through its user-assigned identity.
- Workspace Application Insights and Log Analytics with 30-day retention and a 0.1 GB daily ingestion target cap. This is not a total spending cap or guaranteed ingestion ceiling.
- An **existing** Foundry account receives an account-scoped Cognitive Services OpenAI User assignment. The cross-resource-group module creates only that assignment, not an account, project or model deployment. Supply an existing, vision-capable deployment and matching inference endpoint privately.

### Identity permissions

The runtime user-assigned identity receives Key Vault Secrets User on the vault; Storage Table/Blob/Queue Data Contributor on application storage; Storage Blob Data Owner, Storage Queue Data Contributor and Storage Account Contributor on host storage. The deployment container also has an explicit Storage Blob Data Contributor assignment (covered by the broader required host Blob Data Owner permission). Deployment authentication uses `UserAssignedIdentity` and **`userAssignedIdentityResourceId`**, not `userAssignedIdentityId`.

Optional `deployerObjectId` grants the bootstrap caller application Storage Table, Blob and Queue Data Contributor for seeding and idempotent container/queue creation. An empty value disables these grants in Bicep; publication/bootstrap needs an appropriately authorized caller. The private helper may require a caller ID for its full workflow. No assignment is subscription-wide or resource-group-wide. The executing deployment principal separately needs resource creation, nested deployment, secret-write and role-assignment permissions at the relevant scopes, including the existing Foundry account. RBAC propagation can delay runtime and bootstrap access after a successful deployment.

## Private configuration contract

`main.parameters.example.json` is a **nondeployable shape example**, not a place to store real identifiers or credentials. Keep filled values in ignored `.azure-private` files protected by the Windows helper ACLs. Do not print generated parameter files, deploy with literal secrets on command lines, commit compiled private artifacts, or publish deployment diagnostics containing input parameters.

The Bicep parameter set matches `scripts\private_config.py`: all required helper parameters, its three optional parameters (`maxImageBytes`, `imageContainerName`, `imageQueueName`), and secure `appSecretValues`. `resourceNames` has exactly nine members: `functionApp`, `functionPlan`, `hostStorageAccount`, `appStorageAccount`, `keyVault`, `logAnalyticsWorkspace`, `appInsights`, `staticWebApp`, `userAssignedIdentity`. Ancillary plan/identity names are supplied there, not inferred. Resource metadata tags use the private `environmentName`, `sessionId`, `deployedBy`, and `createdAt` values.

`staticWebAppApiBaseUrl` is retained solely for legacy helper compatibility, defaults to `''`, and is intentionally unused. No hostname is guessed for first deployment. Secret generation and validation are owned by the private helpers; do not fill the example secret placeholders manually.

## Local preparation and independent approval gates

Run commands from the repository root in PowerShell. Populate an ACL-protected private source configuration matching the helper contract, then use `infra\scripts\Initialize-PrivateConfig.ps1 -SourceConfig <private-source-path> -ApproveCredentialGeneration` to initialize `.azure-private` and generate device/operator/VAPID credentials. Reuse existing credentials on subsequent runs; do not accidentally rotate them. The helpers require their documented local Python environment/dependencies and Azure CLI version.

Offline template compilation (no Azure changes and no compiled file):

```powershell
az bicep build --file .\infra\main.bicep --stdout 1>$null
```

Once private configuration is ready, use `infra\scripts\Test-Infrastructure.ps1` for compilation and subscription ARM **validation only**. This may contact Azure, but does not create the proposed resources. Confirm names, API support, permissions, regional capacity and vision model compatibility before approving deployment. Local compilation alone cannot establish these facts.

After **separate infrastructure approval**, `infra\scripts\Invoke-Deployment.ps1 -ApproveDeployment` provisions infrastructure. After **separate code-publication approval**, `infra\scripts\Publish-Applications.ps1 -ApprovePublication` remotely builds/publishes Functions, bootstraps synthetic demo data using Entra identity, builds the frontend with the actual Functions origin, and publishes the static site. These are mutating steps and must not run during scaffolding or validation. Publication requires Functions Core Tools v4, the Static Web Apps CLI, Node/npm and the backend Python environment. The publication helper keeps the SWA deployment token in process environment only and restores the environment afterward.

Verify health, authentication failures/successes, an image/queue inference cycle, and browser CORS before distributing credentials. Use `infra\scripts\New-DeviceHandoff.ps1` only after the private configuration contains the verified backend URL; distribute its per-device handoff privately. This is a synthetic public demo, not a production healthcare-data deployment.

## Outputs and URL conventions

| Output | Meaning |
| --- | --- |
| `functionAppUrl` | Actual HTTPS Functions **origin without `/api`**; set frontend `VITE_API_URL` to this value. `static-frontend\src\api.ts` appends `/api`. |
| `backendApiUrl` | Actual HTTPS route base **including `/api`**, for API callers/private helper bookkeeping. Do not use it as `VITE_API_URL`. |
| `staticWebAppUrl` | Actual SWA HTTPS origin used by Functions CORS. |
| `storageAccountUrl` | Application **Table** service URL for `STORAGE_ACCOUNT_URL` and bootstrap. |
| `storageBlobUrl`, `storageQueueUrl` | Application Blob/Queue service URLs for bootstrap. |
| `functionAppName`, `resourceGroupName`, `hostStorageAccountName`, `appStorageAccountName`, `keyVaultName` | Resource names for subsequent publishing/operations. |

The runtime also receives identity-based `AzureWebJobsStorage` and `ImageStorage` connection settings, `AZURE_CLIENT_ID`, application service URLs and names, image-size limits, and `FOUNDRY_ENDPOINT` / `FOUNDRY_VISION_DEPLOYMENT`. Connection strings and account keys are not emitted or used.

## API versions and validation limitations

The template retains the approved resource API versions: Web sites/serverfarms `2026-08-01`, staticSites `2025-05-01`, Storage `2026-09-01`, Key Vault `2026-05-15`, Log Analytics `2026-03-01`, Insights `2020-02-02`, managed identity `2024-11-30`, and RBAC `2022-04-01`. Bicep 0.46.1 builds successfully but reports `BCP081` for the newer Web, Storage, Key Vault and Log Analytics types. Those warnings mean local property validation is unavailable, **not** that deployment is validated. No fallback API version was substituted. ARM validation remains a prerequisite; do not silently replace approved versions merely to hide warnings.

The native Flex authentication property was verified against the Microsoft.Web schema returned by the Azure Bicep schema tool. See [Flex deployment identity guidance](https://learn.microsoft.com/azure/azure-functions/flex-consumption-how-to#configure-deployment-settings) and [Functions identity-based host connections](https://learn.microsoft.com/azure/azure-functions/functions-reference#connecting-to-host-storage-with-an-identity).
