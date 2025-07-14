import json
import boto3
import urllib.request
import urllib.parse
import urllib.error
import base64
import logging
import re
import os

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')

# Configuration - all from environment variables
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL")
CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")

def create_auth_header(username, api_token):
    """Create Basic Auth header"""
    credentials = f"{username}:{api_token}"
    logger.info(f"Creating auth for username: {username}")
    logger.info(f"Credentials string length: {len(credentials)}")
    
    # Encode credentials
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    logger.info(f"Encoded credentials length: {len(encoded_credentials)}")
    logger.info(f"Encoded credentials (first 20 chars): {encoded_credentials[:20]}...")
    
    auth_header = f"Basic {encoded_credentials}"
    logger.info(f"Auth header length: {len(auth_header)}")
    
    return auth_header

def make_request(url, auth_header, params=None):
    """Make HTTP request using urllib"""
    try:
        if params:
            url += '?' + urllib.parse.urlencode(params)
        
        logger.info(f"Making request to: {url}")
        logger.info(f"Auth header: {auth_header[:50]}...")
        
        req = urllib.request.Request(url)
        req.add_header('Authorization', auth_header)
        req.add_header('Content-Type', 'application/json')
        req.add_header('Accept', 'application/json')
        req.add_header('User-Agent', 'Lambda-Confluence-Sync/1.0')
        
        # Log all headers being sent
        logger.info(f"Request headers: {dict(req.headers)}")
        
        with urllib.request.urlopen(req, timeout=30) as response:
            response_data = response.read().decode('utf-8')
            logger.info(f"Response status: {response.getcode()}")
            logger.info(f"Response data length: {len(response_data)}")
            
            return {
                'status_code': response.getcode(),
                'data': json.loads(response_data)
            }
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8') if e.fp else str(e)
        logger.error(f"HTTP Error {e.code}: {error_body[:500]}")
        return {
            'status_code': e.code,
            'error': error_body
        }
    except Exception as e:
        logger.error(f"Request failed: {str(e)}")
        return {
            'status_code': 500,
            'error': str(e)
        }

def lambda_handler(event, context):
    """
    Sync Confluence content to S3 with enhanced debugging
    """
    logger.info("=== STARTING CONFLUENCE DATA SYNC ===")
    
    # Validate required environment variables
    required_vars = {
        'S3_BUCKET_NAME': S3_BUCKET,
        'CONFLUENCE_BASE_URL': CONFLUENCE_BASE_URL,
        'CONFLUENCE_USERNAME': CONFLUENCE_USERNAME,
        'CONFLUENCE_API_TOKEN': CONFLUENCE_API_TOKEN
    }
    
    missing_vars = [var_name for var_name, var_value in required_vars.items() if not var_value]
    
    if missing_vars:
        error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
        logger.error(error_msg)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': error_msg,
                'missing_variables': missing_vars
            })
        }
    
    logger.info(f"S3_BUCKET: {S3_BUCKET}")
    logger.info(f"CONFLUENCE_BASE_URL: {CONFLUENCE_BASE_URL}")
    logger.info(f"CONFLUENCE_USERNAME: {CONFLUENCE_USERNAME}")
    logger.info(f"API_TOKEN length: {len(CONFLUENCE_API_TOKEN)}")
    
    try:
        logger.info("Starting Confluence data sync...")
        
        confluence_docs = []
        auth_header = create_auth_header(CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN)
        
        # Test basic connectivity first
        logger.info("Testing Confluence API connectivity...")
        test_url = f"{CONFLUENCE_BASE_URL}/wiki/rest/api/space"
        test_params = {'limit': 1}
        logger.info(f"Testing URL: {test_url}")
        
        test_response = make_request(test_url, auth_header, test_params)
        logger.info(f"Test response status: {test_response['status_code']}")
        
        if test_response['status_code'] != 200:
            logger.error(f"API test failed: {test_response['status_code']} - {test_response.get('error', 'Unknown error')}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': f'Confluence API test failed: {test_response["status_code"]}',
                    'details': str(test_response.get('error', 'Unknown error'))[:500]
                })
            }
        
        # Get Confluence spaces
        logger.info("Fetching Confluence spaces...")
        spaces_url = f"{CONFLUENCE_BASE_URL}/wiki/rest/api/space"
        spaces_response = make_request(spaces_url, auth_header)
        
        if spaces_response['status_code'] != 200:
            logger.error(f"Failed to get spaces: {spaces_response['status_code']} - {spaces_response.get('error', 'Unknown error')}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': f'Failed to get spaces: {spaces_response["status_code"]}',
                    'details': str(spaces_response.get('error', 'Unknown error'))[:500]
                })
            }
        
        spaces_data = spaces_response['data']
        spaces = spaces_data.get('results', [])
        logger.info(f"Found {len(spaces)} spaces")
        
        if not spaces:
            logger.warning("No spaces found in Confluence")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No spaces found in Confluence',
                    'documents': 0
                })
            }
        
        # Process each space (limit to first 3 for PoC)
        spaces_processed = 0
        for space in spaces[:3]:  # Limit for PoC
            space_key = space['key']
            space_name = space.get('name', 'Unknown')
            logger.info(f"Processing space: {space_key} ({space_name})")
            
            # Get pages in space
            pages_url = f"{CONFLUENCE_BASE_URL}/wiki/rest/api/content"
            params = {
                'spaceKey': space_key,
                'expand': 'body.storage,version',
                'limit': 25  # Limit pages per space for PoC
            }
            
            pages_response = make_request(pages_url, auth_header, params)
            if pages_response['status_code'] != 200:
                logger.error(f"Failed to get pages for space {space_key}: {pages_response['status_code']}")
                continue
            
            pages_data = pages_response['data']
            pages = pages_data.get('results', [])
            logger.info(f"Found {len(pages)} pages in space {space_key}")
            
            pages_processed = 0
            for page in pages:
                try:
                    # Extract and clean content
                    page_body = page.get('body', {})
                    storage = page_body.get('storage', {})
                    html_content = storage.get('value', '')
                    
                    if not html_content:
                        logger.warning(f"No content found for page: {page.get('title', 'Unknown')}")
                        continue
                    
                    clean_content = extract_text_from_html(html_content)
                    
                    # Build document
                    doc = {
                        'id': page['id'],
                        'title': page['title'],
                        'content': clean_content,
                        'url': f"{CONFLUENCE_BASE_URL}/wiki{page['_links']['webui']}",
                        'space': space_key,
                        'last_modified': page['version']['when']
                    }
                    
                    confluence_docs.append(doc)
                    pages_processed += 1
                    logger.info(f"Processed page {pages_processed}: {page['title']}")
                    
                except Exception as e:
                    logger.error(f"Error processing page {page.get('title', 'unknown')}: {str(e)}")
                    continue
            
            logger.info(f"Completed space {space_key}: {pages_processed} pages processed")
            spaces_processed += 1
        
        logger.info(f"Total documents collected: {len(confluence_docs)}")
        
        if not confluence_docs:
            logger.warning("No documents were collected")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No documents found to sync',
                    'documents': 0
                })
            }
        
        # Test S3 access
        logger.info("Testing S3 bucket access...")
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET)
            logger.info("S3 bucket access confirmed")
        except Exception as e:
            logger.error(f"S3 bucket access failed: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': f'S3 bucket access failed: {str(e)}'
                })
            }
        
        # Save to S3
        logger.info("Saving documents to S3...")
        try:
            s3_client.put_object(
                Bucket=S3_BUCKET,
                Key='confluence-index.json',
                Body=json.dumps(confluence_docs, indent=2),
                ContentType='application/json'
            )
            logger.info(f"Successfully saved {len(confluence_docs)} documents to S3")
        except Exception as e:
            logger.error(f"Failed to save to S3: {str(e)}")
            return {
                'statusCode': 500,
                'body': json.dumps({
                    'error': f'Failed to save to S3: {str(e)}'
                })
            }
        
        logger.info("=== CONFLUENCE DATA SYNC COMPLETED SUCCESSFULLY ===")
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'Successfully synced {len(confluence_docs)} documents',
                'documents': len(confluence_docs),
                'spaces_processed': spaces_processed
            })
        }
        
    except Exception as e:
        logger.error(f"Unexpected error during sync: {str(e)}")
        logger.error(f"Error type: {type(e).__name__}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Unexpected error: {str(e)}',
                'error_type': type(e).__name__
            })
        }

def extract_text_from_html(html_content: str) -> str:
    """
    Extract plain text from HTML content
    """
    if not html_content:
        return ""
    
    try:
        # Simple HTML tag removal
        clean = re.compile('<.*?>')
        text = re.sub(clean, '', html_content)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    except Exception as e:
        logger.error(f"Error extracting text from HTML: {str(e)}")
        return html_content  # Return original if extraction fails