import json
import boto3
import os
import urllib.request
import urllib.parse
import base64
import logging
import re
from typing import Dict, List, Any
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
bedrock_client = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

# Configuration - all from environment variables
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME")

def lambda_handler(event, context):
    """
    Main Lambda handler - Handles Lambda console, API Gateway, and frontend requests
    """

    CORS_HEADERS = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Access-Control-Allow-Headers": "*"
    }

    # 🔍 Detect HTTP method robustly
    method = (
        event.get('requestContext', {}).get('http', {}).get('method') or
        event.get('httpMethod') or
        (event.get('headers', {}).get('Origin') and 'OPTIONS')
    )

    # ✅ Handle CORS preflight
    if method == "OPTIONS":
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'message': 'CORS preflight OK'})
        }

    try:
        logger.info(f"Received event: {json.dumps(event)}")

        # Validate required environment variables
        if not S3_BUCKET:
            logger.error("S3_BUCKET_NAME environment variable is not set")
            return {
                'statusCode': 500,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Server configuration error: S3_BUCKET_NAME not set'})
            }

        # ✅ Extract query from different sources
        if "query" in event:
            query = event["query"]
        elif "body" in event:
            try:
                body = json.loads(event["body"]) if isinstance(event["body"], str) else event["body"]
                query = body.get("query", "")
            except:
                query = ""
        else:
            query = ""

        if not query:
            return {
                'statusCode': 400,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': 'Query parameter is required'})
            }

        logger.info(f"Processing query: {query}")

        # Step 1: Search through stored Confluence content
        search_results = search_confluence_content(query)

        # Step 2: Generate AI response using Bedrock
        ai_response = generate_ai_response(query, search_results)

        # Step 3: Return response
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({
                'query': query,
                'answer': ai_response,
                'sources': [
                    {
                        'title': result.get('title', 'Unknown'),
                        'url': result.get('url', ''),
                        'excerpt': result.get('content', '')[:200] + '...' if len(result.get('content', '')) > 200 else result.get('content', '')
                    }
                    for result in search_results
                ]
            })
        }

    except Exception as e:
        logger.error(f"Error processing query: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': f'Internal server error: {str(e)}'})
        }

def search_confluence_content(query: str) -> List[Dict]:
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key='confluence-index.json')
        content_index = json.loads(response['Body'].read().decode('utf-8'))

        query_words = query.lower().split()
        results = []

        for doc in content_index:
            title = doc.get('title', '').lower()
            content = doc.get('content', '').lower()
            score = sum(3 for word in query_words if word in title) + \
                    sum(1 for word in query_words if word in content)

            if score > 0:
                results.append({
                    'title': doc.get('title', ''),
                    'content': doc.get('content', ''),
                    'url': doc.get('url', ''),
                    'score': score
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f"Found {len(results)} results from simple search")
        return results[:5]

    except Exception as e:
        logger.error(f"Error searching content: {str(e)}")
        return []


def generate_ai_response(query: str, search_results: List[Dict]) -> str:
    try:
        context = ""
        for i, result in enumerate(search_results, 1):
            title = result.get('title', 'Unknown Document')
            content = result.get('content', '')[:1000]
            context += f"\n\nDocument {i}: {title}\n{content}"

        prompt = f"""Based on the following Confluence documentation, please answer the user's question. 
If the information isn't available in the provided context, please say so.

Context from Confluence:{context}

User Question: {query}

Please provide a helpful and accurate answer based on the context above:"""

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        response = bedrock_client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps(request_body),
            contentType='application/json'
        )

        response_body = json.loads(response['body'].read())
        ai_answer = response_body.get('content', [{}])[0].get('text', 'No response generated')

        logger.info("Generated AI response successfully")
        return ai_answer

    except Exception as e:
        logger.error(f"Error generating AI response: {str(e)}")
        return f"I found some relevant information in your Confluence docs, but couldn't generate a proper response. Error: {str(e)}"


def make_confluence_request(url: str, auth_header: str) -> dict:
    try:
        req = urllib.request.Request(url)
        req.add_header('Authorization', auth_header)
        req.add_header('Content-Type', 'application/json')

        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Error making Confluence request: {str(e)}")
        raise


def sync_confluence_to_s3():
    """
    Sync Confluence content to S3 - requires environment variables to be set
    """
    try:
        # Validate required environment variables for sync
        if not all([CONFLUENCE_BASE_URL, CONFLUENCE_API_TOKEN, CONFLUENCE_USERNAME, S3_BUCKET]):
            missing_vars = []
            if not CONFLUENCE_BASE_URL:
                missing_vars.append("CONFLUENCE_BASE_URL")
            if not CONFLUENCE_API_TOKEN:
                missing_vars.append("CONFLUENCE_API_TOKEN")
            if not CONFLUENCE_USERNAME:
                missing_vars.append("CONFLUENCE_USERNAME")
            if not S3_BUCKET:
                missing_vars.append("S3_BUCKET_NAME")
            
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        confluence_docs = []

        auth_string = f"{CONFLUENCE_USERNAME}:{CONFLUENCE_API_TOKEN}"
        auth_bytes = auth_string.encode('ascii')
        auth_header = f"Basic {base64.b64encode(auth_bytes).decode('ascii')}"

        spaces_url = f"{CONFLUENCE_BASE_URL}/wiki/rest/api/space"
        spaces_data = make_confluence_request(spaces_url, auth_header)
        spaces = spaces_data['results']

        for space in spaces[:3]:
            space_key = space['key']
            logger.info(f"Processing space: {space_key}")

            pages_url = f"{CONFLUENCE_BASE_URL}/wiki/rest/api/content?spaceKey={space_key}&expand=body.storage,version&limit=25"
            pages_data = make_confluence_request(pages_url, auth_header)

            for page in pages_data['results']:
                try:
                    html_content = page['body']['storage']['value']
                    clean_content = extract_text_from_html(html_content)

                    doc = {
                        'id': page['id'],
                        'title': page['title'],
                        'content': clean_content,
                        'url': f"{CONFLUENCE_BASE_URL}/wiki{page['_links']['webui']}",
                        'space': space_key,
                        'last_modified': page['version']['when']
                    }

                    confluence_docs.append(doc)
                    logger.info(f"Processed page: {page['title']}")

                except Exception as e:
                    logger.error(f"Error processing page {page.get('title', 'unknown')}: {str(e)}")

        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key='confluence-index.json',
            Body=json.dumps(confluence_docs, indent=2),
            ContentType='application/json'
        )

        logger.info(f"Synced {len(confluence_docs)} documents to S3")

    except Exception as e:
        logger.error(f"Error during Confluence sync: {str(e)}")
        raise


def extract_text_from_html(html_content: str) -> str:
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', html_content)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


if __name__ == "__main__":
    sync_confluence_to_s3()