# Confluence AI Assistant 🤖

Serverless AI assistant that syncs Confluence docs and provides intelligent Q&A with daily Slack digests.

![AWS](https://img.shields.io/badge/AWS-FF9900?style=flat&logo=amazon-aws&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![Slack](https://img.shields.io/badge/Slack-4A154B?style=flat&logo=slack&logoColor=white)

## Features

- 🧠 **AI-powered Q&A** using Amazon Bedrock (Claude 3 Sonnet)
- 📅 **Daily Slack digest** with curated “Did you know?” content
- 🌐 **Web interface** for easy querying
- 💰 **Cost-effective** (~$3.35/month on AWS free tier)

## Quick Start

### Prerequisites

- AWS account with Bedrock access
- Confluence API token
- Slack webhook URL (for digest)

### Deploy

**Clone and setup**

```bash
git clone https://github.com/[your-username]/confluence-ai-assistant.git
cd confluence-ai-assistant
```

**Create S3 bucket**

```bash
aws s3 mb s3://confluence-docs-poc-$(date +%s)
```

**Deploy Lambda functions**

- `confluence-data-sync` - Syncs Confluence to S3
- `confluence-ai-query` - Handles AI queries
- `confluence-daily-digest` - Sends Slack messages

**Configure environment variables**

```bash
# All functions need:
S3_BUCKET=your-bucket-name

# Data sync needs:
CONFLUENCE_BASE_URL=https://your-domain.atlassian.net
CONFLUENCE_API_TOKEN=your-api-token

# Daily digest needs:
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

**Schedule daily digest**
   Create EventBridge rule: `cron(0 9 * * ? *)` → `confluence-daily-digest`

## Usage

### Query API

```bash
curl -X POST https://your-function-url/ \
  -H "Content-Type: application/json" \
  -d '{"query": "What is our deployment process?"}'
```

### Web Interface

Open `web-interface/index.html` and update the API endpoint.

## Architecture

```
Confluence → Lambda (Sync) → S3 → Lambda (Query) → Bedrock → Web UI
                                  ↓
                            Lambda (Digest) → Slack
                                  ↑
                            EventBridge (Daily)
```

## Project Structure

```
src/
├── confluence-data-sync/     # Confluence → S3 sync
├── confluence-ai-query/      # AI-powered queries
└── confluence-daily-digest/  # Daily Slack messages
web-interface/
└── index.html               # Chat interface
```

## Costs

|Service  |Monthly Cost|
|---------|------------|
|Lambda   |~$0.20      |
|S3       |~$0.05      |
|Bedrock  |~$3.00      |
|**Total**|**~$3.35**  |

## Troubleshooting

- **Access Denied**: Check IAM permissions for S3/Bedrock
- **Confluence API fails**: Verify API token and URL
- **No Slack messages**: Check webhook URL and EventBridge rule

## Contributing

1. Fork the repo
1. Create feature branch
1. Submit pull request

## License

MIT License - see <LICENSE> file.

-----

**Built with AWS serverless • [LinkedIn](https://www.linkedin.com/in/brianmaiyo/) • [Issues](https://github.com/brianmaiyo/confluence-ai-assistant/issues)**
