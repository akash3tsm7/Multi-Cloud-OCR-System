# Cost Model — Multi-Cloud OCR System

## Azure Costs (per 1,000 images)

| Service | Tier | Cost Estimate |
|---|---|---|
| **Azure Blob Storage** | LRS, ~100 MB images + results | ~$0.002 |
| **Azure Functions** | Consumption (first 1M free/month) | ~$0.00 – $0.20 |
| **Azure Computer Vision** | Read API, S1 tier | ~$1.00 (1,000 transactions) |
| **Application Insights** | First 5 GB/month free | ~$0.00 |
| **Total est. (Azure)** | | **~$1.00–$1.25 per 1,000 images** |

## AWS Costs (per 1,000 images)

| Service | Tier | Cost Estimate |
|---|---|---|
| **AWS S3** | ~100 MB storage + GET/PUT requests | ~$0.005 |
| **AWS Lambda** | 256 MB, ~5s avg, first 1M free | ~$0.00 – $0.08 |
| **AWS Rekognition** | $0.001 per image (first 1M) | ~$1.00 |
| **AWS Textract** | $0.0015 per page (documents) | ~$1.50 (documents only) |
| **API Gateway** | $3.50 per 1M calls | ~$0.004 |
| **Total est. (AWS)** | | **~$1.00–$1.60 per 1,000 images** |

## Smart Routing Cost Savings

The router's primary goal is to minimize cost while maintaining accuracy:

```
Image < 1MB (general photo)  → Azure Vision  ($0.001/img) ← CHEAPER
Image >= 1MB (large photo)   → AWS Rekognition ($0.001/img) ← avoids Azure timeout risk
Document (_doc_ in name)     → AWS Textract ($0.0015/pg) ← best accuracy for docs
Azure Vision fails           → AWS Rekognition (failover)
```

**Estimated savings:** ~15–30% vs. always using one fixed provider.

## Free Tier Summary

| Service | Free Tier |
|---|---|
| Azure Functions | 1M executions/month free |
| Azure Computer Vision | 5,000 transactions/month (F0 tier) |
| AWS Lambda | 1M invocations/month free |
| AWS Rekognition | 1,000 images/month free (first 12 months) |
| AWS Textract | 1,000 pages/month free (first 3 months) |
| AWS S3 | 5 GB + 20K GET + 2K PUT/month free |

> **Dev/Test Tip:** Use Azure Computer Vision F0 + AWS Rekognition free tier for zero-cost development.

## Scaling Cost Projection

| Monthly Volume | Azure Only | AWS Only | Multi-Cloud Routed |
|---|---|---|---|
| 1,000 images | ~$1.25 | ~$1.10 | ~$0.90 |
| 10,000 images | ~$11.00 | ~$10.00 | ~$8.50 |
| 100,000 images | ~$100 | ~$100 | ~$85 |
| 1,000,000 images | ~$1,000 | ~$1,000 | ~$800 |

*Estimates approximate. Actual costs vary by region, image size, and free tier usage.*
