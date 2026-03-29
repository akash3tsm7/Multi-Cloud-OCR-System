# Azure Infrastructure Setup Guide

## Resources to Provision

### 1. Storage Account

```bash
# Resource group (reuse existing or create new)
az group create --name rg-ocr-multicloud --location eastus

# Storage Account
az storage account create \
  --name rgocrmulticloudacbc \
  --resource-group rg-ocr-multicloud \
  --location eastus \
  --sku Standard_LRS

# Blob containers
az storage container create --name input-images \
  --account-name rgocrmulticloudacbc

az storage container create --name output-results \
  --account-name rgocrmulticloudacbc

# Get connection string
az storage account show-connection-string \
  --name rgocrmulticloudacbc \
  --resource-group rg-ocr-multicloud \
  --query connectionString -o tsv
```

### 2. Azure Computer Vision

```bash
az cognitiveservices account create \
  --name ocrvision-akash-2026 \
  --resource-group rg-ocr-multicloud \
  --kind ComputerVision \
  --sku S1 \
  --location eastus \
  --yes

# Get key and endpoint
az cognitiveservices account keys list \
  --name ocrvision-akash-2026 \
  --resource-group rg-ocr-multicloud

az cognitiveservices account show \
  --name ocrvision-akash-2026 \
  --resource-group rg-ocr-multicloud \
  --query properties.endpoint -o tsv
```

### 3. Application Insights

```bash
az extension add --name application-insights 2>/dev/null || true

az monitor app-insights component create \
  --app ocr-appinsights \
  --location eastus \
  --resource-group rg-ocr-multicloud \
  --application-type web

# Get instrumentation key
az monitor app-insights component show \
  --app ocr-appinsights \
  --resource-group rg-ocr-multicloud \
  --query instrumentationKey -o tsv
```

### 4. Function App

```bash
# App Service Plan (Consumption = serverless)
az functionapp create \
  --name ocr-serverless-func \
  --resource-group rg-ocr-multicloud \
  --storage-account rgocrmulticloudacbc \
  --consumption-plan-location eastus \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4

# Set environment variables
az functionapp config appsettings set \
  --name ocr-serverless-func \
  --resource-group rg-ocr-multicloud \
  --settings \
    "AZURE_STORAGE_CONNECTION_STRING=<CONNECTION_STRING>" \
    "AZURE_VISION_KEY=<VISION_KEY>" \
    "AZURE_VISION_ENDPOINT=https://ocrvision-akash-2026.cognitiveservices.azure.com/" \
    "APPINSIGHTS_INSTRUMENTATIONKEY=<APPINSIGHTS_KEY>" \
    "AWS_ACCESS_KEY_ID=<KEY>" \
    "AWS_SECRET_ACCESS_KEY=<SECRET>" \
    "AWS_REGION=us-east-1" \
    "AWS_S3_INPUT_BUCKET=ocr-input-bucket" \
    "AWS_S3_OUTPUT_BUCKET=ocr-output-bucket"
```

### 5. Deploy Functions

```bash
cd azure-functions/
func azure functionapp publish ocr-serverless-func
```

## Useful Test Commands

```bash
# Upload a test image
az storage blob upload \
  --account-name rgocrmulticloudacbc \
  --container-name input-images \
  --file tests/sample.jpg \
  --name sample.jpg

# Check OCR result (wait ~10s for trigger)
az storage blob download \
  --account-name rgocrmulticloudacbc \
  --container-name output-results \
  --name sample.jpg.txt \
  --file /tmp/result.txt
cat /tmp/result.txt

# Call HTTP API
curl -X POST "https://ocr-serverless-func.azurewebsites.net/api/ocr" \
  -H "Content-Type: application/json" \
  -d '{"blob_name": "sample.jpg"}'

curl "https://ocr-serverless-func.azurewebsites.net/api/ocr/sample.jpg"
```
