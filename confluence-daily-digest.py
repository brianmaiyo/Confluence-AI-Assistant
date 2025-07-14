import json
import boto3
import random
import os
import re
import urllib3
from datetime import datetime
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
http = urllib3.PoolManager()

def lambda_handler(event, context):
    """
    Lambda function to send daily "Did you know?" messages from Confluence to Slack
    """
    try:
        # Configuration - set these as environment variables
        S3_BUCKET = os.environ.get('S3_BUCKET')
        SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
        CONFLUENCE_INDEX_FILE = 'YOUR_INDEXED_FILE'
        
        if not SLACK_WEBHOOK_URL:
            raise ValueError("SLACK_WEBHOOK_URL environment variable is required")
        
        # Step 1: Fetch Confluence data from S3
        logger.info(f"Fetching Confluence data from S3: {S3_BUCKET}/{CONFLUENCE_INDEX_FILE}")
        confluence_data = fetch_confluence_data(S3_BUCKET, CONFLUENCE_INDEX_FILE)
        
        if not confluence_data:
            logger.error("No Confluence data found")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'No Confluence data available'})
            }
        
        # Step 2: Extract and select interesting content
        logger.info("Extracting interesting content snippets")
        interesting_snippets = extract_interesting_snippets(confluence_data)
        
        if not interesting_snippets:
            logger.error("No interesting snippets found")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'No interesting content found'})
            }
        
        # Step 3: Select random snippet for today's digest
        selected_snippet = select_daily_snippet(interesting_snippets)
        
        # Step 4: Format as "Did you know?" message
        slack_message = format_slack_message(selected_snippet)
        
        # Step 5: Send to Slack
        logger.info("Sending message to Slack")
        response = send_to_slack(SLACK_WEBHOOK_URL, slack_message)
        
        logger.info(f"Daily digest sent successfully: {selected_snippet['title']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Daily digest sent successfully',
                'snippet_title': selected_snippet['title'],
                'slack_response': response
            })
        }
        
    except Exception as e:
        logger.error(f"Error in daily digest: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def fetch_confluence_data(bucket, key):
    """Fetch Confluence data from S3"""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        return data
    except Exception as e:
        logger.error(f"Error fetching from S3: {str(e)}")
        return None

def extract_interesting_snippets(confluence_data):
    """Extract interesting snippets from Confluence content"""
    snippets = []
    
    for item in confluence_data:
        content = item.get('content', '')
        title = item.get('title', '')
        url = item.get('url', '')
        space = item.get('space', '')
        
        # Skip if content is too short
        if len(content) < 100:
            continue
        
        # Extract interesting sentences/paragraphs
        interesting_parts = find_interesting_content(content, title, url, space)
        snippets.extend(interesting_parts)
    
    return snippets

def find_interesting_content(content, title, url, space):
    """Find interesting content patterns within a page"""
    snippets = []
    
    # Split content into sentences
    sentences = re.split(r'[.!?]+', content)
    
    # Patterns that indicate interesting content
    interesting_patterns = [
        r'\b(did you know|fun fact|interesting|tip|best practice|important|note|remember)\b',
        r'\b(how to|step by step|process|procedure|workflow)\b',
        r'\b(feature|capability|benefit|advantage|improvement)\b',
        r'\b(definition|explanation|overview|summary)\b',
        r'\b(example|instance|case study|scenario)\b',
        r'\b(warning|caution|avoid|don\'t|never)\b',
        r'\b(new|latest|recent|updated|change)\b',
        r'\b(integration|api|configuration|setup)\b'
    ]
    
    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        
        # Skip short sentences
        if len(sentence) < 50 or len(sentence) > 300:
            continue
        
        # Check for interesting patterns
        score = 0
        for pattern in interesting_patterns:
            if re.search(pattern, sentence, re.IGNORECASE):
                score += 1
        
        # Also check if it's a list item or definition
        if sentence.startswith(('•', '-', '*', '1.', '2.', '3.')) or ':' in sentence:
            score += 1
        
        # If sentence seems interesting, add it
        if score > 0:
            # Get some context (surrounding sentences)
            context_start = max(0, i - 1)
            context_end = min(len(sentences), i + 2)
            context = '. '.join(sentences[context_start:context_end]).strip()
            
            # Clean up the context
            context = clean_content(context)
            
            if len(context) > 50:
                snippets.append({
                    'content': context,
                    'title': title,
                    'url': url,
                    'space': space,
                    'score': score,
                    'type': classify_content_type(context)
                })
    
    return snippets

def clean_content(content):
    """Clean and format content for Slack"""
    # Remove HTML tags
    content = re.sub(r'<[^>]+>', '', content)
    
    # Remove extra whitespace
    content = re.sub(r'\s+', ' ', content)
    
    # Remove special characters that might cause issues
    content = content.replace('&nbsp;', ' ')
    content = content.replace('&amp;', '&')
    content = content.replace('&lt;', '<')
    content = content.replace('&gt;', '>')
    
    return content.strip()

def classify_content_type(content):
    """Classify the type of content for better messaging"""
    content_lower = content.lower()
    
    if any(word in content_lower for word in ['how to', 'step', 'process', 'procedure']):
        return 'process'
    elif any(word in content_lower for word in ['tip', 'best practice', 'recommendation']):
        return 'tip'
    elif any(word in content_lower for word in ['feature', 'capability', 'new', 'update']):
        return 'feature'
    elif any(word in content_lower for word in ['definition', 'explanation', 'what is']):
        return 'definition'
    elif any(word in content_lower for word in ['warning', 'caution', 'avoid', 'don\'t']):
        return 'warning'
    else:
        return 'general'

def select_daily_snippet(snippets):
    """Select a snippet for today's digest"""
    if not snippets:
        return None
    
    # Sort by score (highest first) and take top 20%
    sorted_snippets = sorted(snippets, key=lambda x: x['score'], reverse=True)
    top_snippets = sorted_snippets[:max(1, len(sorted_snippets) // 5)]
    
    # Randomly select from top snippets
    return random.choice(top_snippets)

def format_slack_message(snippet):
    """Format the snippet as a Slack message"""
    content_type = snippet['type']
    
    # Choose appropriate emoji and prefix based on content type
    type_config = {
        'process': {'emoji': '⚙️', 'prefix': 'Process tip'},
        'tip': {'emoji': '💡', 'prefix': 'Pro tip'},
        'feature': {'emoji': '🆕', 'prefix': 'Feature spotlight'},
        'definition': {'emoji': '📚', 'prefix': 'Definition'},
        'warning': {'emoji': '⚠️', 'prefix': 'Important note'},
        'general': {'emoji': '🤔', 'prefix': 'Did you know'}
    }
    
    config = type_config.get(content_type, type_config['general'])
    emoji = config['emoji']
    prefix = config['prefix']
    
    # Format the message
    message = {
        "text": f"{emoji} Daily Confluence Digest",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {prefix}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{snippet['title']}*\n\n{snippet['content']}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"📍 Space: {snippet['space']} | <{snippet['url']}|Read more>"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Daily digest from Confluence • {datetime.now().strftime('%B %d, %Y')}_"
                    }
                ]
            }
        ]
    }
    
    return message

def send_to_slack(webhook_url, message):
    """Send message to Slack via webhook"""
    try:
        encoded_msg = json.dumps(message).encode('utf-8')
        
        response = http.request(
            'POST',
            webhook_url,
            body=encoded_msg,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status != 200:
            raise Exception(f"Slack webhook failed with status {response.status}: {response.data}")
        
        return {
            'status': response.status,
            'response': response.data.decode('utf-8')
        }
        
    except Exception as e:
        logger.error(f"Error sending to Slack: {str(e)}")
        raise

# Additional utility function for testing
def test_handler(event, context):
    """Test function to preview messages without sending to Slack"""
    # Same logic as lambda_handler but returns the message instead of sending
    # Useful for testing locally
    pass